# POC plan: Kimi-style slides loop in Conversations

Status: proposal, 2026-11-12. Branch `poc/slides-loop-plan`, fork `kaaloo/conversations`
(synced to upstream `57386cb`). Runs locally with the existing `docker compose` dev stack;
no new services.

## 1. Goal

Reproduce the Kimi Slides iteration loop inside l'Assistant:

1. Generate a deck from a chat brief.
2. Edit it manually in an in-browser studio.
3. Pin comments on specific slides/fields ("shorten this", "wrong figure").
4. Ask the assistant to rework; it revises **the latest human-edited state**, not its own
   last output.
5. Keep every round as a version; restore any earlier one; export real PPTX.

The POC proves the loop end to end on a laptop. It is not a free-form canvas editor
(no drag/resize of arbitrary shapes); editing is field-level on a fixed set of layouts.
That is a deliberate scope choice, see section 3.

## 2. What upstream already provides (verified at 57386cb)

Refreshing the fork (292 commits, Feb -> Nov 2026) surfaced an existing presentation
pipeline. This is the foundation; the POC extends it rather than replacing it.

| Piece | Location | State |
|---|---|---|
| `generate_presentation` chat tool | `src/backend/chat/tools/generate_presentation.py` | Works; returns a 15-min presigned PPTX link |
| Feature flag (default off) | `src/backend/core/feature_flags/flags.py:47` | `FEATURE_FLAG_PRESENTATION_GENERATION=enabled` |
| Tool registration on the conversation agent | `src/backend/chat/clients/pydantic_ai.py` (`_setup_presentation_tool`) | Global, not per-model |
| `PresentationAgent` (Pydantic AI, structured output) | `src/backend/chat/agents/presentation.py` | Produces a validated `Presentation` spec |
| Deck spec: title + typed slides, Markdown fields | `src/backend/chat/file_generation/entities.py` | 5 layouts: cover, section, 1/2/3 columns; `slide_notes` everywhere |
| Markdown -> PPTX renderer + template builder | `src/backend/chat/file_generation/{renderer,builder}.py`, `templates/generic.pptx` | Marianne template; `check_template` test guards bindings |
| Tool metadata -> custom UI precedent | `pydantic_ui_message_converter.py` (chart metadata), `ToolInvocationItem.tsx` (`TableChart`) | Exactly the pattern a deck card needs |
| "Edit in Docs" interop | `src/backend/chat/docs_client.py`, `docs/interoperabilities.md` | Creates a Docs document as the user via OIDC; one-way, no link back |
| Local dev stack | `compose.yml`, `Makefile` (`make bootstrap`) | postgres, redis, rustfs, Keycloak, nginx, backend :8071, Vite frontend :3000 |

What is missing for the Kimi loop:

- **Persistence.** Decks are ephemeral: no DB row, object stored under
  `<conversation>/generated/` (a prefix meant to be lifecycle-pruned), reachable only
  via a short-lived URL. Nothing survives the link expiry.
- **Editable preview.** The user only gets a download link; no in-browser view.
- **Annotations.** No comments, no anchoring.
- **Rework.** No revision tool; the agent cannot see or modify an existing deck.
- **Versioning.** No history, no rollback.

## 3. Architecture decision

**Native, spec-driven studio inside Conversations.** The `Presentation` spec is already
the structured deck model that both the LLM and a renderer can read/write - the hardest
design decision is made upstream. A React preview of five fixed layouts is small, and
the existing builder remains the export source of truth.

Rejected for the POC:

- **Presenton sidecar** (Apache-2.0, full canvas editor + MCP/API). Strong product, but it
  adds a second app, DB and auth surface to the compose stack, duplicates the existing
  generation pipeline, and its editing model (HTML/Tailwind templates) diverges from the
  Marianne PPTX template. Revisit only if free-form canvas editing becomes a requirement.
- **ONLYOFFICE / Collabora embed.** Real office fidelity and native comments, but the
  agent integration is file-level and coarse; wiring comments to the assistant needs
  plugin work, and the stack is heavy for a laptop POC.
- **tldraw / Univer Slides.** Not open source (production license keys / commercial
  plugins).

Tradeoff accepted: no pixel-level design freedom. Field-level Markdown editing on fixed
layouts covers the iteration loop, which is what the POC must prove. The annotation ->
agent context bridge (section 6.3) is the genuinely novel piece; no OSS component ships
it complete.

