# POC plan: Presenton sidecar for the slides loop

Status: proposal, 2026-11-12. Companion to `poc-slides-studio-plan.md` (the native
approach). Same fork `kaaloo/conversations`, same branch `poc/slides-loop-plan`.
This document answers: what would it take to run Presenton as a sidecar, and what is
the PR breakdown.

## 1. What "sidecar" means here

Run **Presenton** (Apache-2.0, self-hosted) as an extra service in the existing
`docker compose` stack and let Conversations drive it over its REST API. Presenton
owns deck generation, the canvas editor, AI editing and PPTX export; Conversations
owns the chat, the link between a conversation and a deck, and the comment/rework
bridge.

This is an **alternative** to the native studio, not a layer on top of it. Both use the
same chat-bridge idea (a normal message carrying a deck reference + comments), but they
differ on where the deck lives and who edits it:

| | Native studio | Presenton sidecar |
|---|---|---|
| Deck model | upstream `Presentation` spec (5 layouts) | Presenton HTML/Tailwind templates, free-form canvas |
| Editor | small React field editor we build | Presenton's full canvas editor, reused |
| Export | existing python-pptx + Marianne template | Presenton PPTX (its own design system) |
| New services | none | Presenton container (Chromium/Puppeteer, its own DB) |
| Net new code | studio UI + models + revision tool | API client + mapping + embed + bridge |
| Upstream fit | additive to an existing upstream feature | introduces an external dependency |

The sidecar trades a new service and an auth wrinkle for a much richer editor and less
UI to build. The native plan trades editor richness for zero new services and a clean
upstream story.

## 2. Effort verdict

**Moderate, and front-loadable into a cheap go/no-go.** Roughly 4-6 focused days for a
working loop, comparable to the native ~6 days, but with a different risk profile: the
native plan's risk is UI volume, the sidecar's risk is one integration unknown
(section 3). Because that unknown is resolvable in about a day, the sidecar is a
reasonable POC **if** PR 1 below comes back green. If it comes back red, stop and fall
back to the native plan rather than building a fragile auth workaround.

What makes it not-too-intensive:

- Presenton's self-hosted v1 API already has every primitive the loop needs
  (verified against the published OpenAPI, v0.9.7-beta):
  - `POST /api/v1/ppt/presentation/generate` and `/generate/async` + `GET .../status/{id}`
  - `GET /api/v1/ppt/presentation/{id}` (inspect slide indices + content)
  - `POST /api/v1/ppt/presentation/edit` (deep-merges targeted slides, preserves the rest)
  - `POST /api/v1/ppt/presentation/derive` (modified copy, original kept -> versioning)
  - `POST /api/v1/ppt/slide/edit` (AI edit of one slide)
  - export to PPTX/PDF, `DELETE`, list.
- It is one container, configured entirely by env (OpenAI-compatible endpoint via
  `CUSTOM_LLM_URL`/`CUSTOM_LLM_API_KEY`/`CUSTOM_MODEL`, or `OLLAMA_URL`), so it points at
  the same Etalab Mistral / Ollama provider as Conversations.
- The `derive` endpoint gives versioning for free; the `edit` deep-merge gives the
  "only touch the targeted slides" guarantee for free. Those are two of the hardest
  parts of the native plan, already solved upstream of us.

## 3. The one real wrinkle: embedding the editor (self-hosted auth)

> **Update 2026-11-12 (source + issue research).** The v3 question now has a definitive
> answer, and a no-new-tab embedding path exists that does not depend on v3. See 3.1
> and 3.2; the option list below is superseded by 3.2 for the POC.

Presenton's clean embedded-editor flow - a **scoped, expiring, per-presentation iframe
token** (`POST /api/v3/presentation/integrate`, scopes `presentation:read/edit/export`)
- is **Cloud API v3 only**. The self-hosted v1 surface does not expose it.

