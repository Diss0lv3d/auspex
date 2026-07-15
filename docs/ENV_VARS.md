# ENV_VARS — every variable, documented (rule: born here + .env.example simultaneously)

| Var | Purpose | Required | Default | Since |
|---|---|---|---|---|
| APP_ENV | `dev` or `prod`. Gates `/api/auth/dev-login` (dev only), `/api/docs` (dev only), and SECRET_KEY strictness | no | `dev` | S0 |
| DATABASE_URL | Postgres DSN (transactional truth; D-001). In compose: `postgresql://auspex:auspex@postgres:5432/auspex`; from host (tests): port `55432` | no | compose-internal DSN | S1 |
| OPENSEARCH_URL | Our OWN OpenSearch container (D-009); SARA's cluster is reference-only, its creds never appear here | no | `http://opensearch:9200` | S0 |
| OPENSEARCH_USER / OPENSEARCH_PASS | Basic auth for real clusters. Local dev container runs `DISABLE_SECURITY_PLUGIN=true`, so these are ignored locally | no | empty | S0 |
| LLM_BASE_URL / LLM_MODEL / LLM_API_KEY | Customer-supplied OpenAI-compatible endpoint (D-005). Loaded by config since S1, first used in S2. **Dev primary (D-015):** Llama-4-Scout via Northflank — a normal remote HTTPS URL that resolves identically from host and container (so `auspex.devhost` does NOT pin it; `.env` is the single source of truth). **Dev secondary/offline (D-013):** local Ollama `qwen3:14b` — set `LLM_BASE_URL=http://host.docker.internal:11434` (container; compose `extra_hosts: host-gateway`) or `http://localhost:11434` (host runs). Secrets never committed — `.env` and `.env.bak-northflank` are gitignored | no (until S2) | empty | S0 |
| SECRET_KEY | JWT signing key (HS256). **Required when APP_ENV=prod**; in dev, a missing key falls back to an ephemeral per-process key (tokens die on restart). Generate: `openssl rand -hex 32` | prod: yes | none (dev: ephemeral) | S1 |
| JWT_TTL_MINUTES | Session JWT lifetime in minutes | no | `720` | S1 |
| GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET | Google OAuth web client. Both empty ⇒ OAuth endpoints return 503 "not configured" (config-stubbed) | no | empty | S1 |
| GOOGLE_REDIRECT_URI | OAuth callback URL registered with Google | no | `http://localhost:8000/api/auth/google/callback` | S1 |
