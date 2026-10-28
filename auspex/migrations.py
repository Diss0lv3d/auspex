"""Schema v0 — idempotent startup migration.

D-008: `workspace_id` on EVERY table from day one. The single exception is
`workspaces` itself, whose primary key IS the workspace id. The schema test
enforces this invariant against the live database.

Every statement is IF NOT EXISTS / idempotent: running this N times is safe,
which is the whole migration strategy for v0 (no version table yet).
"""

import logging

import asyncpg

logger = logging.getLogger("auspex.migrations")

# Held by a booting replica while it re-runs the schema; the jobs queue takes it shared.
MIGRATION_LOCK = 715001

SCHEMA_V0: list[str] = [
    'CREATE EXTENSION IF NOT EXISTS "pgcrypto"',
    """
    CREATE TABLE IF NOT EXISTS workspaces (
        id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        name        text NOT NULL,
        created_at  timestamptz NOT NULL DEFAULT now()
    )
    """,
    # UNIQUE on name makes get-or-create race-safe (ON CONFLICT) and prevents two
    # concurrent first logins from splitting one identity across duplicate workspaces.
    # Separate index statement so it also applies to pre-existing tables (idempotent).
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_workspaces_name ON workspaces (name)",
    """
    CREATE TABLE IF NOT EXISTS users (
        id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        email         text NOT NULL,
        display_name  text NOT NULL DEFAULT '',
        google_sub    text,
        role          text NOT NULL DEFAULT 'analyst',
        created_at    timestamptz NOT NULL DEFAULT now(),
        UNIQUE (workspace_id, email)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS api_keys (
        id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name          text NOT NULL DEFAULT '',
        key_prefix    text NOT NULL,
        key_hash      text NOT NULL UNIQUE,
        created_at    timestamptz NOT NULL DEFAULT now(),
        last_used_at  timestamptz,
        revoked_at    timestamptz
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title         text NOT NULL DEFAULT '',
        created_at    timestamptz NOT NULL DEFAULT now(),
        updated_at    timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        session_id    uuid NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
        role          text NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
        content       text NOT NULL,
        created_at    timestamptz NOT NULL DEFAULT now()
    )
    """,
    # S2: one row per capability-probe run of a customer LLM endpoint (D-005).
    # endpoint_fingerprint = sha256(base_url|model) — identifies the endpoint
    # without ever storing its API key. agent_mode is what the runtime compiles
    # to (code picks the mode from the typed scorecard, not the prompt).
    """
    CREATE TABLE IF NOT EXISTS llm_endpoint_scorecards (
        id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id          uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        endpoint_fingerprint  text NOT NULL,
        base_url              text NOT NULL,
        model                 text NOT NULL,
        agent_mode            text NOT NULL
            CHECK (agent_mode IN ('native_tools', 'prompted_tools', 'plan_only')),
        scorecard             jsonb NOT NULL,
        probed_at             timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_llm_scorecards_ws_fp
        ON llm_endpoint_scorecards (workspace_id, endpoint_fingerprint, probed_at DESC)
    """,
    # S3 (D-014): a write/destructive tool call routed through the permission
    # gate becomes a PROPOSAL, never an execution. A proposal is only ever
    # created from a real tool call — model text claiming an action was done
    # mints nothing here. session_id is nullable + SET NULL so the audit trail
    # of proposed actions outlives the chat session that spawned it.
    """
    CREATE TABLE IF NOT EXISTS proposals (
        id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        session_id    uuid REFERENCES chat_sessions(id) ON DELETE SET NULL,
        tool_name     text NOT NULL,
        tool_level    text NOT NULL CHECK (tool_level IN ('write', 'destructive')),
        tool_input    jsonb NOT NULL,
        status        text NOT NULL DEFAULT 'pending_approval'
            CHECK (status IN ('pending_approval', 'approved', 'rejected', 'executed')),
        created_at    timestamptz NOT NULL DEFAULT now(),
        decided_at    timestamptz,
        decided_by    uuid REFERENCES users(id) ON DELETE SET NULL,
        result        jsonb
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_proposals_ws_status
        ON proposals (workspace_id, status, created_at DESC)
    """,
    # S5: enrichment substrate. `observables` is keyed by the S4-normalized
    # (type, value) per workspace; obs_id is the short deterministic id users
    # reference in chat ("check ipv4-9c463859 again"). `verdicts` is APPEND-ONLY
    # with decay-curve fields from day one (D-017, first Living Verdicts brick):
    # effective confidence at t = floor + (confidence_at_write - floor)
    #                              * 2^(-(t - created_at)/half_life_days).
    """
    CREATE TABLE IF NOT EXISTS observables (
        id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        obs_id        text NOT NULL,
        type          text NOT NULL CHECK (type IN
            ('ipv4', 'ipv6', 'domain', 'url', 'sha256', 'sha1', 'md5', 'email', 'cve')),
        value         text NOT NULL,
        first_seen    timestamptz NOT NULL DEFAULT now(),
        last_seen     timestamptz NOT NULL DEFAULT now(),
        UNIQUE (workspace_id, type, value)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_observables_ws_obsid ON observables (workspace_id, obs_id)",
    """
    CREATE TABLE IF NOT EXISTS verdicts (
        id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id         uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        observable_id        uuid NOT NULL REFERENCES observables(id) ON DELETE CASCADE,
        label                text NOT NULL CHECK (label IN
            ('malicious', 'suspicious', 'benign', 'unknown')),
        confidence_at_write  real NOT NULL
            CHECK (confidence_at_write >= 0 AND confidence_at_write <= 1),
        half_life_days       real NOT NULL CHECK (half_life_days > 0),
        floor                real NOT NULL DEFAULT 0
            CHECK (floor >= 0 AND floor <= confidence_at_write),
        source               text NOT NULL,
        details              jsonb NOT NULL DEFAULT '{}',
        -- clock_timestamp(), NOT now(): see the S15 Step 0 note at the end of
        -- this list. This column IS the definition of "the current verdict"
        -- (latest_verdict, the retro-hunt sweep's LATERAL), so it must order by
        -- when the row was WRITTEN, not by when its transaction began.
        created_at           timestamptz NOT NULL DEFAULT clock_timestamp()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_verdicts_ws_obs
        ON verdicts (workspace_id, observable_id, created_at DESC)
    """,
    # S7: per-feed ingestion watermarks (NVD delta / KEV / EPSS). KB content is
    # platform-global (workspace_id "" in the OpenSearch index), so feed state
    # is too: workspace_id is NULLABLE here — NULL = global feed — keeping the
    # D-008 column for the day workspace-private sources exist. `cursor` is
    # jsonb because watermark shapes differ per feed (NVD: lastMod window end;
    # KEV: HTTP Last-Modified + dateAdded horizon).
    """
    CREATE TABLE IF NOT EXISTS ingest_state (
        id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id  uuid REFERENCES workspaces(id) ON DELETE CASCADE,
        feed          text NOT NULL,
        cursor        jsonb NOT NULL DEFAULT '{}',
        last_run_at   timestamptz,
        last_status   text NOT NULL DEFAULT '',
        docs_upserted bigint NOT NULL DEFAULT 0,
        updated_at    timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_ingest_state_global_feed
        ON ingest_state (feed) WHERE workspace_id IS NULL
    """,
    "CREATE INDEX IF NOT EXISTS idx_api_keys_workspace ON api_keys (workspace_id)",
    "CREATE INDEX IF NOT EXISTS idx_chat_sessions_ws_user ON chat_sessions (workspace_id, user_id)",
    """
    CREATE INDEX IF NOT EXISTS idx_messages_ws_session
        ON messages (workspace_id, session_id, created_at)
    """,
    # S12: the ACH substrate (D-019). An `investigations` row is the durable
    # container for one competing-hypotheses analysis of one subject (an alert
    # or email paste). `hypotheses` stores IDENTITY only (key + wording) —
    # status/scores/weights are recomputed from evidence by auspex.ach.matrix
    # on every read, so the math has a single source of truth and a fixed table
    # can never drift from it. `ach_evidence` is APPEND-ONLY like verdicts:
    # each row carries its curated cell vector as written, so a later change
    # to the doctrine tables re-scores the future without rewriting the past.
    """
    CREATE TABLE IF NOT EXISTS investigations (
        id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        session_id    uuid REFERENCES chat_sessions(id) ON DELETE SET NULL,
        subject_kind  text NOT NULL CHECK (subject_kind IN ('alert', 'email')),
        subject       jsonb NOT NULL DEFAULT '{}',
        status        text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
        created_at    timestamptz NOT NULL DEFAULT now(),
        updated_at    timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_investigations_ws
        ON investigations (workspace_id, created_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS hypotheses (
        id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id      uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        investigation_id  uuid NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
        key               text NOT NULL CHECK (key IN
            ('true_positive', 'false_positive', 'benign_activity', 'test_activity')),
        label             text NOT NULL,
        created_at        timestamptz NOT NULL DEFAULT now(),
        UNIQUE (investigation_id, key)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_hypotheses_ws_inv
        ON hypotheses (workspace_id, investigation_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS ach_evidence (
        id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id      uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        investigation_id  uuid NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
        kind              text NOT NULL,
        statement         text NOT NULL,
        credibility       real NOT NULL CHECK (credibility >= 0 AND credibility <= 1),
        cells             jsonb NOT NULL,
        source            text NOT NULL,
        obs_id            text,
        created_at        timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ach_evidence_ws_inv
        ON ach_evidence (workspace_id, investigation_id, created_at)
    """,
    # S14: retro-hunt (Phase 3 flagship). New intel sweeps the workspace's
    # HISTORICAL observables for matches. The sweep is an INDEXED JOIN, never a
    # scan per DocChange, and ingest is platform-global (feeds are not
    # workspace-private), so it must find matches ACROSS workspaces in one
    # query: `WHERE type = 'cve' AND value = ANY($1)`. The existing
    # UNIQUE (workspace_id, type, value) index cannot serve that — its leading
    # column is workspace_id, which the sweep does not know yet. Hence a
    # (type, value) index; tenancy is preserved by carrying each match's
    # workspace_id into the event row it writes.
    "CREATE INDEX IF NOT EXISTS idx_observables_type_value ON observables (type, value)",
    # One row per (observable, triggering doc): the analyst-visible "this
    # settled observable just showed up in new intel" event. The honesty rail
    # of D-017 is structural here — a match records the verdict label as it
    # stood AT MATCH TIME and NEVER writes a verdict. It is a reason to
    # re-examine, not a re-classification.
    # UNIQUE makes re-emission idempotent: the KEV first-run refresh re-emits
    # every held KEV id on a fresh volume, and a catalog re-read can repeat ids.
    """
    CREATE TABLE IF NOT EXISTS retrohunt_matches (
        id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id   uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        observable_id  uuid NOT NULL REFERENCES observables(id) ON DELETE CASCADE,
        doc_id         text NOT NULL,
        feed           text NOT NULL,
        change_kind    text NOT NULL,
        verdict_id     uuid REFERENCES verdicts(id) ON DELETE SET NULL,
        verdict_label  text,
        status         text NOT NULL DEFAULT 'open'
            CHECK (status IN ('open', 'reviewed')),
        -- clock_timestamp() (S15 Step 0 note below): record_matches writes a
        -- whole sweep's rows in ONE transaction, so under now() every match in
        -- a batch shares a timestamp and open_match_for's "newest open match"
        -- picks arbitrarily among them.
        created_at     timestamptz NOT NULL DEFAULT clock_timestamp(),
        UNIQUE (workspace_id, observable_id, doc_id, change_kind)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_retrohunt_matches_ws_status
        ON retrohunt_matches (workspace_id, status, created_at DESC)
    """,
    # The D-017 append-only verdict trail gains its first AUTOMATED writer: when
    # re-enrichment changes an observable's label, the change itself becomes a
    # typed, provenanced row (old → new, which verdict rows, what triggered it,
    # and the retro-hunt match if one was open). Verdict rows already record
    # what was believed; this records that belief CHANGED, which is the thing an
    # analyst needs to see and the thing a falsification watcher will read.
    """
    CREATE TABLE IF NOT EXISTS verdict_flips (
        id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id     uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        observable_id    uuid NOT NULL REFERENCES observables(id) ON DELETE CASCADE,
        from_label       text NOT NULL CHECK (from_label IN
            ('malicious', 'suspicious', 'benign', 'unknown')),
        to_label         text NOT NULL CHECK (to_label IN
            ('malicious', 'suspicious', 'benign', 'unknown')),
        from_verdict_id  uuid REFERENCES verdicts(id) ON DELETE SET NULL,
        to_verdict_id    uuid NOT NULL REFERENCES verdicts(id) ON DELETE CASCADE,
        trigger          text NOT NULL,
        match_id         uuid REFERENCES retrohunt_matches(id) ON DELETE SET NULL,
        -- clock_timestamp() (S15 Step 0 note below): a flip is written in the
        -- same transaction as the verdict it describes, so under now() it
        -- inherits that transaction's start time — and two flips of one
        -- observable could list in a different order than their own verdicts.
        created_at       timestamptz NOT NULL DEFAULT clock_timestamp()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_verdict_flips_ws_obs
        ON verdict_flips (workspace_id, observable_id, created_at DESC)
    """,
    # S15 Step 0 — the same correction for databases that already exist.
    #
    # `now()` is transaction_timestamp(): fixed at a transaction's FIRST
    # statement and unmoved for its lifetime. That is harmless on the tables
    # above, where a creation time is only ever displayed. On these three it is
    # not — they are ORDERED BY, and the newest row is read back as current
    # truth.
    #
    # Proven by execution before it was fixed
    # (docs/probes/2026-08-09-s15-step0-review.md): transaction B begins,
    # upserts an unrelated observable (fixing its now()), then blocks on the
    # shared observable's row lock while transaction A — which began LATER —
    # writes a verdict and commits. B then writes the newest belief carrying the
    # OLDER stamp. Read back, the trail reported A's superseded label as
    # current, the sweep published it as `verdict_label_at_match`, and the next
    # enrichment would compute `from_label` from a verdict that is no longer the
    # latest.
    #
    # clock_timestamp() is read at INSERT time, which is exactly the order the
    # `observables` row lock already serializes these writes into: B cannot
    # reach its verdict insert until A has committed, so B's stamp is strictly
    # greater. Existing rows keep their values — true write order is not
    # reconstructible after the fact, and inventing one would be the same lie
    # pointing the other way.
    "ALTER TABLE verdicts ALTER COLUMN created_at SET DEFAULT clock_timestamp()",
    "ALTER TABLE retrohunt_matches ALTER COLUMN created_at SET DEFAULT clock_timestamp()",
    "ALTER TABLE verdict_flips ALTER COLUMN created_at SET DEFAULT clock_timestamp()",
    # S15: falsification watchers (Phase 3 flagship). Every verdict registers,
    # AT WRITE TIME, the typed conditions that would prove it wrong — the only
    # moment that answer is honest rather than rationalised. `claim` is the
    # sentence the VERDICT asserts (what would become false), stored alongside
    # the typed kind so the analyst surface never has to reconstruct prose from
    # an enum, and so the exact wording a workspace was shown survives a later
    # change to the derivation rules.
    #
    # verdict_id is the identity of the claim: a watcher belongs to ONE verdict,
    # and when a newer verdict replaces it the old watcher is SUPERSEDED rather
    # than deleted — "we were watching for this and stopped" is how you find a
    # question that was dropped instead of answered.
    """
    CREATE TABLE IF NOT EXISTS watchers (
        id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id   uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        observable_id  uuid NOT NULL REFERENCES observables(id) ON DELETE CASCADE,
        verdict_id     uuid NOT NULL REFERENCES verdicts(id) ON DELETE CASCADE,
        kind           text NOT NULL CHECK (kind IN
            ('kev_listing', 'record_withdrawn', 'provider_escalation')),
        claim          text NOT NULL,
        params         jsonb NOT NULL DEFAULT '{}',
        status         text NOT NULL DEFAULT 'open'
            CHECK (status IN ('open', 'satisfied', 'superseded')),
        satisfied_by   text,
        created_at     timestamptz NOT NULL DEFAULT clock_timestamp(),
        satisfied_at   timestamptz,
        UNIQUE (verdict_id, kind)
    )
    """,
    # The ingest-side check joins doc ids → observables → OPEN watchers of one
    # kind, so the probe is (observable_id, kind) and the filter is status. A
    # partial index on status='open' keeps it proportional to the watchers still
    # watching rather than to every watcher ever registered — satisfied and
    # superseded rows accumulate forever and are never joined against.
    """
    CREATE INDEX IF NOT EXISTS idx_watchers_open_obs_kind
        ON watchers (observable_id, kind) WHERE status = 'open'
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_watchers_ws_status
        ON watchers (workspace_id, status, created_at DESC)
    """,
    # A satisfied watcher does not get its own notification shape: it UPGRADES
    # the S14 re-open event for the same doc from "new intel touches an
    # observable you saw" to "new intel contradicts the specific claim this
    # verdict made". Two rows for one fact would train the analyst to skim.
    #
    # S16 Step 0 moved that link from a WRITTEN column to a DERIVED one. S15
    # wrote `retrohunt_matches.watcher_id` from the watcher sink, which could
    # only find the match if the retro-hunt sink had already written it — true
    # by the order `FanoutSink` happened to be constructed in, and by nothing
    # else. Executed: reversing the two sinks, or the retro-hunt sink simply
    # failing that batch, dropped the link with no error anywhere, and the loss
    # was PERMANENT (the satisfy UPDATE is guarded on status='open', so no later
    # cycle ever retries it). Recording WHICH change satisfied the watcher makes
    # the link a fact about the watcher row, derivable from either side in any
    # order (docs/probes/2026-08-10-s16-step0-review.md).
    "ALTER TABLE watchers ADD COLUMN IF NOT EXISTS satisfied_change_kind text",
    # Mirrors idx_watchers_open_obs_kind for the other end of a watcher's life.
    # The re-open list derives its claim per row, so this is a LIMIT-50 lateral
    # of index descents rather than a scan of every watcher ever satisfied.
    """
    CREATE INDEX IF NOT EXISTS idx_watchers_satisfied_obs
        ON watchers (observable_id, satisfied_by) WHERE status = 'satisfied'
    """,
    # Retire the written column, preserving every link it already holds. Guarded
    # on the column's existence so the whole list stays idempotent — after the
    # drop this statement is a no-op rather than an error on the next boot.
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'retrohunt_matches' AND column_name = 'watcher_id'
        ) THEN
            UPDATE watchers w
               SET satisfied_change_kind = m.change_kind
              FROM retrohunt_matches m
             WHERE m.watcher_id = w.id AND w.satisfied_change_kind IS NULL;
            ALTER TABLE retrohunt_matches DROP COLUMN watcher_id;
        END IF;
    END $$
    """,
    # S17 Step 0: the digest's decay read. A verdict crossed staleness edge `e`
    # inside (since, now] iff its created_at falls in a window as wide as the
    # window itself — see _DECAYED_SQL. That makes the crossing set a created_at
    # RANGE per (edge, half-life) pair, and this is the index those ranges probe.
    # Measured on 99k observables / 109k verdicts (docs/probes/
    # 2026-08-11-s17-step0-review.md): without it the digest read the workspace's
    # entire history and spilled its sort to disk at 143 ms; with it, 4.6 ms.
    #
    # half_life_days precedes created_at because the crossing offset is a
    # multiple of it: the equality pins the family, the range walks the dates.
    """
    CREATE INDEX IF NOT EXISTS idx_verdicts_ws_hl_created
        ON verdicts (workspace_id, half_life_days, created_at)
    """,
    # S18: a proposal stops being a record of a tool call and becomes a decision
    # about a DECLARATION. `spec_fingerprint` is the identity of the declaration
    # the approver saw (auspex/actions/proposal.py) — re-checked at execute time,
    # because an hour can pass between the approval and the run and a deploy can
    # change an action's risk, scope or undo in between (TD-023). `card` is what
    # was actually shown, stored rather than re-rendered: re-deriving it later
    # would show today's declaration for yesterday's decision, which is the one
    # thing an audit trail must not do.
    """
    ALTER TABLE proposals
        ADD COLUMN IF NOT EXISTS spec_fingerprint text,
        ADD COLUMN IF NOT EXISTS card jsonb,
        ADD COLUMN IF NOT EXISTS undo_result jsonb,
        ADD COLUMN IF NOT EXISTS undone_at timestamptz
    """,
    # 'executed' and 'rejected' were terminal in S3. S18 adds the states a real
    # execution produces: the two in-flight claims ('executing', 'undoing' — the
    # same claim-first device as approval, so a second caller cannot start a
    # second run), one that ran and failed, and one that was put back.
    #
    # S21 adds 'abandoned' (TD-028a). A claim is a promise that a handler is
    # running; a process that dies between the claim and the handler leaves a row
    # that `execute` refuses as not_approved, `undo` refuses as not_executed and
    # `reject` refuses as already_decided — wedged forever, and INVISIBLE,
    # because the queue reads `status = 'pending_approval'`. A human watching
    # the approvals list saw the action disappear.
    #
    # S26 adds 'incomplete' (TD-028b): the handler raised and some of this
    # proposal's effects landed — or the action cannot look. And 'kept' (S26
    # review of D-041): a human looked at an incomplete run and kept what landed.
    # S28 adds 'withdrawn' (TD-042, D-048): approved, then retracted by a human
    # before any run claimed it — nothing ran, and `rejected` would deny that it
    # had been approved.
    #
    # THE ONLY BLOCK THAT MAY DEFINE THIS CONSTRAINT, AND IT HOLDS THE FULL
    # CURRENT LIST. Every boot re-runs every statement, and re-adding the CHECK
    # validates every existing row: a second, later block with a longer list
    # still runs AFTER this one, so a row in a newer status fails this one and
    # the whole migration rolls back — the app cannot start (S26 review, HIGH,
    # pinned by test_startup_survives_every_status_a_proposal_can_be_in). New
    # statuses are added HERE, in place, as S21 did to S18's list.
    """
    DO $$
    BEGIN
        ALTER TABLE proposals DROP CONSTRAINT IF EXISTS proposals_status_check;
        ALTER TABLE proposals ADD CONSTRAINT proposals_status_check
            CHECK (status IN ('pending_approval', 'approved', 'rejected',
                              'executing', 'executed', 'failed', 'incomplete',
                              'kept', 'undoing', 'undone', 'abandoned',
                              'withdrawn', 'expired'));
    END $$
    """,
    # S21 (TD-028a): when the claim was taken. Without it "this claim is stale"
    # is unanswerable — `decided_at` records the approval, not the run, and a
    # row approved on Monday and claimed on Friday looks four days stale the
    # moment it is claimed.
    #
    # Set by the claim, cleared by every transition out of a claim, so a
    # non-NULL claimed_at means "a claim is outstanding right now" and needs no
    # join with status to be read.
    """
    ALTER TABLE proposals ADD COLUMN IF NOT EXISTS claimed_at timestamptz
    """,
    # S26 (TD-034): WHICH operation `abandon` gave up on. `abandoned` alone does
    # not say whether a run or a put-back was lost, so a late undo answer could
    # land on a row whose RUN was abandoned. Written by the statement that moves
    # the row, from the status it moved it out of; matched by the late-write.
    """
    ALTER TABLE proposals ADD COLUMN IF NOT EXISTS abandoned_from text
        CHECK (abandoned_from IN ('executing', 'undoing'))
    """,
    # S26 review of D-041: a claim is identified by a TOKEN, not by its status
    # string. Once undo could start from `abandoned`, two undos could be in
    # flight on one row, and a late failure matched the fresh claim by status
    # alone. `claim_token` is set by every claim and cleared by every exit;
    # `abandoned_token` is the claim a human gave up on, which is the only claim
    # whose late answer may still land.
    """
    ALTER TABLE proposals
        ADD COLUMN IF NOT EXISTS claim_token uuid,
        ADD COLUMN IF NOT EXISTS abandoned_token uuid
    """,
    # S27 review of D-041: who resolved a run a human had to look at — kept what
    # an incomplete run left, or abandoned a dead claim — and when. Their own
    # columns because `decided_by`/`decided_at` are the APPROVAL, and `keep` and
    # `abandon` used to overwrite them: the row stopped saying who had approved
    # the action that partly ran. Rows resolved before S27 still carry the
    # resolver in `decided_by`; which human approved them is not recoverable.
    """
    ALTER TABLE proposals
        ADD COLUMN IF NOT EXISTS resolved_by uuid REFERENCES users(id) ON DELETE SET NULL,
        ADD COLUMN IF NOT EXISTS resolved_at timestamptz
    """,
    # The stale-claim scan: within a workspace, the claimed rows by age. Partial,
    # because claims are the rare state — the index stays the size of the
    # problem rather than the size of the table.
    """
    CREATE INDEX IF NOT EXISTS idx_proposals_ws_claimed
        ON proposals (workspace_id, claimed_at)
     WHERE claimed_at IS NOT NULL
    """,
    # The claim-first settlement reads exactly this: one row, by id, within a
    # workspace, still pending. D-008 tenancy is part of the key, not a filter
    # applied afterwards.
    """
    CREATE INDEX IF NOT EXISTS idx_proposals_ws_id_status
        ON proposals (workspace_id, id, status)
    """,
    # S26 review (TD-028d): the twin lookup runs per returned card, every second
    # per approvals-stream subscriber; unindexed it scanned the whole pending
    # queue each time (811 ms at 20k pending rows, measured). md5 of the
    # canonical jsonb text rather than the jsonb itself: a 2000-char note would
    # exceed btree's row size and make FILING a proposal fail. Partial, because
    # only pending rows are ever twins. One bound, probed at S27: jsonb `=` calls
    # numbers that differ only in scale equal (1 = 1.0) while their text, and so
    # their md5, differs — such twins are not named. Arguments are filed as the
    # model sent them, so this is reachable the day an action declares an
    # INTEGER or NUMBER parameter.
    """
    CREATE INDEX IF NOT EXISTS idx_proposals_pending_twins
        ON proposals (workspace_id, tool_name, md5(tool_input::text))
     WHERE status = 'pending_approval'
    """,
    # S18: the internal system an action can actually touch this session. A note
    # on an observable is ours, has a real undo, and needs no third-party
    # credential — the executor refuses anything whose scope we do not own, so
    # this is what makes "something actually happens" demonstrable.
    """
    CREATE TABLE IF NOT EXISTS observable_notes (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        observable_id uuid NOT NULL REFERENCES observables(id) ON DELETE CASCADE,
        note text NOT NULL,
        source text NOT NULL,
        proposal_id uuid REFERENCES proposals(id) ON DELETE SET NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_observable_notes_ws_obs
        ON observable_notes (workspace_id, observable_id, created_at DESC)
    """,
    # S19 (Hardening): what a workspace may spend, and what it has spent.
    #
    # The plan lives on the workspace and the LIMITS live in code
    # (auspex/limits.py), the same split as EXECUTABLE_SYSTEMS: which tier a
    # customer is on is data, what a tier is allowed to do is a decision with a
    # blast radius. A limits table would let a bad UPDATE hand someone unbounded
    # inference.
    """
    ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS plan text NOT NULL DEFAULT 'free'
    """,
    # One row per (workspace, meter, window). `used` is incremented by a
    # conditional UPSERT that refuses to go over the ceiling in the same
    # statement that reads it — the S18 claim-first device, applied to spend:
    # "check then increment" is a window two concurrent turns fit through.
    """
    CREATE TABLE IF NOT EXISTS usage_counters (
        workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        meter text NOT NULL,
        window_start timestamptz NOT NULL,
        used integer NOT NULL DEFAULT 0,
        updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY (workspace_id, meter, window_start)
    )
    """,
    # Sweeping closed windows is a range scan per workspace, and the PK's
    # leading column already serves the hot read.
    """
    CREATE INDEX IF NOT EXISTS idx_usage_counters_window
        ON usage_counters (window_start)
    """,
    # F1 (D-054): what each deep turn spent on the customer's engine. One row per
    # deep turn, written at the turn's own ending — including the endings that
    # store no answer (the rail's cut, the ceiling, an endpoint error), because
    # the calls were made and paid for all the same. Tokens are the endpoint's
    # own usage, NULL where it reported none (never a guessed zero).
    """
    CREATE TABLE IF NOT EXISTS turn_spend (
        id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id      uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        session_id        uuid NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
        message_id        uuid REFERENCES messages(id) ON DELETE SET NULL,
        engine_calls      integer NOT NULL CHECK (engine_calls >= 0),
        prompt_tokens     integer,
        completion_tokens integer,
        ending            text NOT NULL,
        created_at        timestamptz NOT NULL DEFAULT clock_timestamp()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_turn_spend_session
        ON turn_spend (session_id, created_at)
    """,
]

# The list as it stood before S30 (with idx_users_workspace removed): the
# migration test builds a pre-S30 database from it.
PRE_S30_STATEMENTS: tuple[str, ...] = tuple(SCHEMA_V0)

# S30 (D-061; docs/superpowers/specs/2026-10-15-s30-tenancy-design.md §1).
# Organizations own workspaces; a user is a PERSON with a home organization and
# memberships, no longer a row per workspace. `organizations` and `users` are
# the two tables D-061 exempts from D-008's workspace_id (tests/test_schema.py).
S30_TENANCY: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS organizations (
        id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        name        text NOT NULL UNIQUE,
        kind        text NOT NULL CHECK (kind IN ('direct', 'provider', 'client')),
        parent_id   uuid REFERENCES organizations(id) ON DELETE RESTRICT,
        restricted  boolean NOT NULL DEFAULT false,
        created_at  timestamptz NOT NULL DEFAULT now(),
        CHECK ((kind = 'client') = (parent_id IS NOT NULL)),
        CHECK (NOT restricted OR kind = 'client')
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_organizations_parent ON organizations (parent_id)",
    """
    ALTER TABLE workspaces
        ADD COLUMN IF NOT EXISTS org_id uuid REFERENCES organizations(id) ON DELETE RESTRICT,
        ADD COLUMN IF NOT EXISTS region text NOT NULL DEFAULT 'global'
    """,
    "CREATE INDEX IF NOT EXISTS idx_workspaces_org ON workspaces (org_id)",
    # THE ONLY BLOCK THAT DEFINES THIS CONSTRAINT; it holds the full list and
    # must equal auspex/tenancy/region.py's REGIONS (pinned by a test). A new
    # region is added HERE, in place — the proposals-status rule (S26).
    """
    DO $$
    BEGIN
        ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS workspaces_region_check;
        ALTER TABLE workspaces ADD CONSTRAINT workspaces_region_check
            CHECK (region IN ('global', 'ksa'));
    END $$
    """,
    """
    ALTER TABLE users
        ADD COLUMN IF NOT EXISTS home_org_id uuid REFERENCES organizations(id) ON DELETE RESTRICT
    """,
    """
    CREATE TABLE IF NOT EXISTS memberships (
        id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id   uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        role           text NOT NULL CHECK (role IN ('admin', 'analyst', 'viewer')),
        provider_wide  boolean NOT NULL DEFAULT false,
        created_at     timestamptz NOT NULL DEFAULT now(),
        updated_at     timestamptz NOT NULL DEFAULT now(),
        UNIQUE (workspace_id, user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_memberships_user ON memberships (user_id)",
    # Append-only (no code updates or deletes a row; pinned by a test). The
    # actor columns carry no foreign key on purpose: purging a user must not
    # erase who acted. clock_timestamp(): these rows are read back in order.
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id     uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        actor_kind       text NOT NULL CHECK (actor_kind IN ('user', 'cli', 'system')),
        actor_user_id    uuid,
        actor_org_id     uuid,
        action           text NOT NULL,
        subject_user_id  uuid,
        details          jsonb NOT NULL DEFAULT '{}',
        created_at       timestamptz NOT NULL DEFAULT clock_timestamp(),
        CHECK ((actor_kind = 'user') = (actor_user_id IS NOT NULL))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_events_ws_created
        ON audit_events (workspace_id, created_at DESC)
    """,
    # THE ONLY BLOCK THAT DEFINES THIS CONSTRAINT; it must equal
    # auspex/tenancy/audit.py's ACTIONS (pinned by a test). Edited in place.
    """
    DO $$
    BEGIN
        ALTER TABLE audit_events DROP CONSTRAINT IF EXISTS audit_events_action_check;
        ALTER TABLE audit_events ADD CONSTRAINT audit_events_action_check
            CHECK (action IN ('workspace.enter', 'membership.add', 'membership.role',
                              'membership.remove', 'membership.provider_wide',
                              'org.create', 'org.restricted', 'workspace.create',
                              'person.rehome', 'connector.registered',
                              'integration.created', 'integration.updated',
                              'integration.disabled', 'edge_agent.created',
                              'edge_agent.enrolled', 'edge_agent.revoked'));
    END $$
    """,
    # The one-time move, guarded on the old column like S16's watcher_id block:
    # after it runs, every later boot skips it. One transaction with the whole
    # list (run_migrations), so a refusal leaves the old shape untouched.
    """
    DO $$
    DECLARE
        dupes integer;
        stranded integer;
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'users'
               AND column_name = 'workspace_id'
        ) THEN
            SELECT count(*) INTO dupes FROM (
                SELECT lower(email) FROM users GROUP BY 1 HAVING count(*) > 1
            ) d;
            IF dupes > 0 THEN
                RAISE EXCEPTION 'S30 migration refused: % email address(es) on 2+ user rows',
                    dupes USING HINT = 'One person, one home organization (D-061): merge the rows.';
            END IF;
            SELECT count(*) INTO stranded
              FROM users u JOIN workspaces w ON w.id = u.workspace_id
             WHERE w.name = '__deployment__';
            IF stranded > 0 THEN
                RAISE EXCEPTION 'S30 migration refused: % user(s) in __deployment__ (reserved)',
                    stranded USING HINT = 'D-035: nobody may belong to the deployment workspace.';
            END IF;
            INSERT INTO organizations (name, kind)
            SELECT w.name, 'direct' FROM workspaces w
             WHERE w.org_id IS NULL AND w.name <> '__deployment__'
            ON CONFLICT (name) DO NOTHING;
            UPDATE workspaces w SET org_id = o.id
              FROM organizations o
             WHERE w.org_id IS NULL AND w.name <> '__deployment__' AND o.name = w.name;
            UPDATE users u SET home_org_id = w.org_id
              FROM workspaces w
             WHERE w.id = u.workspace_id AND u.home_org_id IS NULL;
            INSERT INTO memberships (workspace_id, user_id, role)
            SELECT u.workspace_id, u.id,
                   CASE WHEN u.role IN ('admin', 'analyst', 'viewer') THEN u.role
                        ELSE 'viewer' END
              FROM users u
            ON CONFLICT (workspace_id, user_id) DO NOTHING;
            ALTER TABLE users DROP CONSTRAINT IF EXISTS users_workspace_id_email_key;
            DROP INDEX IF EXISTS idx_users_workspace;
            ALTER TABLE users DROP COLUMN workspace_id;
            ALTER TABLE users DROP COLUMN role;
        END IF;
    END $$
    """,
    "ALTER TABLE users ALTER COLUMN home_org_id SET NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_lower ON users (lower(email))",
    # Only the deployment's system workspace (D-035) belongs to no organization:
    # nothing can ever reach it through a membership.
    """
    DO $$
    BEGIN
        ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS workspaces_org_required;
        ALTER TABLE workspaces ADD CONSTRAINT workspaces_org_required
            CHECK (org_id IS NOT NULL OR name = '__deployment__');
    END $$
    """,
]

# S31 (D-065; docs/superpowers/specs/2026-10-16-s31-jobs-design.md §1): the jobs
# queue. Every job belongs to one workspace (D-008); a provider's shared
# integration's jobs belong to the provider's workspace. `max_attempts` and
# `lease_seconds` are copied from the kind at enqueue, so a claim needs no code.
S31_JOBS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id     uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        kind             text NOT NULL,
        integration_id   uuid,
        payload          jsonb NOT NULL DEFAULT '{}',
        idempotency_key  text NOT NULL,
        status           text NOT NULL DEFAULT 'queued',
        attempts         integer NOT NULL DEFAULT 0,
        max_attempts     integer NOT NULL CHECK (max_attempts >= 1),
        lease_seconds    integer NOT NULL CHECK (lease_seconds >= 1),
        run_after        timestamptz NOT NULL DEFAULT now(),
        lease_expires_at timestamptz,
        claim_token      uuid,
        claimed_by       text,
        result           jsonb,
        last_error       text,
        created_at       timestamptz NOT NULL DEFAULT now(),
        finished_at      timestamptz,
        UNIQUE (workspace_id, idempotency_key)
    )
    """,
    # THE ONLY BLOCK THAT MAY DEFINE THIS CONSTRAINT (the proposals rule, S26):
    # a new job status is added HERE, in place.
    """
    DO $$
    BEGIN
        ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_status_check;
        ALTER TABLE jobs ADD CONSTRAINT jobs_status_check
            CHECK (status IN ('queued', 'claimed', 'done', 'failed', 'dead'));
    END $$
    """,
    "CREATE INDEX IF NOT EXISTS idx_jobs_ready ON jobs (status, run_after)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_ws_status ON jobs (workspace_id, status)",
    # Whose turn it was (§1): the claim serves the least-recently-served
    # workspace first, so one busy client cannot starve the rest.
    """
    CREATE TABLE IF NOT EXISTS job_turns (
        workspace_id   uuid PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
        last_served_at timestamptz NOT NULL
    )
    """,
    # S31 (TD-025): the built-in note action keys its write on the operation's
    # idempotency key, so a repeat of one execute leaves one note. Older rows
    # stay NULL and are not de-duplicated.
    "ALTER TABLE observable_notes ADD COLUMN IF NOT EXISTS idempotency_key text",
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_observable_notes_idempotency
        ON observable_notes (workspace_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """,
]

# S32 (D-064; docs/superpowers/specs/2026-10-22-s32-connectors-design.md decision 3):
# the connector catalogue. A package is identified by its content hash (a changed
# package is a new identity), so the hash is unique per workspace and an id+version
# names one hash. First-party rows live in `__deployment__` (D-035/D-068).
# `registered_by` carries no foreign key, as audit_events' actors: purging a person
# must not erase or block who registered a package.
S32_CONNECTORS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS connector_packages (
        id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id        uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        connector_id        text NOT NULL,
        version             text NOT NULL,
        content_hash        text NOT NULL,
        manifest            jsonb NOT NULL,
        package             bytea NOT NULL,
        first_party         boolean NOT NULL DEFAULT false,
        offered_to_clients  boolean NOT NULL DEFAULT false,
        registered_by       uuid,
        created_at          timestamptz NOT NULL DEFAULT now(),
        UNIQUE (workspace_id, content_hash),
        UNIQUE (workspace_id, connector_id, version)
    )
    """,
    # The listing's two cross-workspace probes: first-party and offered rows.
    """
    CREATE INDEX IF NOT EXISTS idx_connector_packages_first_party
        ON connector_packages (connector_id) WHERE first_party
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_connector_packages_offered
        ON connector_packages (workspace_id) WHERE offered_to_clients
    """,
]

# S33: Edge Agents and their one-time enrollments (D-062), then integrations
# (D-060). An agent belongs to one workspace; its credential is stored hashed only
# (the api_keys pattern), and is NULL until it enrolls.
S33_EDGE: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS edge_agents (
        id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id       uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        name               text NOT NULL,
        credential_hash    text UNIQUE,
        key_prefix         text,
        created_by         uuid,
        created_at         timestamptz NOT NULL DEFAULT now(),
        enrolled_at        timestamptz,
        revoked_at         timestamptz,
        last_heartbeat_at  timestamptz,
        UNIQUE (workspace_id, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS edge_enrollments (
        id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        agent_id      uuid NOT NULL REFERENCES edge_agents(id) ON DELETE CASCADE,
        token_hash    text NOT NULL UNIQUE,
        created_by    uuid,
        created_at    timestamptz NOT NULL DEFAULT now(),
        expires_at    timestamptz NOT NULL,
        used_at       timestamptz
    )
    """,
    # An integration is disabled, never deleted, and its prefix (the wire name's) is
    # unique in its workspace for good, disabled rows included: an approval can never
    # later point at another integration under the same name (Hunaiza's call, S33).
    """
    CREATE TABLE IF NOT EXISTS integrations (
        id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        name          text NOT NULL,
        prefix        text NOT NULL,
        connector_id  text NOT NULL,
        content_hash  text NOT NULL,
        config        jsonb NOT NULL,
        agent_id      uuid NOT NULL REFERENCES edge_agents(id),
        created_by    uuid,
        created_at    timestamptz NOT NULL DEFAULT now(),
        disabled_at   timestamptz,
        UNIQUE (workspace_id, prefix)
    )
    """,
]

SCHEMA_V0 = [*SCHEMA_V0, *S30_TENANCY, *S31_JOBS, *S32_CONNECTORS, *S33_EDGE]


async def run_migrations(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        # Serialize concurrent app replicas racing the same DDL.
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", MIGRATION_LOCK)
            for statement in SCHEMA_V0:
                await conn.execute(statement)
    logger.info("Schema v0 migration applied (idempotent, %d statements)", len(SCHEMA_V0))
