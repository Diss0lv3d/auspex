# S34 design — connector actions through approvals, per-client policy, the co-analyst

_2026-11-02. Owner: Hunaiza (Burhan handed S34 fully, 2026-10-30; D-059). The
contract is the S34 entry in `NEXT-SESSION-BE.md` (its exit criteria are the done
line), on D-014, D-024, D-048, D-062, D-064, D-066 and D-074. This document settles
what those leave open. Each call is marked **Hunaiza's** or **Claude's** (where the
docs were silent, by her standing instruction). Baseline:
docs/probes/2026-11-02-s34-baseline.md._

## Goal

An integration's action takes the path built-in actions already take: propose (the
card from a **dry-run job on the agent**), approve (under the workspace's **approval
policy**), claim, an **execute job on the agent**, the validated result, then settle,
or undo, observe, abandon, keep, withdraw and D-048's stale doors. Nothing of a
connector runs in the app (D-062); every write goes through an approval (D-014).

## Decisions

1. **The default approval rule** (Hunaiza's). A workspace with no policy of its own:
   `write` actions may be approved by its analysts and admins (as today);
   `destructive` actions by its **admins only**. A workspace's admin may tighten it,
   per risk level: which roles, and whether provider staff (an MSSP's people working
   in a client's workspace) may approve at all.
2. **Grants** (Hunaiza's). An integration may run only the actions an admin granted
   it, and a new integration is granted **none**. Grants are a set of manifest action
   names on the integration, edited by an admin, audited; a grant of an action the
   pinned manifest lacks is refused.
3. **The dry run waits up to 30 s** (Hunaiza's). Proposing a connector action enqueues
   its dry-run job and waits up to 30 s for the agent's answer; no answer → refused in
   words ("the Edge Agent did not answer the preview"), nothing filed.
4. **The co-analyst part stays in S34, done last** (Hunaiza's). If the engine key is
   still refused then (STATE.md Blockers #0), S34 stops at that step and says so.
5. **Actions resolve by workspace** (Claude's). One resolver replaces the app-wide
   registry where a proposal's action is looked up (settlement's execute,
   stale-approval and undo paths, the proposals route, the agent loop):
   `resolve(name, workspace_id)` returns a built-in spec, or for `<prefix>__<action>`
   the compiled spec of that workspace's **enabled** integration with that prefix and
   that action **granted**, from the manifest of its pinned package. Prefixes are
   never reused (S33), so workspace + prefix binds an approval to its integration.
6. **Dispatch** (Claude's). A compiled role enqueues `connector.action.<step>` for the
   integration (S31's queue, `integration_id` set), and waits for the job's answer:
   dry run 30 s, execute and undo 60 s, observe 30 s. The agent claims action kinds as
   it claims tests (the edge API's claim scope grows by kind), runs them through
   `auspex_sdk.run`, and the core checks the answer with `auspex_sdk.validate`
   (`check_envelope`, `check_observe`), by job kind (the merge review's note: pick the
   check by kind before `EDGE_KINDS` grows). A wait that runs out raises: execute's
   failure path then asks observe (TD-028b), as for any action.
7. **`check_executable` for a connector action** (Claude's). `EXECUTABLE_SYSTEMS`
   admits a connector system only through the resolver: a spec with an origin is
   executable when its integration is enabled, the action granted, its agent
   online or stale (not offline, never, or revoked), and the package hash the same as
   the approval's (the fingerprint already covers it, D-064). Each refusal has its own
   reason: `agent_offline`, `integration_disabled`, `not_granted`, `spec_changed`.
8. **The approval policy is data** (Claude's shape). `approval_policies`
   (workspace_id, risk, roles, provider_staff), one row per risk level, absent rows
   meaning the default (decision 1). Checked in D-024's settle path for
   `approved`, and recorded: the approver and their organization are already in the
   audit; the policy row in force goes into the proposal's decision record.
9. **One execution even when a result is lost** (Claude's). The idempotency key
   (S31's `operation_key`) reaches the handler as `ctx.idempotency_key`; the job is
   enqueued under it, so a re-run re-claims the same job, never a second one. A test
   drops the agent's first result post, lets the lease expire, has the job reclaimed,
   and counts one execution at the mock SIEM.
10. **Scope inside a shared integration** (Claude's). An action's `targets` param is
    checked against the item's routing key when the integration is shared; S35 builds
    shared fetches, so S34 checks it where a routing key exists and records the rule.
11. **The co-analyst** (Claude's, done last). The agent loop is offered the
    workspace's granted connector actions, their tool text composed by code from the
    manifest's typed fields and capped; customer text joins the rail's index and
    TD-044's calibration is re-run with it (needs the engine).

## Carried and found

- TD-071 (roles distinct as imported) before any action runs.
- TD-077: S34's first change to how a command runs makes one shared invoke-and-validate
  helper for the runner and the harness.
- The merge review's notes: `post_result` picks its check by job kind; fix
  `check_fingerprint`'s docstring (D-074).
- B-041 (a print at import breaks the runner's answer) sits in the code S34 changes
  first; whether S34 fixes it is a scope call, Burhan's (asked, not assumed).

## Safety, stated

Every write is approved (D-014); a connector action is refused before its claim when
its integration, grant, agent or package moved; tenant isolation holds in the
resolver (a prefix resolves only in its own workspace); a fresh-agent adversarial
review covers actions, the rail and tenancy before the close.
