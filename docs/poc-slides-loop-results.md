# Slides-loop POC: results and sidecar-vs-native evaluation

Status: POC complete (P1-P6), 2026-11-12. Companion to
`poc-presenton-sidecar-plan.md` (the chosen sidecar approach) and
`poc-slides-studio-plan.md` (the native alternative). This note records what
was built, what the build revealed, and the recommendation.

## 1. What was built

A Kimi-style deck iteration loop inside Conversations, driven by a Presenton
sidecar:

1. **Generate** — `generate_presentation_sidecar` tool runs Presenton's async
   generation, links the deck to the conversation, and renders an in-chat deck
   card. The editor opens **inline (iframe), not a new tab**.
2. **Edit** — the embedded Presenton canvas editor; manual edits are not
   recorded as versions (a documented limitation).
3. **Comment** — slide-anchored comments (slide index + optional field) stored
   in Conversations, owner-scoped endpoints.
4. **Rework** — `revise_presentation_sidecar` reads the live deck, applies each
   unresolved comment via Presenton's AI slide edit, marks them resolved, and
   snapshots a new version. Defaults to the conversation's latest deck so the
   model never needs the UUID (which lives only in tool metadata).
5. **Version history** — Conversations keeps its own snapshots (Presenton
   mutates in place); list, restore, and fresh export.

All behind the `presenton_sidecar` feature flag (default off).

## 2. What the build revealed

These are the things that were not evident from the plan and only surfaced
during implementation and review:

- **The self-hosted v1 API is deep-merge only.** `/edit` applies
  `deep_update()` to slide content; there is no replacement operation and no
  way to remove slides via the API. Consequence: **restore is a merge, not a
  byte-for-byte rollback** — slides and content keys added after a snapshot
  are kept. The restore endpoint now always surfaces this as a note.
- **Slide edits assign a new UUID every time.** Presenton returns the updated
  slide with a fresh id; a second comment on the same slide must target the
  replacement id or it 404s. The rework tool tracks it.
- **Edits commit immediately.** A later comment's failure must not un-resolve
  earlier successful comments (a retry would compound non-idempotent changes),
  and the partial rework must still be snapshotted. Both are handled.
- **Tool metadata is not model-visible.** Pydantic AI does not send
  `ToolReturn.metadata` to the LLM, so the deck UUID had to be made optional
  (default to the latest deck) rather than required.
- **The browser and backend reach the sidecar differently.** Compose service
  name vs published loopback port; the client keeps two base URLs
  (`PRESENTON_BASE_URL`, `PRESENTON_BROWSER_BASE_URL`).
- **Feature-flag env values are enum names.** `FeatureToggle[...]` resolves
  `ENABLED`, not `enabled`; the compose default had to use the uppercase name.
- **v3 stays cloud-only.** Confirmed again: the self-hosted image ships v1/v2
  only; the scoped-token embed (`/presentation/integrate`) is Cloud v3. The
  inline iframe works without it because the sidecar runs single-user
  (`DISABLE_AUTH`) on loopback and sets no framing headers.

## 3. Sidecar vs native — evaluation

| Criterion | Presenton sidecar (built) | Native studio (alternative) |
|---|---|---|
| Editor richness | Full canvas (shapes, charts, themes) — reused | Field-level Markdown editor we build |
| New services | Presenton container (Chromium, own DB, ~3.7 GB image) | None |
| Net new code | API client + mapping + embed + comment/version bridge | Studio UI + models + revision tool |
| Export fidelity | Presenton PPTX (its design system) | python-pptx + Marianne template (upstream) |
| Restore semantics | Merge only (v1 API limit) — cannot remove added content | Full control (we own the spec) — exact rollback |
| Versioning | We snapshot around an opaque mutable deck | We own the spec — trivial exact versions |
| Upstream fit | Introduces an external dependency | Additive to an existing upstream feature |
| Auth posture | Single-user `DISABLE_AUTH` on loopback for the POC | Inherits Conversations auth |
| Branding | Presenton templates; Marianne needs rework | Marianne template already upstream |

### Recommendation

The sidecar POC **proved the loop works end to end** and delivered a far richer
editor than we could build quickly. But the build exposed structural costs:
an opaque, mutable deck we must snapshot around; a deep-merge-only API that
makes true restore impossible; a heavy extra service; and a single-user auth
posture that does not generalize to multi-user deployment without SSO work.

For a **production** feature in la suite, the **native studio** is the better
fit: we own the deck spec, so versioning and exact restore are trivial, there
is no new service, it inherits Conversations auth, and it reuses the upstream
Marianne export. The sidecar is the right call for a **fast, rich-editor
prototype** and as a reference for the editor UX, but its API limitations
(merge-only restore, mutable deck) are inherent, not incidental.

If the sidecar route is pursued further, the prerequisites are: a replacement
-capable edit endpoint upstream (or direct deck-spec access), multi-user auth
(SSO into Presenton), and Marianne-compatible templates.

## 4. Verification

- Backend: full suite green under xdist (CI mode), including the sidecar
  client, generate/rework tools, comment and version endpoints, and the
  version-recording helper.
- Frontend: full vitest suite green; tsc/eslint/prettier clean. Deck card,
  comments panel, versions panel, and fresh-export download all covered.
- Live spike (P1): generate → edit → derive → export against Etalab Mistral,
  and the editor verified rendering inside a cross-origin iframe.
- Each PR reviewed by Codex; findings addressed and re-reviewed before merge.

## 5. Running it

See `presenton-sidecar.md` for the sidecar runbook (compose overlay, env,
security posture) and `poc-presenton-sidecar-plan.md` for the original plan.
