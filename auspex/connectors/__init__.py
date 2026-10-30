"""Connectors, the core side (S32, D-064): a manifest action compiles to today's
`ActionSpec` (`compile.py`), and the job kinds and payload the connector agent will
run are declared here in code (`jobs.py`). The handlers for those kinds are S33's.

The catalogue (`catalogue.py`) holds the registered packages and answers which connectors a
workspace has; first-party packages are registered by `python -m auspex.connectors`.

The core may import `auspex_sdk.manifest`, `auspex_sdk.vocab` and `auspex_sdk.package` only:
the manifest types are the SDK's (spec decision 1), `package` is pure (zipfile and hashing,
nothing a package ships is imported or run, D-062), and the SDK never imports the core."""
