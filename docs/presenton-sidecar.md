# Presenton sidecar runbook (POC)

This is the P1 stand-up for the slides-loop POC
(`docs/poc-presenton-sidecar-plan.md`). Presenton runs as an extra compose
service; Conversations will drive it over the self-hosted v1 API in later PRs.

## Security posture (read first)

The POC runs Presenton with `DISABLE_AUTH=true`, its supported single-user
runtime (the same mode the Electron app uses). **This disables authentication
for the API as well as the UI.** Therefore:

- The port is published on `127.0.0.1` only. Never expose it on a shared or
  public host, and never put this overlay in front of a reverse proxy that
  serves other users.
- Pin the image to `v0.9.12-beta` or newer: earlier versions carry a CSRF
  vulnerability (CVE-2026-122151) and unauthenticated-access issues fixed in
  the 0.9.12 line.
- For a multi-user or exposed deployment, drop `DISABLE_AUTH`, create users in
  Presenton's admin panel, and use an admin-generated API key
  (`PRESENTON_API_KEY`) for backend calls. The browser editor then needs a
  Presenton session (one shared login for a POC; SSO is future work).

## Bring it up

```bash
# 1. Configure the LLM provider (any OpenAI-compatible endpoint).
cp env.d/development/presenton.dist env.d/development/presenton
#    edit: PRESENTON_LLM_BASE_URL / PRESENTON_LLM_API_KEY / PRESENTON_LLM_MODEL
#    Etalab Mistral:  https://api.mistral.etalab.gouv.fr/v1  mistral-medium-3-5
#    Ollama on host:  http://host.docker.internal:11434/v1   <your model>

# 2. Load the env and start the sidecar (base stack optional for P1).
set -a; . env.d/development/presenton; set +a
docker compose -f compose.yml -f compose.presenton.yml up -d presenton

# 3. Wait for health, then open http://localhost:5001 (no login in POC mode).
docker compose -f compose.yml -f compose.presenton.yml ps presenton
```

State lives in `./data/presenton` (gitignored): database, exports, uploads.
Delete that directory to reset the sidecar completely.

### Two sidecar addresses

The backend and the browser reach the sidecar differently, so the client
keeps two base URLs:

- `PRESENTON_BASE_URL` — backend → sidecar API address. Inside the compose
  network this is the service name (`http://presenton:80`); on the host it is
  the published port (`http://localhost:5001`).
- `PRESENTON_BROWSER_BASE_URL` — browser → sidecar origin used for the editor
  and export card URLs. It must be reachable from the user's browser (the
  published loopback port), never the compose service hostname. Defaults to
  `PRESENTON_BASE_URL` when unset (fine when both run on the host).

Using the API address for card URLs would hand the browser a hostname it
cannot resolve; the split keeps generation working while the card actions
stay usable.

Resource notes: the image is ~3.7 GB (it bundles Chromium for export and
embedding models). Generation runs a full LLM outline + per-slide content
pipeline; on a laptop expect tens of seconds to a few minutes per deck
depending on the provider.

## Run the integration spike

`bin/presenton-spike` exercises the whole v1 loop with stdlib Python only:

```bash
PRESENTON_URL=http://localhost:5001 python3 bin/presenton-spike
# with auth enabled instead:
PRESENTON_URL=http://localhost:5001 PRESENTON_API_KEY=sk-presenton-... \
    python3 bin/presenton-spike
```

It checks, in order:

1. `POST /api/v1/ppt/presentation/generate/async` starts a task.
2. `GET .../status/{id}` reaches `completed` (bounded poll, 10 min).
3. `GET .../presentation/{id}` returns the deck with slides.
4. `POST .../presentation/edit` deep-merges a new title into slide 0 and
   **verifies no other slide changed** (the anti-drift guarantee the rework
   bridge relies on).
5. `POST .../presentation/derive` creates a new presentation id and
   **verifies the original is untouched** (the versioning primitive).
6. Both exported PPTX files download and are structurally valid zips with
   `ppt/presentation.xml` and slide parts.
7. The editor page `/presentation?id=...` is fetched and its
   `X-Frame-Options` / CSP `frame-ancestors` headers recorded: with neither
   present, the editor can be embedded in an iframe (the no-new-tab
   requirement).

Artifacts land in `/tmp/presenton-spike/` (`deck.json`, `status.json`,
`original.pptx`, `derived.pptx`, `findings.json`). Exit code 0 = all passed.

## What the spike does not cover

- Real-browser iframe rendering and cookie behavior (needs a browser; done
  manually or in the P6 Playwright flow). The header probe is necessary but
  not sufficient evidence for embedding.
- AI slide edits (`POST /api/v1/ppt/slide/edit`) - exercised in P4.
- Conversations integration itself - P2 onwards.

## Teardown

```bash
docker compose -f compose.yml -f compose.presenton.yml down
# keep ./data/presenton to preserve decks, or delete it to reset.
```
