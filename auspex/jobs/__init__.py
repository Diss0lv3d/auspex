"""The jobs queue (D-065, S31): our own Postgres table, claimed with
`FOR UPDATE SKIP LOCKED`, and the in-app worker that runs it."""
