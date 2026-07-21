# Switching Chat + Embeddings from Grok to Gemini — Plan

Status: **Implemented, awaiting a real Gemini API key to live-verify.**

- Phase 1 (chat): `.env` updated (`ARYX_LLM_PROVIDER=gemini`, base URL, model
  names) — no code changes needed, per §3. `ARYX_LLM_API_KEY` is a
  placeholder (`REPLACE_WITH_YOUR_GEMINI_API_KEY`) pending your key.
- Phase 2 (embeddings): implemented — `Broker._gemini_embed()`
  (`src/aryx/broker/__init__.py`), `embed()` dispatch extended, config
  descriptions updated, `.env` sets `ARYX_EMBED_BACKEND=gemini`, backfill
  script at `scripts/reembed_gemini.py`, unit tests in
  `tests/test_broker_gemini_embed.py` (5/5 passing, mocked HTTP — no real
  Gemini calls made yet).
- **Not yet done:** the container has NOT been rebuilt/restarted (would
  break the currently-working Grok setup with a placeholder key), and the
  backfill script has NOT been run against real data. Both need your real
  API key first — see §8.

## 1. Where things stand today (verified against the actual code, not assumed)

Two completely separate subsystems, with very different amounts of work ahead:

| | Chat (menial + answer roles, extraction, rules) | Embeddings |
|---|---|---|
| Current provider | Grok (`ARYX_LLM_PROVIDER=openai`, `ARYX_LLM_BASE_URL=https://api.x.ai/v1`, `.env`) | Ollama `nomic-embed-text`, 768-dim (`docker-compose.yml`, `broker/catalog.json`) |
| Code path | `src/aryx/llm.py` — anything other than `"anthropic"`/`"ollama"` falls through to a generic **OpenAI-compatible `/chat/completions` caller** (`openai_json`/`complete_text`, `src/aryx/llm_providers.py`) | `src/aryx/broker/__init__.py`'s `Broker.embed()` — hardcoded to exactly two backends: `_ollama_embed` (native Ollama `/api/embed`) and `_oci_embed` (OCI GenAI Cohere) |
| Gemini support | **Already designed in** — `discover_openai_compatible`'s own docstring: *"Works for xAI (Grok), Google (Gemini OpenAI-compat), OpenRouter, vLLM..."* (`broker/discovery.py:58`) | **Does not exist.** Gemini's embedding API (`:embedContent`/`:batchEmbedContents`) is not OpenAI-compatible — it's Google's own wire protocol, with the API key as a query param, not a Bearer header. No third branch in `embed()` today. |

## 2. This isn't the first time — Gemini was already run here once

`git log` shows a real Gemini deployment earlier in this project's history (commits `8773c1e` → `1497a42` → `b46c841` → `8d84d7e` → `4fa0d93` → `50bec38`, all pre-dating the current Grok config):

- `8773c1e` opened the broker to any OpenAI-compatible provider specifically to support Grok **and** Gemini interchangeably.
- `b46c841` fixed `docker-compose.yml` hardcoding `ARYX_LLM_BASE_URL=http://ollama:11434` (it now uses `${VAR:-default}` so `.env` wins) and made `llm_runtime` actually read `ARYX_LLM_API_KEY` — *"gives the entire pipeline — Ask + doc ingest — Gemini Flash quality without any UI change required."*
- Two REAL Gemini-specific bugs were hit and fixed live:
  - `8d84d7e`: Gemini's JSON mode often returns a **bare list** where the schema declares `{"mentions": [...]}` — Ollama/others return the wrapped envelope; Gemini frequently doesn't.
  - `4fa0d93`: Gemini's JSON mode **does not enforce `required` schema fields** — mentions could arrive missing `span`, causing `KeyError`s that killed extraction.
- `50bec38` **consolidated both fixes into `src/aryx/llm_normalize.py`** — a permanent, provider-agnostic JSON normalizer (envelope coercion + synonym field renaming) that every `complete_json()` caller already passes through today. Its own docstring: *"To switch to ChatGPT/Claude/anything else: edit `.env`, restart container. Zero code touches."*

**This means the chat-side Gemini quirks are already handled by code sitting in the repo right now.** This migration is not walking into unknown territory — it's re-enabling a path that was built, used, hit real bugs, and had those bugs fixed into a general-purpose normalizer.

One explicit prior decision to be aware of: `1497a42`'s commit message states *"Embed model stays on local Ollama (nomic-embed-text) — text similarity is provider-agnostic for now."* The team deliberately did NOT move embeddings to match the chat provider last time. This plan's embedding half is new work beyond that precedent, per today's ask.

## 3. Part A — Chat (menial + answer roles): config-only, no code changes expected

