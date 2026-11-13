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

The fastest path is the one-shot script, which also keeps the LLM provider in
Presenton in sync with the environment (see "Provider settings drift" below):

```bash
ALBERT_API_KEY=... bin/presenton-up     # start everything, wait for health
bin/presenton-down                      # stop, keep ./data
bin/presenton-down --wipe               # stop and delete the sidecar state
```

It is idempotent: re-running keeps `./data` (database, object storage, decks),
rebuilds nothing that is already built, and re-applies the provider settings.
Use `--no-build` to skip the image builds and `--reset` to wipe before starting.
First run needs an `ALBERT_API_KEY` in the environment so it can write the env
files; it targets the sovereign Albert API with `mistral-medium-3-5`.

Doing it by hand:

```bash
# 1. Configure the LLM provider (any OpenAI-compatible endpoint).
cp env.d/development/presenton.dist env.d/development/presenton
#    edit: PRESENTON_LLM_BASE_URL / PRESENTON_LLM_API_KEY / PRESENTON_LLM_MODEL
#    Albert API:      https://albert.api.etalab.gouv.fr/v1  mistral-medium-3-5
#    Etalab Mistral:  https://api.mistral.etalab.gouv.fr/v1  mistral-medium-3-5
#    Ollama on host:  http://host.docker.internal:11434/v1   <your model>

# 2. Load the env and start the sidecar (base stack optional for P1).
set -a; . env.d/development/presenton; set +a
docker compose -f compose.yml -f compose.presenton.yml up -d presenton

# 3. To use the feature from the assistant, start the backend with the same
#    overlay: it injects PRESENTON_BASE_URL / PRESENTON_BROWSER_BASE_URL and
#    enables the presenton_sidecar flag in app-dev. Without this the backend
#    sees no sidecar address and generation fails as unconfigured.
docker compose -f compose.yml -f compose.presenton.yml up -d app-dev

# 4. Wait for health, then open http://localhost:5001 (no login in POC mode).
docker compose -f compose.yml -f compose.presenton.yml ps presenton
```

State lives in `./data/presenton` (gitignored): database, exports, uploads.
Delete that directory to reset the sidecar completely.

### Provider settings drift

Presenton imports the LLM configuration from the environment **once**, on its
first boot, into the `provider_settings` row of `./data/presenton/fastapi.db`,
and that row wins over the environment afterwards. Changing
`env.d/development/presenton` later has no effect: the sidecar keeps calling the
old endpoint with the old key, and deck generation fails with
`401 Invalid API key` even though the container environment looks correct.

`bin/presenton-up` re-applies the environment values on every run through
`PUT /api/v1/admin/provider-settings`, which needs no credentials while
`DISABLE_AUTH=true`. By hand:

```bash
curl -X PUT http://localhost:5001/api/v1/admin/provider-settings \
  -H 'Content-Type: application/json' \
  -d "{\"LLM\":\"custom\",
       \"CUSTOM_LLM_URL\":\"$PRESENTON_LLM_BASE_URL\",
       \"CUSTOM_LLM_API_KEY\":\"$PRESENTON_LLM_API_KEY\",
       \"CUSTOM_MODEL\":\"$PRESENTON_LLM_MODEL\"}"
```

`GET` on the same route is the quickest way to see which key the sidecar is
actually using.

### Container DNS in the Docker VM

The frontend image runs `yarn install` on `node:24-alpine`. When the Docker VM's
only nameserver is Docker's internal forwarder, musl's resolver intermittently
returns `EAI_AGAIN` under yarn's parallel lookups and the build fails with
`error Error: getaddrinfo EAI_AGAIN registry.yarnpkg.com` — even though
`getent hosts` and a single Node lookup both succeed. Giving the daemon public
resolvers fixes it (Colima):

```bash
colima ssh -- sudo sh -c 'cat > /etc/docker/daemon.json <<EOF
{"features": {"buildkit": true, "containerd-snapshotter": true},
 "dns": ["1.1.1.1", "8.8.8.8"]}
EOF
systemctl restart docker'
```

Allow >= 6 CPU and >= 8 GiB for the VM: Conversations (backend, frontend,
Keycloak, Postgres x2, Redis, object storage) plus Presenton (Chromium, ~3.7 GB
image) does not fit in the default 2 CPU / 2 GiB.

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
