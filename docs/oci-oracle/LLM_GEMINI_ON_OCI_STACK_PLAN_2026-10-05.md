# Use Gemini on the OCI stack (match dev-rv-msi) — Plan (2026-10-05)

**Status: compose change applied (default behaviour unchanged); the switch itself is a `.env` change and has not been run. Nothing here was tested against a live Gemini endpoint or the running stack (Docker was unresponsive when this was written).**

## 1. Current state

| Use | Model today | Source |
|---|---|---|
| Cheap and frontier chat tiers (OCI stack) | `cohere.command-a-03-2025` via OCI GenAI | `docker-compose-oci-local.yml` (LLM models block), `ARYX_LLM_CHEAP_BACKEND=oci`, `ARYX_LLM_FRONTIER_BACKEND=oci` |
| Embeddings | `cohere.embed-multilingual-v3.0`, 1024 dimensions | same file, `ARYX_EMBED_BACKEND=oci`, `ARYX_EMBED_DIM` |
| CPQ intent gateway | pinned `gemini-2.5-pro`, but see 3.3 | `config_cpq_intent.py:122` |
| Code defaults if nothing overrides | provider `ollama`, `llama3.2:3b` | `config_llm.py` |
| Tier-2 BML evaluation with an LLM | off | `bml_use_llm=false` |

The effective values can differ from the compose defaults because `.env` overrides them. `.env` was not read.

## 2. What dev-rv-msi does (branch `stagging-dev-rv-msi`, `2f7dd7c`)

- Chat on Gemini through Google's OpenAI-compatible endpoint, configured in `.env` (its compose files do not set Gemini): `ARYX_LLM_PROVIDER=gemini`, `ARYX_LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/`, menial `gemini-3.5-flash`, reason `gemini-2.5-pro`, `ARYX_LLM_API_KEY`.
- Embeddings optionally on Gemini (`ARYX_EMBED_BACKEND=gemini`, `gemini-embedding-2` pinned to 768 dimensions) with `scripts/reembed_gemini.py`.
- Source: `docs/LLM_GEMINI_MIGRATION_PLAN.md` (identical in `dev_oci`). The model names there are described as best guesses, not verified against the account's API access.

## 3. Comparison with dev_oci

### 3.1 Already the same
`broker/specs.py`, `broker/discovery.py` and `llm_normalize.py` have no differences. The Gemini embed path (`broker/embed_backends.py`), `scripts/reembed_gemini.py` and the routing rule (a tier goes to OCI only when its backend setting is `oci`) exist in both. The remaining differences in `llm_providers` and `intent_gateway` come from the file split in the style-compliance refactor.

### 3.2 What blocks Gemini on dev_oci
1. The LLM backends were hard-coded to `oci` in both OCI compose files, so `.env` could not override them.
2. `ARYX_LLM_BASE_URL` and `ARYX_LLM_API_KEY` were not passed into the `api` service.
3. The model defaults in compose are Cohere.

### 3.3 Intent gateway uses the wrong model on the OCI stack
`_pinned_chat` in `cpq/intent_gateway/intent_gateway.py` calls `complete_text(..., "frontier", ...)`. With the frontier backend on OCI, `llm_oci_route._oci_model_for` returns the frontier override, so the pinned `gemini-2.5-pro` is ignored and intent classification runs on `cohere.command-a-03-2025`. Setting the frontier backend to `local` makes the pinned model take effect.

## 4. Change made

`docker-compose-oci-local.yml` and `docker-compose-oci.yml`, `api` service:
- `ARYX_LLM_CHEAP_BACKEND` and `ARYX_LLM_FRONTIER_BACKEND` now read `${…:-oci}` instead of a fixed `oci`.
- Added pass-throughs `ARYX_LLM_BASE_URL` (default `http://ollama:11434`, the previous code default), `ARYX_LLM_API_KEY` (default empty) and `ARYX_CPQ_INTENT_GEMINI_MODEL` (default `gemini-2.5-pro`).
- `ARYX_EMBED_BACKEND` stays fixed at `oci` on purpose (see section 6).
- With no `.env` change the behaviour is identical to before. Both files parse as YAML.

## 5. Switch procedure (user action, `.env` only)