This covers everything `llm_runtime.chat()` drives (`ask_api.py`'s CPQ turns, Q&A, summary narration) and everything `aryx.llm.complete_text`/`complete_json` drive elsewhere (entity extraction, relationship inference, schema discovery — all already routed through `llm_normalize.normalize()`).

### 3.1 Get a Gemini API key + confirm the OpenAI-compat endpoint

Google's OpenAI-compatible endpoint: `https://generativelanguage.googleapis.com/v1beta/openai/`. Confirm current Gemini model names for the two roles — likely:
- **menial** (cheap/fast, high volume): `gemini-2.5-flash` or `gemini-2.0-flash`
- **answer** (reasoning-tier, customer-facing narration): `gemini-2.5-pro`

### 3.2 Update `.env` (and `.env.example` stays as-is — it already documents `gemini` as a supported value)

```bash
ARYX_LLM_PROVIDER=gemini            # was: openai (label only — anything but "anthropic"/"ollama" hits the generic path)
ARYX_LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
ARYX_LLM_MENIAL_MODEL=gemini-2.5-flash    # was: grok-3-mini
ARYX_LLM_REASON_MODEL=gemini-2.5-pro      # was: grok-3
ARYX_LLM_API_KEY=<Gemini API key>          # was: xAI key
ARYX_LLM_TIMEOUT=900                       # keep, or re-tune after latency testing
```

### 3.3 Rebuild/restart

`docker-compose.yml`/`docker-compose.local.yml` already pass all five vars through with `${VAR:-default}` substitution (fixed by `b46c841`) — recreating the `api` container picks up the new values with **zero code changes**. `llm_runtime.set_config()` also means this is hot-swappable from the Settings panel without a restart at all, if that path is preferred.

### 3.4 What to verify live before calling this done (not assume)

- **`complete_text` path** (`ask_api.py` CPQ summary narration, Q&A): plain-text completions — lowest risk, no schema to violate.
- **`complete_json` path** (entity extraction, relationship inference, schema discovery): confirm `llm_normalize.normalize()` still catches whatever shape/field quirks *current* Gemini models produce — the fixes were written against whatever Gemini model was live in ~June 2026; today's `gemini-2.5-*` models may behave slightly differently. Re-run a real extraction against a real document and check for `KeyError`/shape mismatches in logs, the same way `8d84d7e`/`4fa0d93` were originally diagnosed.
- **Rate limits / quota**: Gemini's free/paid tier request-per-minute limits differ from xAI's — check under the ingestion pipeline's real concurrency (`ARYX_DOC_WORKERS`), not just a single Ask turn.
- **Latency**: `usage.latency_ms` is hardcoded to `0` today (a separate, already-known gap — see `docs/CPQ_LIVE_PROGRESS_HINTS_PLAN.md` §7) — no automatic before/after comparison exists; time a handful of real turns manually.

## 4. Part B — Embeddings: real code work, plus a data-migration decision

### 4.1 Why this is not a config change

`Broker.embed()` only ever calls `_ollama_embed` or `_oci_embed` (`broker/__init__.py:113-114`) — there is no generic/OpenAI-compatible embed path to piggyback on, because Gemini's embedding API isn't OpenAI-compatible. Setting `ARYX_EMBED_MODEL`/`ARYX_EMBED_ENDPOINT` to Gemini values today would just point `_ollama_embed`'s Ollama-shaped request (`POST {endpoint}/api/embed`) at a URL that doesn't speak that protocol — it would fail outright, not silently misbehave.

### 4.2 New code required

1. **`src/aryx/broker/__init__.py`** — add a `_gemini_embed(texts, settings)` method alongside `_ollama_embed`/`_oci_embed`:
   - Endpoint: `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents?key={api_key}`
   - Body shape differs from Ollama's: `{"requests": [{"model": "models/{model}", "content": {"parts": [{"text": t}]}} for t in texts]}`
   - Response: `{"embeddings": [{"values": [...]}, ...]}` — note the extra nesting (`values`, not a bare list) vs. Ollama's flat `embeddings: [[...], ...]`.
2. **`src/aryx/config.py`** — extend `embed_backend`'s allowed values / docstring to include `"gemini"`, and `effective_embed_backend()`'s `_resolve()` call sites accordingly (currently a strict `"local"`/`"oci"` binary).
3. **`Broker.embed()`** dispatch — add the third branch.
4. **New env vars**: `ARYX_EMBED_BACKEND=gemini`, reuse `ARYX_LLM_API_KEY` (one Gemini key covers both chat and embeddings) or add a dedicated `ARYX_GEMINI_EMBED_MODEL` (e.g. `text-embedding-004` or `gemini-embedding-001`).

### 4.3 The real blocker: vector dimension is baked into the schema

`src/aryx/store/migrations/0006_documents.sql:35` — `embedding vector(768)`, a fixed-width pgvector column. Only **one** table has this column and only **three** call sites use `broker.embed()` at all (`cli.py`, `pipeline/embed.py`, `resolution/run.py`) — a small, well-scoped surface, but the dimension constraint is real:

- Ollama's `nomic-embed-text` → 768-dim (matches the column as-is).
- OCI's `cohere.embed-multilingual-v3.0` → 1024-dim (already a mismatch if that path is ever live simultaneously — out of scope here).
- Gemini `text-embedding-004` → 768-dim **by default** (configurable via `output_dimensionality`, matches without a migration).
- Gemini `gemini-embedding-001` (newer, generally better quality) → 3072-dim **by default**, but explicitly supports `output_dimensionality: 768` to truncate to match — **must be set explicitly**, verify it isn't silently defaulting to 3072 in testing.

**Two paths:**
- **(A) Pin `output_dimensionality=768`** on whichever Gemini embed model is chosen — no schema migration, but every embedding must be **re-generated** (old Ollama vectors and new Gemini vectors are not comparable even at the same dimension — different model, different semantic space). Existing rows in `documents.embedding` need a backfill job re-running `broker.embed()` over all existing content.
- **(B) Widen the column** (new migration, `vector(3072)` or provider-max) to use Gemini's native dimension without truncation — same re-embed requirement, plus an actual schema migration and an index rebuild (pgvector's ivfflat/hnsw indexes are dimension-locked too, if one exists on this column — confirm before choosing this path).

