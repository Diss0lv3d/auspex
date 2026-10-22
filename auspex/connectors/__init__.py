"""Connectors, the core side (S32, D-064): a manifest action compiles to today's
`ActionSpec` (`compile.py`), and the job kinds and payload the connector agent will
run are declared here in code (`jobs.py`). The handlers for those kinds are S33's.

The core may import `auspex_sdk.manifest` and `auspex_sdk.vocab` only: the manifest
types are the SDK's (spec decision 1), and the SDK never imports the core."""