Upstreamability: keep everything additive and behind the existing feature flag so this
can become an upstream PR. The presentations feature is actively developed upstream
(`docs/presentations.md`); coordinate with the la suite team before investing beyond M2.

## 4. Data model

Three models in the `chat` app (next migration: `0017_...`):

```text
ChatPresentation
  id: UUID
  conversation: FK ChatConversation (owner-scoped access)
  title: str
  created_at / updated_at

PresentationVersion
  presentation: FK ChatPresentation
  number: int (1-based, append-only)
  spec: JSONField          # validated Presentation.model_dump()
  storage_key: str         # PPTX blob, see below
  source: enum generated | manual | rework | restore
  parent: FK self (null for v1)
  created_by: FK User (null when agent-produced)
  created_at

PresentationComment
  version: FK PresentationVersion   # pinned against the version the user saw
  slide_index: int
  field: str | null                 # null = whole slide
  body: text
  author: FK User
  resolved: bool (default false)
  resolved_in: FK PresentationVersion (null)
  created_at
```

Notes:

- Comments anchor to **slide index + field name**, not pixel coordinates. Field anchors
  survive re-layout and are trivially serializable into the rework prompt. Free-region
  annotation (Kimi allows it) is deferred.
- A comment pinned on v2 stays readable when v3 exists; the studio shows it as
  "on v2" if the anchor moved. Resolution records which version addressed it.
- Storage: `<conversation>/presentations/<presentation_id>/v<n>.pptx` under
  `default_storage`. **Not** the `generated/` prefix - that one is meant to be pruned by
  a bucket lifecycle rule (see the comment in `generate_presentation.py`). Studio decks
  are durable artifacts.
- Restore = append a new version copying an old spec (`source=restore`). Linear history,
  no destructive operation.

## 5. Backend changes

### 5.1 Persist on generation

Modify `generate_presentation` (keep its signature and the presigned-link return for
compatibility):

1. After `PresentationAgent().run(brief)`, create `ChatPresentation` + v1
   (`source=generated`), store the PPTX blob at the durable key.
2. Extend `ToolReturn.metadata` with `presentation_id`, `version`, `slide_count`
   alongside the existing `url`. The frontend card reads this (chart-metadata precedent).

### 5.2 Revision tool: `revise_presentation`

New `src/backend/chat/tools/revise_presentation.py`, registered next to
`generate_presentation` under the same flag.

```python
revise_presentation(presentation_id: str, instruction: str) -> ToolReturn
```

Contract (the crux of the loop):

1. Load the **latest** version's spec (including manual edits) and all unresolved
   comments. Never revise from the agent's own previous output.
2. Determine target slides: union of comment anchors; if the instruction is structural
   ("merge slides 3 and 4", "add a section"), fall back to full-deck mode.
3. **Targeted mode (default):** a revision agent variant outputs only the targeted
   slides (`list[{index, Slide}]`, same Pydantic validation). The service merges them
   into a copy of the current spec. Untouched slides are preserved **by construction**,
   not by prompt discipline - this is the deterministic guard against drift.
4. **Full-deck mode:** reuse `PresentationAgent` with the current spec + comments +
   instruction as context; output is a complete `Presentation`.
5. Validate the merged spec (cover-first etc.), append a version (`source=rework`),
   mark the included comments `resolved` with `resolved_in`, rebuild the PPTX, return
   metadata like generation.

Prompt inputs: current spec JSON, unresolved comments rendered as
`slide 3, field "content": <body>`, and the user instruction. Prompt rules: keep
untouched content verbatim, write in the deck's language, respect the layout field
contract (already in `PRESENTATION_SYSTEM_PROMPT`).

### 5.3 REST endpoints

Follow the `edit-in-docs` action precedent on the chat viewset
(`fetchAPI('chats/{id}/...')` on the frontend). Owner-only permissions, same as the
conversation.

```text
GET  chats/{cid}/presentations/                  list decks of the conversation
GET  presentations/{id}/                         spec of latest version + versions + comments
PUT  presentations/{id}/spec/                    full-spec manual edit -> new version (source=manual)
POST presentations/{id}/comments/                {slide_index, field?, body}
POST presentations/{id}/comments/{cid}/resolve/  manual resolve
POST presentations/{id}/restore/                 {version_number} -> append restore version
GET  presentations/{id}/export/                  presigned URL of the latest version's PPTX
```