Recommend **(A)** unless there's a specific quality reason to want the untruncated embedding — it avoids a schema migration and keeps the blast radius to "re-run the embed backfill," not "alter a live table + rebuild an index."

### 4.4 Re-embed backfill

`scripts/reembed_gemini.py` — iterates `aryx_chunk` rows not yet embedded under the target Gemini `model_id`, calls the new `_gemini_embed` path, and writes via the existing `ChunkStore.save_embeddings()`. Safer than a straight overwrite: `aryx_chunk_embedding` has `UNIQUE (chunk_id, model_id)` with `ON CONFLICT DO NOTHING` (`insert_chunk_embedding.sql`), so Gemini rows land ALONGSIDE the existing `nomic-embed-text` rows rather than destroying them — old and new coexist until you explicitly delete the old ones once satisfied.

One catch found while implementing this: `ChunkStore.check_embed_compat()` (a fail-closed startup guard) runs `SELECT DISTINCT model_id, dim ... LIMIT 1` — with two model_ids coexisting across different chunks, which row that returns is non-deterministic, so this becomes an all-or-nothing cutover in practice, not a gradual rollout. The script logs a reminder to run `DELETE FROM aryx_chunk_embedding WHERE model_id != '<gemini-model>'` once Gemini embeddings are verified — a deliberate manual step, not automated.

Run with `--dry-run` first to get a real count of unembedded rows before committing to the real batch.

## 5. Phasing recommendation

1. **Phase 1 — Chat only** (§3): low risk, mostly de-risked by prior history, no schema/data migration. Ship and live-verify independently first.
2. **Phase 2 — Embeddings** (§4): real new code + a data backfill decision. Do NOT bundle with Phase 1 — if something regresses, you want to know which half caused it.

## 6. Rollback

Both phases are env-var/config-gated (`ARYX_LLM_PROVIDER`, `ARYX_EMBED_BACKEND`) — reverting to Grok/Ollama is flipping the same variables back and rebuilding, no code to revert for Phase 1. Phase 2's rollback additionally requires either keeping the old Ollama-embedded vectors untouched until Gemini embeddings are verified (don't overwrite in place; write to a new column or table first) or being prepared to re-run the backfill against Ollama again if Gemini embeddings prove lower quality in practice.

## 7. Open questions for you

- Confirm exact Gemini model names to target (menial/answer/embed) — the ones above are best-guess current-generation names, not verified against your actual Gemini API access/quota tier.
- Phase 2: pin `output_dimensionality=768` (path A, **implemented**) or widen the column (path B, not built)?
- Is a dedicated Gemini API key wanted (separate billing/quota from a shared key), or reuse one key for both chat and embeddings? **Implemented as reuse** — `_gemini_embed` reads the same `ARYX_LLM_API_KEY` as chat.

## 8. Implementation status / how to finish this

**Done:**
- `.env`: `ARYX_LLM_PROVIDER/BASE_URL/MENIAL_MODEL/REASON_MODEL` set to Gemini; `ARYX_EMBED_BACKEND=gemini` added.
- `src/aryx/broker/__init__.py`: `_gemini_embed()` implemented (path A, 768-dim pinned, reuses `ARYX_LLM_API_KEY`, routed through `post_json` for 429 retry + no URL-in-logs), `embed()` dispatch extended.
- `src/aryx/config.py`: `embed_backend`/`embed_model_override` descriptions document the new value.
- `.env.example`: documents `ARYX_EMBED_BACKEND=gemini` for future setup.
- `scripts/reembed_gemini.py`: backfill script, `--dry-run` supported, refuses to run unless `ARYX_EMBED_BACKEND=gemini` is actually set.
- `tests/test_broker_gemini_embed.py`: 5 tests, all passing (mocked HTTP, no real Gemini calls made).

**Not done — needs you:**
1. Put a real Gemini API key into `.env`'s `ARYX_LLM_API_KEY` (currently `REPLACE_WITH_YOUR_GEMINI_API_KEY`).
2. Rebuild/restart `aryx-api-1` — not done yet, to avoid breaking the currently-working Grok setup with a placeholder key.
3. Live-verify chat (§3.4) and a real extraction call.
4. Run `scripts/reembed_gemini.py --dry-run` to see how many chunks need backfilling, then run it for real.
5. Spot-check Gemini-embedded similarity/resolution quality before deleting the old `nomic-embed-text` rows (script logs the exact `DELETE` statement when ready).
