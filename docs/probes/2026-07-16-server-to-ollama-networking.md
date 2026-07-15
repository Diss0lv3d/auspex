# Probe: app container → host Ollama networking (S3 step 0, STATE.md blocker #5)

- **Date:** 2026-07-16 (S3)
- **Goal:** let the app *container* reach the host Ollama (D-013) so the agent
  loop can run server-side. Blocker recorded in STATE.md #5.

## Repo-side wiring (DONE, committed)

`docker-compose.yml` app service now declares:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

and the container-side `LLM_BASE_URL=http://host.docker.internal:11434`
(`.env`; host runs use `http://localhost:11434` via `auspex.devhost`).

## Verified reality (from inside `auspex-app-1`, 2026-07-16)

```
$ docker compose exec app python -c "from auspex.config import get_settings; \
    print(get_settings().llm_base_url)"
http://host.docker.internal:11434         # container picks up the right URL

$ docker compose exec app getent hosts host.docker.internal
172.17.0.1      host.docker.internal      # host-gateway alias RESOLVES ✅

$ docker compose exec app python -c "import urllib.request; \
    urllib.request.urlopen('http://host.docker.internal:11434/api/version', timeout=5)"
ConnectionRefusedError: [Errno 111] Connection refused   # port refuses ❌
```

DNS + routing to the host work (we reached `connect()`, not a resolution
error). The refusal is a **bind-address** problem, not a compose problem:

```
$ ss -tlnp | grep 11434
LISTEN 0 4096 127.0.0.1:11434 0.0.0.0:*    # Ollama binds LOOPBACK ONLY
```

Ollama listens on `127.0.0.1` only, so the docker-bridge gateway IP
(`172.17.0.1`) has nothing to connect to. No container-side change can reach a
loopback-only host service (short of `network_mode: host`, which would break
the compose service-name DNS for postgres/opensearch — rejected).

## Remaining unblock (HOST command, needs sudo — one-time)

Make the snap Ollama listen on all interfaces and restart its listener:

```bash
sudo snap set ollama host=0.0.0.0
sudo snap restart ollama.listener
# fallback if the snap ignores `host`: export OLLAMA_HOST=0.0.0.0:11434 for the
# service and restart it.
```

Then re-verify from the container (expected: `HTTP 200` + model list):

```bash
docker compose exec app python -c "import urllib.request, json; \
  r=urllib.request.urlopen('http://host.docker.internal:11434/v1/models', timeout=5); \
  print(r.status, [m['id'] for m in json.load(r)['data']])"
```

## Status

- Repo wiring: **DONE** (host-gateway + container URL + devhost host pin).
- End-to-end container→Ollama reachability: **PENDING the host command above**
  (sudo; not runnable from the non-interactive session). Does NOT gate S3
  steps 1–3 (offline/FAKE-client tested) or CI (hermetic).
