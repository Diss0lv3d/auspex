# 2026-10-22 — S32 live: a reference connector built, registered, offered and listed

The connector catalogue, checked against the rebuilt app container after the full
gate (`./ci.sh` green: 2055 tests, 139 modules; `/api/health/ready` answered
`ready` with Postgres and OpenSearch 2.19.4). Run on 2026-10-27, finishing S32.
Script: `docs/probes/s32-live/probe_connectors_live.py` (`run` / `cleanup`).
Synthetic data only, under the `t-s32-live` prefix, all deleted afterwards.

## Setup

One MSSP from `tests/_tenancy.py` `build_mssp`: a provider, two clients (client2
restricted), one direct customer, and their users. The reference connector
(`examples/connectors/mock_siem/python`) was built with `auspex_sdk.build.build`
into its git-ignored `dist/`:

```
built example.mock_siem-1.0.0.zip  hash sha256:c3f3d719b…
```

## Through the running app

```
POST as the provider's admin, offered → 201
POST as a client's analyst → 403 (expected 403)
  provider               lists it as: own
  client1                lists it as: provider
  client2 (restricted)   lists it as: provider
  direct                 lists it as: —
```

The provider's offer reaches both of its clients, including the restricted one
(D-071: a listing is code, not access to a client's data). It does not reach the
direct customer.

## First-party, by the CLI inside the container

```
CLI first-party → exit 0: registered first-party example.mock_siem 1.0.0 (sha256:c3f3d719ba1c6633c414bca6ac0e82ce46b7b661015c4dc0630b95599c5ec096)
  client1                now lists it as: first_party
  direct                 now lists it as: first_party
```

The same id is now listed once per workspace, from the first-party source,
which wins over a provider's offer and a workspace's own (S32 Task 10 ruling).
The direct customer, which could not see the provider's offer, now sees the
first-party package.

## Cleanup

```
first-party rows: DELETE 1; organizations under t-s32-live dropped
```

Afterwards `connector_packages` held 0 rows and no `t-s32-live` organization
remained.

## What this does not show

Nothing ran the connector. Running it (dispatch, integrations, the Edge Agent)
is S33's.
