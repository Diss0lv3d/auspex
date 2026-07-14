# IDEAS — parking lot (never implemented directly from here)
- Herd Immunity federation (flagship phase 2; k>=3 anonymity) — deferred by design
- MCP server surface: expose Auspex as the security-intel backend for external AI agents
- Detection backtest loop (English -> Sigma -> backtest vs customer logs) — needs log access
- Investigation cost ledger UI (token spend per verdict)
- PCAP/EVTX/EML artifact drop -> auto investigation
- API-key management endpoints: GET /api/auth/api-keys (list) + DELETE (revoke, sets
  revoked_at) + optional expires_at. Schema/chokepoint already support revocation
  (S1); only the product surface to reach it is missing. (Raised in S1 review.)
