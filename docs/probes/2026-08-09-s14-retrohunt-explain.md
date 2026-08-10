# S14 — retro-hunt sweep query plans (EXPLAIN against live Postgres 16)

_Date: 2026-08-09 · Postgres 16-alpine, compose dev DB on :55432 ·
ROADMAP S14 constraint: "The sweep MUST be an indexed join on the observables
table (workspace-scoped), never a full scan per DocChange — probe the query plan
(EXPLAIN) and save it to docs/probes/ before calling it done."_

_Seeding: N synthetic `type='cve'` observables in a throwaway workspace, one
verdict each plus a second verdict for a tenth of them (so the LATERAL has a real
trail to descend), then `VACUUM (ANALYZE)`. Workspace dropped at the end._

## What the probe caught

The first version of the sweep was the obvious spelling:

```sql
WHERE o.type = $2 AND o.value = ANY($1::text[])   -- batch of 500 ids
```

At 20,000 observables it planned as exactly what the ROADMAP forbids:

```
Nested Loop Left Join  (cost=1.66..4858.68 rows=500) (actual time=0.022..1.205 rows=250)
  ->  Seq Scan on observables o  (cost=1.25..637.42 rows=500) (actual rows=250)
        Filter: ((type = 'cve') AND (value = ANY ('{CVE-2020-000001,…}')))
        Rows Removed by Filter: 19760
  ->  Limit
        ->  Index Scan using idx_verdicts_ws_obs on verdicts  (loops=250)
              Index Cond: ((workspace_id = o.workspace_id) AND (observable_id = o.id))
Execution Time: 1.222 ms
```

`Rows Removed by Filter: 19760` — every observable in the platform read to
answer one KEV release, and the cost grows with the table forever.

## The wrong conclusion, and the correction

The first reading blamed the *spelling* and rewrote it as an explicit join with
the changed ids as the driving relation (`FROM unnest($1) d JOIN observables o ON
o.type = $2 AND o.value = d.doc_id`). At a 500-id batch that plan is **also** a
whole-table read — it just reaches it via a hash join:

```
->  Hash Join  (cost=786.13..798.00 rows=500)
      Hash Cond: (d.doc_id = o.value)
      ->  Function Scan on unnest d  (rows=500)
      ->  Hash  (rows=20000)
            ->  Seq Scan on observables o  (rows=20000)
                  Filter: (type = 'cve')
Execution Time: 3.712 ms      ← slower than the query it "fixed"
```

Measured head-to-head on 25,000 VACUUMed rows, the two spellings behave like
this — the array version holds the index to a *larger* batch than the join:

| batch | `JOIN unnest(ids)` | `value = ANY(ids)` |
|---|---|---|
| 10 | INDEX | INDEX |
| 50 | INDEX | INDEX |
| 100 | **SEQ SCAN** | INDEX |
| 500 | SEQ SCAN | SEQ SCAN |

**So the rewrite was not the fix. The batch bound is.** The comment in
`store.py` says so, because a code comment that credits the wrong cause is worse
than no comment — the next person "simplifies" the query and cannot understand
why the plan changed.

The join formulation is kept on separate grounds: it is the shape the work has
(the changed docs drive the lookup), and it returns `d.doc_id`, the doc that
caused each match, instead of inferring it from the matched value.

## Choosing SWEEP_CHUNK from the crossover

The planner abandons per-id index descents for a whole-table hash join once the
batch looks expensive relative to one heap scan — and that threshold **rises**
with the table:

