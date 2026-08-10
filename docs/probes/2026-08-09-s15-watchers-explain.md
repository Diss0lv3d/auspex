# S15 — falsification watcher check: query plans, measured

_Date: 2026-08-09 · compose Postgres 16 · `auspex/watchers/store.py::_CHECK_SQL`
at the shipped `SWEEP_CHUNK = 50` · `VACUUM (ANALYZE)` before every measurement
(STATE.md host note: seeding and dropping rows leaves bloat, and the planner
costs a scan in PAGES, so bloat rather than the query decides the plan)._

The ROADMAP S15 constraint is S14's: **indexed join, never a scan per change.**
The watcher check has a second scaling worry S14's sweep does not — `watchers`
accumulates `satisfied` and `superseded` rows forever, and those rows are never
joined against. The partial index on `status = 'open'` exists for exactly that,
so this probe measures the closed-row case explicitly instead of assuming it.

## Plan by table size, all watchers open

```
watchers = 1600 (all open)
   batch   50: SEQ observables  | SEQ watchers  | 0.281 ms
   batch  100: SEQ observables  | SEQ watchers  | 0.302 ms
   batch  500: SEQ observables  | SEQ watchers  | 0.528 ms
   batch 1000: SEQ observables  | SEQ watchers  | 0.811 ms

watchers = 25000 (all open)
   batch   50: idx observables  | idx watchers  | 0.174 ms
   batch  100: SEQ observables  | idx watchers  | 1.891 ms
   batch  500: SEQ observables  | idx watchers  | 4.841 ms
   batch 1000: SEQ observables  | idx watchers  | 5.094 ms
```

Same shape as the S14 sweep, and the same honest caveat: at 1,600 rows the
planner scans and is right to — the table is a couple of dozen pages and the
scan costs 0.28 ms. The claim worth making is the one measured at 25k, where a
scan would cost something: **at the shipped chunk of 50 both legs are index
descents, and at 100 the observables leg is already lost.** The bound is what
holds the plan, exactly as S14 found.

## The case the PARTIAL index is for

Closed watchers accumulate for the life of the workspace. Tripling the table
with rows the join must never touch:

```
adding 50,000 CLOSED watchers (satisfied/superseded accumulate forever)
watchers = 75000 (25000 open, 50000 closed)
   batch   50: idx observables  | idx watchers  | 0.190 ms
```

0.190 ms against 0.174 ms at 25k — the check is proportional to the watchers
still WATCHING, not to every watcher ever registered. That is the property the
partial index was chosen for, and it is now measured rather than asserted.

## The plan itself, at the shipped chunk

```
Nested Loop  (cost=0.71..439.47 rows=17 width=98) (actual time=0.015..0.127 rows=50 loops=1)
  ->  Nested Loop  (cost=0.42..418.88 rows=50 width=64) (actual time=0.010..0.079 rows=50 loops=1)
        ->  Function Scan on unnest d  (actual time=0.003..0.004 rows=50 loops=1)
        ->  Index Scan using idx_observables_type_value on observables o
              (actual time=0.001..0.001 rows=1 loops=50)
              Index Cond: ((type = 'cve'::text) AND (value = d.doc_id))
  ->  Index Scan using idx_watchers_open_obs_kind on watchers w
        (actual time=0.001..0.001 rows=1 loops=50)
        Index Cond: ((observable_id = o.id) AND (kind = 'kev_listing'::text))
        Filter: (o.workspace_id = workspace_id)
Planning Time: 0.168 ms
Execution Time: 0.139 ms
```

The changed doc ids drive the loop; each descends `idx_observables_type_value`;
each match descends the partial watcher index. No relation is read whole.

Note the `Filter: (o.workspace_id = workspace_id)` on the inner leg — the
workspace equality is enforced as a filter after the index probe rather than
inside the index condition, which is correct and deliberate: like the S14 sweep,
this join runs ACROSS workspaces because feeds are platform-global, and tenancy
is preserved by each row carrying its own `workspace_id` into what it writes
(pinned by `test_the_global_check_satisfies_each_tenants_own_watcher`).

## Cost inside an ingest cycle

```
1,600-id KEV first run = 32 chunk queries: 34 ms
```

The S14 worst case — a KEV first-run refresh emitting ~1,600 ids — costs 34 ms
for the watcher check, on top of the 175 ms the S15 Step-0 review measured for
the retro-hunt sweep and its match writes. Both run inside `run_cycle`, against
NVD single fetches paced at seconds apiece. The second consumer is affordable;
the S15 sink is a `FanoutSink` rather than an extension of the retro-hunt sink
for isolation reasons, not cost ones.

## Residue

Probe workspace deleted (cascades cover observables, verdicts and watchers);
`watchers` and `observables` VACUUM ANALYZEd afterwards.
