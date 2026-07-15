# IDEAS — parking lot (never implemented directly from here)
- Herd Immunity federation (flagship phase 2; k>=3 anonymity) — deferred by design
- MCP server surface: expose Auspex as the security-intel backend for external AI agents
- Detection backtest loop (English -> Sigma -> backtest vs customer logs) — needs log access
- Investigation cost ledger UI (token spend per verdict)
- PCAP/EVTX/EML artifact drop -> auto investigation
- API-key management endpoints: GET /api/auth/api-keys (list) + DELETE (revoke, sets
  revoked_at) + optional expires_at. Schema/chokepoint already support revocation
  (S1); only the product surface to reach it is missing. (Raised in S1 review.)
- Scorecard mode ladder conflates call *syntax* with task *competence* (llama3.1:8b: 98.7% valid calls, 52.5% completion → demoted to prompted_tools, which wouldn't fix reasoning failures). Consider separate thresholds: native calls + tighter orchestration (plan check, forced result citation) as a fourth mode. Evidence: docs/probes/2026-07-15-ollama-endpoint.md.
- Harness: pass observable IDs (not raw 64-char hashes) in tool args — small models truncate long strings in arguments. S3 tool-design input.