Manual edit takes the **full spec** (the studio owns the current state), server-side
validated with the same `Presentation` model. Simpler than per-field PATCH and avoids
partial-update races; the version row records `source=manual`.

### 5.4 Chat bridge

No new chat protocol. The studio's "Rework with assistant" button composes a normal user
message carrying the deck reference and the unresolved comments, e.g.:

```text
Rework presentation <presentation_id> (currently v3):
- slide 3, content: "shorten to 3 bullets"
- slide 5: "replace the example with 2025 figures"
Instruction: keep the tone formal.
```

The agent calls `revise_presentation` with the id; the tool loads state server-side, so
the message text is a pointer, not the source of truth. This keeps the chat thread as the
single conversation (Kimi's model) and needs zero changes to the streaming protocol.

## 6. Frontend changes

Stack: React 19 + Vite, zustand, react-markdown/remark-gfm (all present). Follow existing
feature-folder structure (`features/sources-panel/` is the panel precedent).

### 6.1 Deck card in chat

`ToolInvocationItem.tsx`: special-case `generate_presentation` / `revise_presentation`
metadata (exactly how `TableChart` reads `metadata.chart`). Render `PresentationCard`:
title, slide count, version badge, **Open studio**, **Download PPTX**. The card replaces
the bare link for these tools; the link stays in the message for non-studio clients.

### 6.2 Presentation studio

New `features/presentation-studio/`, opened from the card as a full-height panel/modal:

- **Slide rail**: thumbnails (scaled renders), click to select, version badge.
- **Slide preview**: five React layout components mirroring `generic.pptx`
  (Marianne / DSFR palette #000091), Markdown fields rendered with the existing
  react-markdown setup. The preview approximates the PPTX; the builder remains the
  export source of truth.
- **Field editing**: click a field -> Markdown textarea -> save calls `PUT .../spec/`,
  version increments, rail refreshes.
- **Comment mode**: toggle; click a slide or field -> composer; pins render as badges;
  unresolved comments listed in a side tray with their anchors.
- **Version history**: dropdown of versions (source badge: generated/manual/rework/
  restore), view any version read-only, **Restore**.
- **Rework with assistant**: instruction box + unresolved-comments summary; composes the
  chat message (5.4), closes the studio, focuses the chat input. The rework runs as a
  normal agent turn; the new card appears in the thread.
- **Export**: presigned URL from `GET .../export/`.

### 6.3 State

zustand store for the open presentation (id, latest spec, versions, comments, editing
state), fetched via the `fetchAPI` hook pattern (`useEditInDocs.tsx` is the template).
Refetch on version change; no websocket needed for the POC (single user).

## 7. Running locally

Everything below uses the existing stack; no compose changes.

```bash
git clone git@github.com:kaaloo/conversations.git && cd conversations
make bootstrap        # env files from .dist, image builds, migrate, demo data, run
```

First build is long (backend + frontend images). Then:

1. **LLM provider** - edit `env.d/development/common` (gitignored copy of `.dist`):

   ```ini
   # Sovereign option (proven with pydantic-ai in the KIWI investigation):
   AI_BASE_URL=https://api.mistral.etalab.gouv.fr/v1
   AI_MODEL=mistral-medium-3-5
   AI_API_KEY=<your Etalab console key>

   # Offline option (compose already maps host.docker.internal):
   # AI_BASE_URL=http://host.docker.internal:11434/v1
   # AI_MODEL=<your local model>
   # AI_API_KEY=ollama
   ```

   The default provider in `conversations/configuration/llm/default.json` is
   OpenAI-compatible and reads these settings; no code change. Any OpenAI-compatible
   endpoint works (Albert included).

2. **Enable the tool**: add `FEATURE_FLAG_PRESENTATION_GENERATION=enabled` to the same
   env file, restart `app-dev`.
3. Open http://localhost:3000, log in via Keycloak with `conversations` /
   `conversations` (dev realm user). Backend API: :8071, Keycloak: :8083.
4. Smoke test (M0 acceptance): ask "Prepare a 6-slide deck on X for Y" -> the agent calls
   `generate_presentation` -> download link works and the PPTX opens.

Fork maintenance: re-sync before each milestone
(`git fetch upstream main && git merge --ff-only upstream/main && git push origin main`).
The GitHub `merge-upstream` API returned 404 on this fork; the git fast-forward is the
verified route. The fork has no local commits, so syncs stay trivial until POC work
lands - keep POC work on feature branches.

## 8. Milestones

Each milestone is independently demoable. Estimates are rough focused days.

| # | Scope | Acceptance criteria | Est. |
|---|---|---|---|
| M0 | Baseline: bootstrap + flag + provider | Deck generated from chat, PPTX downloads and opens; `bin/pytest` green on the fork | 0.5 |
| M1 | Persistence + deck card | Models + migration; generation persists v1; card renders from tool metadata; deck survives reload and link expiry | 1 |
| M2 | Studio preview + manual edit | Five layouts render; field edit -> v2 (source=manual); export reflects the edit | 1.5 |
| M3 | Comments + rework | Pin a comment on slide 3, send rework message; only slide 3 changes (untouched slides byte-identical in spec), comment resolved, v3 created; manual edits made before rework are respected | 2 |
| M4 | History + restore + polish + e2e | Version list, restore v1 as v4, export matches; one Playwright flow generate->edit->comment->rework->export | 1 |

Total ~6 days. M3 is the proof point: if the loop feels right there, the rest is polish.

## 9. Testing and CI

- **Backend**: `bin/pytest` (runs in `app-test` with `env.d/test`, never inherits dev
  settings). Follow `test_presentation_tool.py` fixtures (`feature_flags`, minimal
  `LLM_CONFIGURATIONS`). New tests:
  - version append/restore invariants; comment anchoring and resolution;
  - revision merge: targeted mode preserves non-targeted slides exactly (mutation-check
    this test - it is the anti-drift guard);
  - endpoints: owner-only access, spec validation rejects bad layouts/cover order;
  - generation still returns the presigned link (compat).
- **Frontend**: vitest component tests next to the code (existing `__tests__` pattern):
  card rendering from metadata, field edit round-trip, comment composer, version switch.
- **E2E (M4)**: one flow in `apps/e2e` (Playwright, Keycloak e2e users exist in the realm).
- **Lint**: `make lint` (ruff format/check, pylint); frontend eslint per repo config.
- **Changelog**: upstream CI gates PRs on a `CHANGELOG.md` entry (Keep a Changelog
  format, emoji-prefixed lines, <= 80 cols). One entry per implementation PR.
- **Fork CI noise**: `docker-hub.yml` pushes to `lasuite/*` and will fail on the fork
  without those credentials (expected, same as the DGAFP fork); `crowdin_upload.yml`
  needs secrets - disable it in the fork's Actions settings. PR-triggered builds still
  give real Dockerfile/trivy signal.

## 10. Risks and open questions

1. **Structured-output reliability on the chosen model.** Generation already depends on
   it upstream; revision adds a second structured call. Pydantic AI retries help;
   mistral-medium-3-5 is proven with this stack. If a local model struggles, targeted
   mode (fewer slides per call) is the mitigation.
2. **Preview vs PPTX fidelity.** The React preview approximates the Marianne layouts.
   Accept for the POC; export is authoritative. If fidelity becomes a complaint, render
   thumbnails from the actual PPTX (LibreOffice headless) instead - deferred.
3. **Comment anchors across structural reworks.** Full-deck mode can renumber slides;
   unresolved comments pinned to old indices are shown as "on vN" rather than silently
   re-anchored. Decide during M3 whether the revision agent should also return an
   anchor-mapping; POC default is the honest stale-anchor display.
4. **Upstream overlap.** The la suite team owns this feature area and ships fast (the
   fork just absorbed 292 commits). Keep changes additive + flag-gated; sync before each
   milestone; raise the studio idea upstream early (an issue on
   `suitenumerique/conversations` describing the loop) so effort is not duplicated.
5. **No public exposure.** Localhost compose only; the studio endpoints inherit
   conversation auth. Nothing here is deployed publicly (abuse-protection rule applies
   before any exposure).

## 11. Deferred (explicitly out of POC scope)

- Free-form canvas (drag/resize, shapes, charts as native objects) -> Presenton
  reconsideration trigger.
- Free-region pixel annotations; multi-user co-editing of decks (Yjs/Docs route).
- "Open deck in Docs" (markdown + `---` presenter mode, native Docs comments). The
  interop client exists (`docs_client.py`), but Docs comments do not flow back into
  Conversations; that return path is a second POC, not this one.
- Deck templates beyond `generic.pptx`; image generation inside slides.

---

Prepared by Dave (Letta Code) on the refreshed fork, 2026-11-12.
