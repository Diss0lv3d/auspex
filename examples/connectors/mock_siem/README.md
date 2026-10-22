# example.mock_siem 1.0.0

The reference connector, and the one to copy. It talks to a made-up SIEM and does the four
things a connector does: `test` (the admin's "Test connection"), `fetch` (pages of alerts, with
a cursor), and one `write` action, `close_alert`, with a dry run, an undo (`reopen`) and an
observe (is the alert closed?).

It is written twice, with the same result:

| Source | What it is |
|---|---|
| `python/mock_siem.py` | Python-first: decorators declare the connector, commands and action. |
| `yaml/connector.yaml` + `yaml/mock_siem.py` | The same declarations as YAML; the module holds plain handler functions. |

Both build to a byte-identical `manifest.json`. Their package hashes differ because the code
differs. Each source directory builds on its own: nothing is shared between them.

The mock SIEM exists only as recorded exchanges in `fixtures/`, so nothing here needs a network
or a real credential. The fixtures use `https://siem.example.test` and a placeholder token.

## Build

    auspex-sdk build examples/connectors/mock_siem/python
    auspex-sdk build examples/connectors/mock_siem/yaml

Each writes `dist/example.mock_siem-1.0.0.zip` in its own directory (git-ignored) and prints
the package hash.

## Run a command against the fixtures

The harness runs one command with a config, secrets and one fixture, and prints the validated
result. A fixture answers each recorded request once, so use one per scenario:

    echo '{"base_url": "https://siem.example.test"}' > config.json
    echo '{"api_token": "example-token"}' > secrets.json
    auspex-sdk run examples/connectors/mock_siem/python test \
        --config config.json --secrets secrets.json \
        --fixture examples/connectors/mock_siem/fixtures/test.json

The same thing from Python, which is what `tests/test_reference_connector.py` does:

    from pathlib import Path
    from auspex_sdk.harness import run_command

    run_command(
        Path("examples/connectors/mock_siem/python"),
        "close_alert.dry_run",
        config={"base_url": "https://siem.example.test"},
        secrets={"api_token": "example-token"},
        fixture=Path("examples/connectors/mock_siem/fixtures/alert_open.json"),
        arguments={"alert_id": "A-1001"},
    )

Commands: `test`, `fetch`, and `close_alert.dry_run|execute|undo|observe`. Fixtures:
`test`, `fetch_first_page`, `fetch_next_page` (cursor `c2`), `alert_open`, `alert_closed`,
`close`, `reopen`.

## Register it

An admin registers the zip with `POST /api/connectors` (an admin, multipart `package`); that
route is added in this session's catalogue task. The platform reads `manifest.json`, shows the
config form (SIEM URL, API token, TLS), and lists `close_alert` as an action that needs
approval.

## Notes for authors

- `hosts` is `["https://{base_url}"]`: the handlers can reach only the host of the admin's
  SIEM URL. A request anywhere else is refused.
- `tls` defaults to "verify". There is no setting that turns verification off.
- `close_alert` takes an optional `note`. When it is left out, the handler receives `None`.
- Without an `observe`, a failed execute would settle as `incomplete` (effects unknown). Here
  `observe` returns 1 if the alert is closed and 0 if not, so the platform can tell whether
  a failed close landed.
