# ENV_VARS — every variable, documented (rule: born here + .env.example simultaneously)
| Var | Purpose | Since |
|---|---|---|
| APP_ENV | dev/staging/prod | S0 |
| OPENSEARCH_URL / _USER / _PASS | Own OpenSearch container (D-009); SARA's cluster is reference-only | S0 |
| DATABASE_URL | Postgres DSN | S1 |
| LLM_BASE_URL / LLM_MODEL / LLM_API_KEY | Customer-supplied OpenAI-compatible endpoint (D-005) | S0 |
| SECRET_KEY | JWT + crypto | S1 |
| GOOGLE_CLIENT_ID | OAuth | S1 |