```
--- observables(cve) = 20,000 ---
  batch    25: INDEX        0.194 ms  (   7.8 µs/id)
  batch    50: INDEX        0.300 ms  (   6.0 µs/id)
  batch   100: SEQ+HASH     1.646 ms  (  16.5 µs/id)
  batch   200: SEQ+HASH     3.647 ms  (  18.2 µs/id)
  batch   500: SEQ+HASH     3.731 ms  (   7.5 µs/id)
  batch  1000: SEQ+HASH     4.156 ms  (   4.2 µs/id)

--- observables(cve) = 200,000 ---
  batch    25: INDEX        0.143 ms  (   5.7 µs/id)
  batch    50: INDEX        0.247 ms  (   4.9 µs/id)
  batch   100: INDEX        0.399 ms  (   4.0 µs/id)
  batch   200: INDEX        0.715 ms  (   3.6 µs/id)
  batch   500: INDEX        1.583 ms  (   3.2 µs/id)
  batch  1000: INDEX        3.421 ms  (   3.4 µs/id)
```

A bigger table makes the index relatively cheaper, never dearer, so **a chunk
that stays on the index at the smallest table size stays on it forever**. Below
the crossover the planner picks a scan because a scan genuinely is cheaper
there — a few hundred pages — which is the correct decision, not a defect.

`SWEEP_CHUNK = 50`. The KEV first-run refresh's ~1,600 ids (S8 review) become 32
queries of ~0.3 ms instead of one query that reads every observable on the
platform.

## The shipped plan

25,000 observables, batch = SWEEP_CHUNK (50), VACUUM (ANALYZE)'d:

```
Nested Loop Left Join  (cost=2.45..513.13 rows=50 width=132)
  ->  Nested Loop  (cost=0.29..404.38 rows=50 width=98)
        ->  Function Scan on unnest d  (cost=0.00..0.50 rows=50 width=32)
        ->  Index Scan using idx_observables_type_value on observables o
                                          (cost=0.29..8.07 rows=1 width=66)
              Index Cond: ((type = 'cve') AND (value = d.doc_id))
  ->  Limit  (cost=2.16..2.16 rows=1 width=34)
        ->  Sort → Seq Scan on verdicts        ← see note
              Filter: ((workspace_id = o.workspace_id) AND (observable_id = o.id))
```

No `Seq Scan on observables`, no `Rows Removed by Filter`: one index descent per
changed doc. The verdicts LATERAL scans here only because `verdicts` held ONE row
in this run; at 22,010 verdict rows the same LATERAL takes
`Index Scan using idx_verdicts_ws_obs` with `loops=250` (see the first plan
above). Both are correct choices for their table size.

## Why the index had to be added

`observables` already had `UNIQUE (workspace_id, type, value)`, and it cannot
serve this query: its leading column is `workspace_id`, which the sweep does not
know — ingest feeds are platform-global, so one sweep must find every tenant's
matches at once. Hence `idx_observables_type_value ON observables (type, value)`.
Tenancy is not weakened: each hit carries its own `workspace_id` into the event
row it writes, and every read path filters on it (D-008).

## A trap for future plan probes: bloat, not the query, can decide the plan

The regression test asserting this plan failed at first for a reason unrelated to
the code. Seeding and dropping 25k rows repeatedly across a test session left:

```
before VACUUM: n_live_tup=10  n_dead_tup=25000  pages=358
after  VACUUM: n_live_tup=10  n_dead_tup=0      pages=1
```

The planner costs a scan in **pages**, so 358 bloated pages behind 10 live rows
made a scan look expensive and shifted the plan. The fixture now runs
`VACUUM (ANALYZE) observables` before EXPLAIN — and again after cleanup, so the
shared dev DB is left as we found it. Any future plan assertion on this DB needs
the same treatment.

## Regressions pinned

`tests/test_retrohunt.py`:
- `test_sweep_plan_is_an_indexed_join_not_a_table_scan` — at 25k rows and the
  shipped chunk: `Function Scan on unnest` drives it,
  `idx_observables_type_value` serves it, no `Seq Scan on observables`.
- `test_an_unchunked_batch_would_scan_which_is_why_the_chunk_exists` — 10× the
  chunk on the same table reaches the forbidden shape, so the bound's value is
  executable rather than asserted in prose.
- `test_a_full_sweep_chunk_is_one_query` — SWEEP_CHUNK ids cost exactly one
  round trip, so "one query per batch, never one per DocChange" is pinned too.
