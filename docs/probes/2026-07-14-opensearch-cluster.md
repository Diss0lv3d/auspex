# Probe: OpenSearch cluster (dev/shared) — 2026-07-14

Probed live with creds from `.env` (`OPENSEARCH_LOGS_HOST/USER/PASS`).

## Cluster
- DigitalOcean managed OpenSearch, **v2.19.4** (Lucene 9.12.3)
- Host: `sara-open-opensearch-logs-do-user-679096-0.j.db.ondigitalocean.com`
- **Port 25060** (443 does not respond), HTTPS + basic auth
- Node: `sara-open-opensearch-logs-1` (single node, pri 1 / rep 0 on all indices)

## What lives here (DO NOT TOUCH — D-004)
- `sara-access-logs-YYYY-MM-DD` (daily; ~5–360K docs/day). Mapping:
  `@timestamp date, api_key_hint kw, component kw, host kw, method kw,
  ms int, path kw, source_ip kw, status int, user_email kw, user_id kw`
- `sara-system-logs-YYYY-MM` (monthly), `sara-traces-YYYY-MM-DD` (daily)
- `sara-open-logs` (5.19M docs, 1GB), `system-logs`, `himaya-logs`,
  `omniintel-access-logs-*`, `staging-sara-*`, dashboards/sample/otel indices
- `.plugins-ml-config` exists → ML plugin present; **server-side model
  deployment on DO managed is UNVERIFIED** (probe in S6)

## What is NOT here
- No `sara-knowledge` / KB index — SARA's KB lives on a separate cluster
  (searchengine.sirp.io). We build our own `auspex-knowledge` here.

## Conventions to adopt
- Time-partitioned indices: daily for high-volume, monthly for medium
- keyword-heavy mappings for telemetry; our KB index will need
  `content` (text) + kNN vector field + `workspace_id`/`scope` keywords

## Our namespace
- `auspex-knowledge` (KB chunks), `auspex-observables`, `auspex-telemetry-*`
  — created in S6/S5; nothing created yet as of this probe.
