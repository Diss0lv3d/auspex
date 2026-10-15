# S30 tenancy, live (2026-10-15)

Reality snapshot of D-061's tenancy through the container `./ci.sh` rebuilt,
after the full gate. Emails and tokens are redacted; ids are random uuids of
rows deleted at the end.

## Gate

`./ci.sh > /tmp/claude-ci.log 2>&1; echo $?` printed `0`. Log: ruff `All checks
passed!`, then `1538 passed, 1 warning in 115.97s (0:01:55)`.

## Live check

Commands, as in the S30 plan's Task 9, Step 6 (the live admin address
is a synthetic `@s30-live` one, shown as `<email>`; `$TOKEN` is the dev-login token, `$SW`
the token the switch into `s30-live-bank` returned).

```
$ python -m auspex.tenancy list
29 organizations, all kind `direct` (the migration's one per workspace, plus test fixtures);
`default` shows `default (global, 13 members)`, `dev` shows `dev (global, 0 members)`, the rest
`(no workspace)`. Exit 0. (Fixture list elided.)

$ create-org
created provider organization 's30-live-mssp' with workspace 's30-live-mssp' (global)
[exit 0]
$ create-client
created client 's30-live-bank' of 's30-live-mssp' with workspace 's30-live-bank' (ksa)
[exit 0]
$ set-member
membership in 's30-live-mssp' set: admin
[exit 0]
$ GET /api/auth/me
{
    "user": {
        "id": "8f2b0add-666b-47b9-be2e-d7051173aef2",
        "email": "<email>",
        "display_name": ""
    },
    "organization": {
        "id": "d932915c-6cff-4d5f-a1b6-e55497e76a93",
        "name": "s30-live-mssp",
        "kind": "provider"
    },
    "workspace": {
        "id": "ce6495cc-dede-43d7-910e-53fcff3f9444",
        "name": "s30-live-mssp",
        "region": "global",
        "role": "admin",
        "organization": "s30-live-mssp"
    },
    "workspaces": [
        {
            "id": "ce6495cc-dede-43d7-910e-53fcff3f9444",
            "name": "s30-live-mssp",
            "region": "global",
            "role": "admin",
            "via": "membership",
            "organization": {
                "id": "d932915c-6cff-4d5f-a1b6-e55497e76a93",
                "name": "s30-live-mssp",
                "kind": "provider"
            }
        },
        {
            "id": "1859b999-8237-44d7-81cf-40fcd8cc8985",
            "name": "s30-live-bank",
            "region": "ksa",
            "role": "admin",
            "via": "provider_wide",
            "organization": {
                "id": "d39fb791-a370-47ea-8dcf-ff0a5211e9d8",
                "name": "s30-live-bank",
                "kind": "client"
            }
        }
    ]
}
$ POST /api/chat deep (status)
403
$ POST /api/chat CVE (first 300 bytes)
data: {"session": "63ac1b30-d5ef-4fa7-a68d-d56ea0f96716"}

data: {"content": "Knowledge base read on 1 vulnerability:\n\n- CVE-2021-44228 \u2014 CRITICAL (CVSS 10.0)\n  Apache Log4j2 2.0-beta9 through 2.15.0 (excluding security releases 2.12.2, 2.12.3, and 2.3.1) JNDI features used in configuration,
$ GET /api/audit?limit=5
{
    "events": [
        {
            "id": "608acd3f-93eb-4c6f-8704-8aef40964fb2",
            "at": "2026-10-15T12:58:17.786303+00:00",
            "action": "workspace.enter",
            "actor": {
                "kind": "user",
                "user_id": "8f2b0add-666b-47b9-be2e-d7051173aef2",
                "email": "<email>",
                "display_name": "",
                "organization": "s30-live-mssp"
            },
            "subject": {
                "user_id": null,
                "email": null
            },
            "details": {
                "via": "switch"
            }
        },
        {
            "id": "07f331f9-b5c2-4471-9b32-61cc7a7afacf",
            "at": "2026-10-15T12:58:17.485546+00:00",
            "action": "workspace.create",
            "actor": {
                "kind": "cli",
                "user_id": null,
                "email": null,
                "display_name": null,
                "organization": null
            },
            "subject": {
                "user_id": null,
                "email": null
            },
            "details": {
                "region": "ksa",
                "workspace": "s30-live-bank"
            }
        },
        {
            "id": "6a69cea3-900a-4c98-a002-52f8948b2166",
            "at": "2026-10-15T12:58:17.485221+00:00",
            "action": "org.create",
            "actor": {
                "kind": "cli",
                "user_id": null,
                "email": null,
                "display_name": null,
                "organization": null
            },
            "subject": {
                "user_id": null,
                "email": null
            },
            "details": {
                "kind": "client",
                "organization": "s30-live-bank"
            }
        }
    ]
}
$ cleanup
DELETE 2
DELETE 1
DELETE 1
DELETE 1
[exit 0]
```