Self-hosted auth is split (verified in Presenton's auth docs):

- Browser UI: user sign-in **session** (local accounts, admin-managed).
- `/api/v1/*` and `/mcp`: admin-generated **API key** (Bearer). API keys cannot sign in
  to the browser UI.

Consequences for a local sidecar POC:

- Driving Presenton **from the Conversations backend** with an API key is clean and
  fully supported. Generation, edit, derive, export all work this way.
- Showing Presenton's **editor inside Conversations** via iframe is the open question:
  the editor wants a session, and there is no self-hosted per-deck token. Options, in
  order of preference:
  1. **Open the editor in a new tab** at `PRESENTON_URL/presentation?id=...`, with a
     single shared local Presenton login for the POC. Simplest; the "in-app" feel is
     weaker but the loop is fully demonstrable. This is the POC default.
  2. **Same-origin iframe behind the existing nginx** with a shared dev session cookie
     and relaxed `frame-ancestors`. Keeps it visually in-app; more config, still a
     shared login (acceptable for a localhost single-user POC, not for production).
  3. A real per-user SSO bridge between Keycloak and Presenton. Correct long-term, but
     out of scope for a POC and the main reason this could balloon.

**PR 1 exists to decide between these with evidence, not assumption.** It stands up
Presenton, confirms the API-key loop end to end with curl, and probes whether the
self-hosted editor can be framed/opened with an acceptable local auth story. That
result sets the embedding approach for PR 3 and the go/no-go for the whole sidecar.

### 3.1 Why self-hosted is v1, and whether parity is coming (researched 2026-11-12)

- **v3 is intentionally closed, not lagging packaging.** Issue
  [presenton/presenton#391](https://github.com/presenton/presenton/issues/391)
  ("v3 API endpoints not included in Docker image", Jan-May 2026): maintainer
  ShivaRajBadu confirmed the v3 code is "intentionally not part of the open-source
  distribution at this time": model variability across self-hosted environments
  makes it unreliable, so they will not ship it in Docker until it behaves
  consistently. Docs were updated to say "If you're using open-source, use v1
  APIs. v3 APIs are not yet available on open-source."
- **No timeline, ever.** Two users asked for an ETA in that issue (Feb and May 2026);
  neither got one. The issue was closed with the doc clarification, not a commitment.
- **Verified in current source (Nov 2026, v0.9.12-beta era):** `servers/fastapi/api/`
  contains only `v1/` and `v2/`. Zero v3 route code. The only v3 touchpoints are
  *outbound client calls* to Presenton Cloud (community gallery
  `api.presenton.ai/api/v3/community/...`, and an optional cloud-provider proxy).
- **Self-hosted is catching up incrementally, under v1/v2, not via a v3 drop.** A v2
  router already exists in the OSS image (`/api/v2/ppt/...`, "Smart" adaptive-layout
  generation, sync + async). Recent releases keep adding self-hosted capability:
  air-gapped deployment support (v0.9.11), AI slide-edit template fixes and a
  `/status/{id}` fix (v0.9.12), MCP single-slide editing requested (#1022, open).
  The stated reason for withholding v3 (Smart-mode reliability across models) is
  being addressed in OSS as v2 - so expect continued v1/v2 growth, with the
  cloud-only surface (integrate tokens, cloud workspaces) staying commercial.
- **Roadmap caveat:** the README points to a public GitHub Projects board
  (orgs/presenton/projects/2); it could not be read with available credentials
  (`read:project` scope) and does not render anonymously. Nothing in issues,
  releases, or docs announces v3 parity. If Luis wants certainty, asking on #391 or
  the project's Discord is the direct route; the evidence-based planning assumption
  is **no v3 in self-hosted for the foreseeable future**.

### 3.2 No-new-tab embedding without v3 (source-verified)

The editor does not need v3 tokens to be framed:

- **No framing restrictions exist.** Repo-wide search: no `X-Frame-Options`, no
  `frame-ancestors` CSP anywhere (nginx.conf, next.config.mjs headers() only sets
  font CORS). The editor page `/presentation?id=<uuid>` takes only the id
  (`servers/nextjs/app/(presentation-generator)/presentation/page.tsx`).
- **Session auth is a cookie, and localhost is same-site.** Conversations
  (`localhost:3000`) framing Presenton (`localhost:5001`) is cross-origin but
  same-site (scheme + registrable domain "localhost"), so a `SameSite=Lax` session
  cookie is sent on the iframe load. One login to Presenton in the same browser
  covers the iframe; no per-deck token needed for a single-user POC.
- **`DISABLE_AUTH=true` is a supported single-user runtime.** Both the FastAPI
  `SessionAuthMiddleware` and the Next.js server auth (`serverAuth.ts`) short-circuit
  to an admin principal when it is set (this is how the Electron app runs). The
  browser-side `window.env.DISABLE_AUTH` is only injected by Electron, but the
  server-side paths are what gate the routes, so the editor loads without a login
  screen. **Caveat: it disables auth for the API too** - acceptable only while the
  sidecar is bound to loopback / the compose network, never exposed.
- **Multi-user later:** Presenton accounts are admin-managed local users, not OIDC;
  per-user SSO would be custom work. Out of POC scope.

**Revised POC default:** iframe the editor inside Conversations, Presenton running
with `DISABLE_AUTH=true` on a loopback-bound port (simplest), or with one shared
login (keeps API-key auth intact). PR 1 verifies both empirically - including cookie
behavior in the target browsers - instead of treating embedding as an open risk.
Security note: pin >= v0.9.12-beta (CSRF fix CVE-2026-122151; the Oct 2026 security
issues #972/#974/#975 were fixed in that line).

## 4. Architecture

```text
Browser (Conversations)
   │  chat: "make a deck about X"
   ▼
Conversations backend ──(API key, server-side)──► Presenton /api/v1
   │   generate/async → poll status → presentation_id
   │   stores mapping conversation ↔ presentation_id (+ version lineage)
   │   returns tool metadata {presentation_id, edit_url, export_url}
   ▼
Deck card in chat ──► open editor in an in-app iframe (per 3.2; PR 1 verifies)
   │                      │ manual canvas edits happen in Presenton
   │   comments stored in Conversations, anchored to slide index (+field)
   ▼
"Rework" → normal chat message {presentation_id, comments, instruction}
   → agent tool reads latest deck via GET, applies Presenton edit/derive
   → new version, card refreshes
```

Division of responsibility:

- **Presenton** is the source of truth for deck content and the editor. We do not
  re-implement its model.
- **Conversations** stores only the mapping (`conversation_id`, `presentation_id`,
  version lineage) and the comments. Comments live in Conversations because the
  comment→agent bridge is ours; Presenton has no equivalent annotation API.
- The **API key never reaches the browser**. All Presenton calls go through a
  Conversations backend client (the `docs_client.py` pattern). The browser only ever
  gets an edit URL / export URL.

## 5. PR breakdown

Six PRs, stacked in order, each independently reviewable and demoable. Estimates are
focused days. PR 1 is a deliberate go/no-go gate.

### PR 1 — Sidecar stand-up + integration spike (go/no-go) · ~1 day

Scope:
- Add a `presenton` service to a compose override (`compose.presenton.yml`, kept
  separate so the base stack is untouched), image `ghcr.io/presenton/presenton`,
  `app_data` volume, env pointing at the shared LLM provider.
- A short `docs/presenton-sidecar.md` runbook: bring it up, create the admin, generate
  an API key, set `PRESENTON_URL` + `PRESENTON_API_KEY`.
- A spike script (committed under `bin/` or `docs/`) that exercises generate → get →
  edit → derive → export with curl/httpx against the running sidecar.

Acceptance / the go/no-go question:
- A deck generates from a brief and exports a valid PPTX, driven only by the API key.
- **Answered in writing:** can the self-hosted editor be opened/framed with an
  acceptable local auth story (section 3 options 1/2)? Record which, and the exact
  `frame-ancestors`/cookie behavior observed.
- If the editor cannot be embedded or opened cleanly, stop here and recommend the
  native plan. Do not proceed to PR 2 on a red spike.

Why first: this is the only genuine unknown. Everything after it is plumbing.

### PR 2 — Backend Presenton client + deck mapping · ~1 day

Scope:
- `chat/presenton_client.py`: httpx client mirroring `docs_client.py` (base URL, API
  key from settings, timeout, instrumentation). Methods: `generate_async`, `status`,
  `get`, `edit`, `derive`, `export_url`.
- Model `ChatPresentationLink` (conversation FK, `presentation_id`, title,
  created/updated) + migration. Version lineage can lean on Presenton `derive` ids;
  store the current id and a parent pointer.
- Settings + env (`PRESENTON_URL`, `PRESENTON_API_KEY`), feature flag
  `FEATURE_FLAG_PRESENTON_SIDECAR` (default off), independent of the native flag.

Acceptance: unit tests with a mocked Presenton (httpx transport stub) cover the client
and the mapping; owner-only access; flag gating. No live Presenton needed in CI.

### PR 3 — Generate tool + deck card · ~1 day

Scope:
- `generate_presentation_sidecar` chat tool (registered under the sidecar flag):
  calls `generate_async`, polls `status` (bounded, with the existing keepalive/stream
  pattern), stores the mapping, returns `ToolReturn` metadata
  `{presentation_id, edit_url, export_url, slide_count}`.
- Frontend deck card in `ToolInvocationItem.tsx` reading that metadata (the
  `TableChart` precedent): title, slide count, **Open editor**, **Download PPTX**.
- Editor opens in an in-app iframe per 3.2 (PR 1 verifies the auth/cookie path).

Acceptance: from chat, a deck is generated, the card renders, the editor opens, the
PPTX downloads. Tool test follows `test_presentation_tool.py` fixtures.

### PR 4 — Comments + rework bridge · ~1.5 days

Scope:
- `PresentationComment` model anchored to slide index (+ optional field), stored in
  Conversations against the mapping; endpoints to add/list/resolve (owner-only).
- A lightweight comment surface in Conversations next to the deck card (list + add).
  The canvas itself stays Presenton's; we do not overlay pins on its iframe for the
  POC (cross-origin pinning is fragile). Comments are slide-level, entered in our UI.
- `revise_presentation_sidecar` tool: reads the **latest** deck via `GET`, takes the
  unresolved comments + instruction, and applies Presenton `edit` (targeted deep-merge)
  or `derive` (new version). Marks included comments resolved. The chat message carries
  `{presentation_id, comments, instruction}` exactly like the native plan.

Acceptance: pin a comment on slide 3, send rework, only slide 3 changes (Presenton's
deep-merge preserves the rest), comment resolved, new version reachable. Manual edits
made in the Presenton editor before rework are respected because the tool re-reads the
live deck.

### PR 5 — Version history + export + polish · ~0.5-1 day

Scope: version list from the derive lineage, "open this version" and export per
version; restore = derive from an older id. Card shows the current version.

Acceptance: generate → edit → rework produces a browsable lineage; any version exports.

### PR 6 — E2E + docs + evaluation note · ~0.5 day

Scope: one Playwright flow (generate → open editor → comment → rework → export) using
the Keycloak e2e users; finalize `docs/presenton-sidecar.md`; write a short comparison
note (sidecar vs native) with the observed auth/embedding behavior, to inform the
keep/drop decision.

Total ~5-6 days. **PRs 1-3 (~3 days) already give a demonstrable generate→edit→export
loop**; PR 4 adds the comment/rework differentiator. If time is tight, PRs 1-3 are a
legitimate minimal POC and PR 4-6 can follow.

## 6. Testing and CI

- Backend: `bin/pytest`; Presenton mocked at the httpx boundary (no live sidecar in
  CI). Follow `test_presentation_tool.py` fixtures and the `feature_flags` fixture.
- The spike (PR 1) is the only part that needs a live Presenton; it is a documented
  manual run, not a CI gate.
- Frontend: vitest for the card and comment surface; one Playwright flow in PR 6.
- Changelog entry per PR (upstream CI gates on it); `make lint`.
- Fork CI noise unchanged: `docker-hub.yml` push fails without `lasuite/*` creds
  (expected), `crowdin_upload.yml` disabled. The compose override is additive, so the
  base `compose.yml` and its CI build are untouched.

## 7. Risks

1. **Self-hosted editor auth (the spike).** Cloud-only scoped tokens are not needed:
   3.2 shows a same-site iframe with `DISABLE_AUTH=true` (loopback-only) or one shared
   login works without v3. Fine for a localhost POC; a real multi-user deployment
   would need SSO work. PR 1 verifies the cookie/auth behavior in target browsers.
2. **Two design systems.** Presenton decks use its HTML/Tailwind templates, not the
   Marianne PPTX template the native pipeline uses. If la suite branding is a hard
   requirement, Presenton templates must be rebuilt to match (it supports custom
   templates from a PPTX, but that is extra work). Flag this early.
3. **Heavier local stack.** Presenton bundles Chromium/Puppeteer for export and its own
   DB; the image is large and generation can be slow on a laptop. Acceptable for a POC;
   note resource needs in the runbook.
4. **Upstream fit.** Unlike the native plan, this introduces an external service
   dependency into a la suite app. It is a fine POC but a harder upstream sell; treat
   it as an experiment that informs the decision, not a foregone merge.
5. **Version drift.** Presenton `edit` mutates in place; use `derive` for anything that
   must be auditable/rollback-able, and always re-read the live deck before rework so
   manual edits are never clobbered.

## 8. Recommendation

Run **PR 1 as a time-boxed spike (~1 day)**. It is cheap and it resolves the only real
unknown. If the editor embeds/opens cleanly with a local auth story and generation
works against the shared provider, continue with PRs 2-4 for a full loop. If not, fall
back to the native plan, which has no such dependency. Either way the comment→agent
bridge design is shared, so effort is not wasted across the two approaches.

## 9. P1 spike outcome (2026-11-12, executed)

Ran in the cloud sandbox: Docker 20.10 + compose v2 installed, image
`ghcr.io/presenton/presenton:v0.9.12-beta` (3.7 GB), provider = Etalab Mistral
(`mistral-medium-3-5`) via `LLM=custom`, `DISABLE_AUTH=true`, loopback-only port.

`bin/presenton-spike` passed every check (~70 s wall clock for a 4-slide deck):

- async generate → status poll → completed; deck of 4 slides returned.
- `edit` deep-merge changed slide 0 only; all other slides byte-identical in content.
- `derive` produced a new presentation id; original verified untouched.
- Both exports downloaded and validated as real PPTX (4 slide parts each).
- Editor page: no `X-Frame-Options`, no CSP `frame-ancestors`.

**Real-browser iframe verification (the no-new-tab requirement):** a host page on
`127.0.0.1:8090` framed `http://localhost:5001/presentation?id=...` in headless
Chrome. The full editor rendered inside the iframe - slide rail, canvas (showing the
title edited via the API), theme panel, Export button. No login screen in
`DISABLE_AUTH` mode. Screenshot and `findings.json` preserved as P1 evidence.

**Go/no-go: GREEN.** Proceed to P2 (backend client + mapping). Notes for later PRs:

- Generation messages stream through status (`Generating presentation outlines`,
  `Generating slides`, `Fetching assets`); the P3 tool can surface them.
- The deck `title` field came back as a long concatenation of cover content; the
  card should prefer a trimmed title or the first slide's title field.
- Sandbox disk is tight with the 3.7 GB image present; teardown (`docker rm -f` +
  `docker rmi`) reclaims it when the POC pauses.

---

Prepared by Dave (Letta Code) on the refreshed fork, 2026-11-12.
