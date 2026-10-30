"""The Edge Agent (S33, D-062): it claims its integrations' jobs over the edge API, runs
each command from a hash-verified package in a subprocess, and posts the answer. It
imports `auspex_sdk` and `auspex.edge` only, never the core (a structural test)."""