Reading it:
- `/me` lists `s30-live-mssp` (`via: membership`, the explicit admin row the CLI
  wrote) and `s30-live-bank` (`region: ksa`, `via: provider_wide`).
- The deep chat turn in the ksa workspace answered `403` (the region guard, no
  engine call).
- The CVE question answered on the shortcut path: an SSE stream whose first
  event is the session id and whose content is the knowledge-base read.
- The audit shows `workspace.enter` with `details.via = switch` by the user,
  and the CLI's `workspace.create` and `org.create` for the client (actor kind
  `cli`). Only three events were returned for `limit=5` in that workspace's
  trail.
- Cleanup ran: `DELETE 2` (workspaces), `DELETE 1` (users), `DELETE 1`,
  `DELETE 1` (organizations).

## Mutant table (Task 8)

Files run: isolation, access, roles, members_api, region_guard, admin (90 tests
baseline). 10 of 10 caught after one pinning test (9 of 10 before).

| # | File | Mutant | Result | Caught by |
|---|---|---|---|---|
| 1 | access.py | delete `AND NOT co.restricted` | caught (4) | isolation::test_a_grant_reaches_a_new_client_but_not_a_restricted_one; access::test_a_provider_wide_admin_reaches_unrestricted_clients_only, ::test_only_narrows_to_one_workspace; admin::test_restricting_a_client_withdraws_the_grant |
| 2 | access.py | `w.org_id IN (SELECT id FROM reach)` to `true` | caught (4) | access::test_a_stray_membership_outside_reach_grants_nothing[3 params], ::test_a_grant_held_by_someone_homed_elsewhere_reaches_nothing |
| 3 | access.py | `(e.via='membership') DESC` to ASC | caught (1) | access::test_an_explicit_membership_wins_over_the_grant |
| 4 | auth.py `_context` | no `access is None` check | caught (3) | isolation::test_a_client_user_reaches_neither_a_sibling_nor_the_provider, ::test_an_mssp_analyst_without_a_membership_cannot_enter_a_client, ::test_a_removed_membership_ends_access_at_the_next_request |
| 5 | auth.py | `require_admin = require_role("admin","analyst")` | caught (1) | members_api::test_every_admin_route_refuses_an_analyst_and_a_viewer |
| 6 | admin.py `_add` | delete `actor.user_id == user_id` check | caught (1) | admin::test_no_one_changes_their_own_membership |
| 7 | admin.py `_add` | delete home-org check | caught (4) | members_api::test_the_api_refuses_self_changes_and_strangers; admin::test_a_member_is_added_only_within_reach, ::test_an_admin_homed_in_another_org_leaves_nothing, ::test_create_client_admin_must_belong_to_the_provider |
| 8 | region.py | `may_process` returns True | caught (3 failed, 1 error) | region_guard::test_a_ksa_turn_on_a_global_engine_is_refused_with_nothing_stored, ::test_a_ksa_ioc_check_makes_no_third_party_lookup, ::test_a_ksa_investigation_lookup_and_summary_are_refused |
| 9 | service.py | fan out to `self._providers`, not `allowed` | survived (90 passed); pinned, then caught | added `test_a_ksa_lookup_reaches_only_the_providers_in_its_region` |
| 10 | proposals.py | delete stream per-tick re-check | caught (1) | roles::test_a_removed_member_s_open_stream_ends |

Mutant 9 survived because, with only global providers, `allowed` is empty, so
`fan_out` is never reached and the old tests could not tell `allowed` from
`self._providers`. The pin uses a mixed set (one global, one ksa provider) in a
ksa workspace: the global one gets 0 lookups, the ksa one 1.