Add to `.env` (the key is the user's to enter; do not commit it):
```
ARYX_LLM_CHEAP_BACKEND=local
ARYX_LLM_FRONTIER_BACKEND=local
ARYX_LLM_PROVIDER=gemini
ARYX_LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
ARYX_LLM_MENIAL_MODEL=gemini-3.5-flash
ARYX_LLM_REASON_MODEL=gemini-2.5-pro
ARYX_LLM_API_KEY=<your Gemini key>
```
Then recreate the `api` container. Check that `/api/health` is up and that the log line `cpq_intent_gateway_start` shows `provider=gemini model=gemini-2.5-pro`.

To confirm no OCI LLM calls remain, check every path, not only the intent gateway:
- `api` container: do not rely on searching the log for `provider=oci`. The per-call lines in `llm_json.py` and `llm_text.py` are `logger.debug`, and the compose default is `ARYX_LOG_LEVEL=INFO`, so the search finds nothing even if OCI calls are happening. Either set `ARYX_LOG_LEVEL=DEBUG` for the check, or (more reliable) query the `aryx_llm_call` table, where `_log_llm_call` persists `provider` and `model` per call (best effort; a write failure is only logged at debug), for example `SELECT provider, model, COUNT(*) FROM aryx_llm_call GROUP BY provider, model`, and compare the counts before and after the switch. Chat, intent classification and Tier-2 BML calls should show `gemini` after it.
- OCI Functions ingestion (if `ARYX_WORKER_BACKEND` is `oci_functions`): the function's own log line `ingest.fn.received` records `llm_cheap_backend`; it will still say `oci` until the provisioner follow-up in risk 5 is done.
- Local worker and other containers: same `provider=oci` search.

Optional discoverability: add the seven variables above as a commented block to `.env.example.oci` and `.env.example.oci-local` (not done in this PR).

Rollback: remove those lines (or set the two backends and provider back to `oci`) and recreate the container.

## 6. Embeddings: leave on OCI for now
Gemini embeddings are 768-dimensional against the 1024-dimensional Cohere vectors in Oracle. Switching needs a full re-embed and a matching vector dimension. I did not check how the Oracle schema uses `ARYX_EMBED_DIM`. Decide this separately.

## 7. Risks and open points
1. **Data leaves OCI.** With Gemini, prompts (catalog text, questions) go to Google, which the OCI-only setup avoided. Confirm this is acceptable.
2. **Model names unverified.** `gemini-3.5-flash` and `gemini-2.5-pro` are taken from the plan doc; check them against the account's access and quota before relying on them.
2a. **API key in plain environment.** The key reaches the container through compose interpolation, so `docker inspect` shows it. That matches how the other keys in this repo are handled today; move it to a Vault or secret mount if Gemini becomes a production dependency.
3. **Output differences.** Gemini through the OpenAI-compatible endpoint has known JSON quirks that `llm_normalize.py` handles; regressions are possible on paths that were tuned on Cohere. Run the CPQ intent and extraction tests with Gemini before the switch.
4. **Rate limits and timeouts.** `ARYX_LLM_TIMEOUT` is 900 seconds; free-tier throttling can stall a turn.
5. **OCI Functions worker does not follow this switch (known limitation).** `worker/oci_functions_provisioner_config.py:37-38` hard-codes `ARYX_LLM_CHEAP_BACKEND` and `ARYX_LLM_FRONTIER_BACKEND` to `oci` in the function's own configuration, and `worker/fn_handler.py:80` picks the OCI broker when the cheap backend is `oci`. So documents processed by the Functions worker keep using OCI GenAI after the `.env` switch and never receive the Gemini key. One deployment can therefore have mixed providers: chat and the intent gateway on Gemini, Functions ingestion on OCI. This PR does not change that. Follow-up: have the provisioner read `settings.effective_llm_*_backend()` and pass the key through a secret mechanism (not plain function config).
6. **Mixed stack.** Chat on Gemini with OCI embeddings and OCI document parsing is a supported combination in code, but untested here.

## 8. Not verified
- No live Gemini call, no container restart and no test run.
- The running stack's real settings were not read (Docker unresponsive, `.env` off-limits).
