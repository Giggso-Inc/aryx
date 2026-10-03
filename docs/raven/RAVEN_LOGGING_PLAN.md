# aryx-oci — plan: where raven_log() goes (ingestion + retrieval)

> **DOC CONTRACT**
>
> - **Purpose**: Placement plan for adding `raven_log()` structured records to dev_oci — which function, which event, which level/criticality/error_code, which context fields, and why — before any code is written.
> - **Status**: PLAN
> - **Last updated**: 2026-10-02 — revision 2: developer decisions folded in (S3 via env, level env, one PR on `feat/ravenlogger`, deep DEBUG trail at the right level, effort estimate); built from the two logging observation docs plus a code check at dev_oci `cac516f` (`work/2026-10-02-local`) — user request
> - **Supersedes**: —
> - **Formatting**: no markdown tables, per `C:\Users\Admin\Desktop\Client\CLAUDE.md`.

## 1. Summary

- **Goal**: every ingestion job and every retrieval turn leaves a short, machine-readable trail of `raven_log()` records that (a) share one correlation id, (b) say how the job/turn ended, and (c) surface every "failure hidden behind a green job" the observation docs found.
- **Approach**: additive only. No existing `logger.*` line is removed or reworded. Each new record sits next to the existing stdlib line at the same decision point (raven-log step 4), using the wrapper that already exists in the repo.
- **Size**: two layers. Layer 1 is the always-on events of sections 4 and 5 (4 foundation changes, 18 ingestion placements, 12 retrieval placements, about 35 event types). Layer 2 is the deep trail of section 9a: a `raven_log(level, ...)` call at every deciding condition on the ingestion and retrieval paths, at the level that fits, with DEBUG for the detail. Layer 2 is an estimated 150 or more call sites.
- **Detail level**: the developer wants deep logs for debugging. One call, `raven_log(level, ...)`, placed in the function where the thing happens. No separate debug helper and no per-area switches. One env (`ARYX_RAVEN_LOG_LEVEL`) controls how much comes out.
- **Not in scope**: removing or rewording any existing `logger.*` line; logging values (section 9a content rule); the PII fixes of section 7 (separate change).
- **Blocked on**: the developer's "approved" on `design.md` (the design gate). The three earlier decisions are answered (section 8).

> **In plain words**: Today the app writes many text lines, but nothing says "job X finished OK" or "job X looked green but dropped two files". This plan adds about 35 short JSON records at exactly those places, all stamped with the job id or the run id, so a person or a tool can follow one upload or one quote turn from start to end.

## 2. What already exists (checked in code, not taken from docs)

- **The wrapper**: `raven_log` in `aryx.raven_log` already wraps the `raven-logger` SDK. It fills `service="aryx-api"`, `project="aryx"`, `principal="service:aryx-api"`, and an `env` mapped from `ARYX_ENV`/`ENV`. The new calls use this wrapper. Note that its argument order is `(level, criticality, message, ...)`, not the SDK's `(level, message, *, criticality)`, so new calls pass everything by keyword.
- **The dependency**: `raven-logger~=1.0` is listed in the root `requirements.txt`. It is **missing** from `functions\aryx-ingest-fn\requirements_oci.txt`, the OCI Function image.
- **The call sites**: there are two today. `health` writes INFO P4 "health check ok" on every `GET /health`, about 4 per minute. `apply_oracle_json_budget` writes WARN P3 `ORACLE_JSON_BUDGET_STRIPPED`, which is already well shaped with Outcome-pipeline context.
- **The sink**: no emitter is passed. The SDK default prints JSON straight to stdout, so the records end up mixed into the container log with no logger prefix (confirmed in `aryx-oci_logging_ingestion_log_mapping.md` section 6). There is no `config.py` and no `S3Emitter` anywhere.
- **Correlation**: `trace_id` is generated fresh on every call. It does not match the job id, the discovery id, the retrieval run id or the request id. The retrieval run id lives in a context variable (`set_run_id`/`get_run_id`), which nothing in ingestion ever sets.

## 3. Foundation changes (do these first, one small diff)

- **Id**: F1
- **What**: make the `aryx.raven_log` wrapper fail open. If `import raven_logger` fails, use a no-op function. If the SDK raises while emitting, swallow the error (raven-flood fail-open rule).
- **Why**: the OCI Function imports the same pipeline modules (`orchestrate`, `doc_discovery`, `csv_land`) but its image has no `raven-logger`. Any new call in that shared code would crash the Function at import time.
- **Also**: add `raven-logger~=1.0` to `functions\aryx-ingest-fn\requirements_oci.txt`, so the Function emits records instead of silently skipping them.

- **Id**: F2
- **What**: default `trace_id` to the bound id. In the wrapper, if no `trace_id` is passed, use `get_run_id()` when it is set and fall back to `new_trace_id()` otherwise. In each ingestion worker entry (`_run_files`, `_run_rest`, `_run_multi`, `_run_db`, `_read_job`, `_confirm_job`, the Function `handler`), call `set_run_id(job_id)` (or `did` for a read job) at the start.
- **Why**: one id for every record of one job or turn, with no need to thread a parameter through 30 functions. Side benefit: the existing `cpq_llm_runtime ... run_id=-` lines during ingestion would show the job id instead of `-`.
- **Risk**: the four loggers that have `RunIdLogFilter` will append ` [run_id=<job id>]` to their lines during ingestion. That is intended, but the tag name says `run_id` while it holds a job id. Decision D2 in section 8.

- **Id**: F3
- **What**: configure the sink from env (section 9b). `stdout` stays the default, `s3` and `both` are available. The S3 path, access id, access token and region come only from env vars. The emitter is the batching writer of section 9c, created lazily inside `aryx.raven_log` (no new `config.py`, since the wrapper already plays that role) and passed as `_emit=`. Incomplete S3 settings or a missing `boto3` give one stdlib WARNING and a fall back to stdout.

- **Id**: F5
- **What**: level filter and kill switch. `ARYX_RAVEN_LOG_ENABLED` turns the wrapper into a no-op. `ARYX_RAVEN_LOG_LEVEL` drops records below the chosen level before any other work is done in the wrapper.
- **Why**: DEBUG call sites exist everywhere in layer 2, so the cheap early exit is what makes them affordable at the default INFO level.

- **Id**: F6
- **Status**: DROPPED by the developer (2026-10-02). No rate limiting anywhere. The flood rules of I-DB, R7 and R11 are removed: those records log every time.

- **Note on the package**: `raven_logger` is not in the repo. It is the pip package `raven-logger` (installed version 1.0.10, declared on line 56 of `requirements.txt`). Only `aryx.raven_log` imports it; all call sites import from `aryx.raven_log`. The OCI Function requirements file lacks it, hence F1.

- **Id**: F4
- **What**: list the health heartbeat as a removal candidate (raven-flood format, section 7). It is not removed in this plan.

> **In plain words**: Before adding any records, make the helper safe (it must never crash the app or the OCI Function), make it reuse the job/run id automatically, and decide where the records are sent.

## 4. Ingestion placements

Shared field rules for this section:

- `trace_id` comes from F2 (the job id). Each record also carries `context.job_id`, so a record can still be matched even if F2 is not done.
- `sample_payload` is always `""`. No record value, file content, SQL bind value or user text goes into a record (PII rule, section 7).
- Error codes use the namespace `ARYX_ING_*`.
- The "Class" field names the raven-decision-map decision class, and the context fields follow that class's required list.

### 4.1 Job lifecycle (the trail that is missing today)

- **Id**: I1
- **Event**: `ingest.job.queued`
- **Function**: the upload handler inside `file_ingest_router`, and likewise the queued points of `rest_ingest_router`, `connect_router` (multi ingest), `admin_router` (database ingest) and `doc_discover_router` (read and confirm)
- **Place**: right after `JobStore.create` succeeds, before the hand-off
- **Level / criticality / error_code**: INFO / P4 / —
- **Class**: Outcome, synchronous
- **Context**: `final_status="queued"`, `result="accepted"`, `reason_code="JOB_QUEUED"`, `duration_ms`, plus `job_id`, `workspace_id`, `road` (file/rest/db/multi/doc_read/doc_confirm), `file_count`, `total_bytes`, `worker_backend`
- **Gap closed**: "the job id of a new upload is never in the log" (ingestion doc, phase 1)

- **Id**: I2
- **Event**: `ingest.dispatch.failed`
- **Function**: `submit_to_oci_function`, `submit_to_dataflow`
- **Place**: a try/except around the OCI call that logs and then re-raises (the current behaviour is unchanged)
- **Level / criticality / error_code**: ERROR / P2 / `ARYX_ING_DISPATCH_FAILED`
- **Class**: Dependency
- **Context**: `dependency_name="oci_functions"` or `"oci_dataflow"`, `operation="invoke_async"`, `duration_ms`, `result="error"`, `error_class`, `attempt=1`, `trace_id`, `job_id`
- **Gap closed**: a failed send leaves the job "queued" for 120 minutes with only a generic `request_error` line

- **Id**: I3
- **Event**: `ingest.job.completed`
- **Function**: `_run_files`, `_run_rest`, `_run_multi`, `_run_db`, `_confirm_job`, `_read_job`, Function `handler`
- **Place**: right after `JobStore.finish(... "complete")`
- **Level / criticality / error_code**: INFO / P4 / —
- **Class**: Outcome, pipeline
- **Context**: `task_id=job_id`, `final_status="complete"`, `duration_ms`, `stage="finish"`, `result="ok"` or `"partial"`, `reason_code`, `impact_scope` (`files_total`, `plans_ok`, `plans_failed`, `docs_skipped`, `entities`, `relationships`)
- **Gap closed**: "there is no job finished OK line" (phase 10). `result="partial"` when any of I8 to I15 fired during the job, so a green job that dropped work shows as `partial` here.

- **Id**: I4
- **Event**: `ingest.job.failed`
- **Function**: the outer `except` of `_run_files`, `_run_rest`, `_run_multi`, `_run_db`, `_read_job`, `_confirm_job`, and Function `handler`
- **Place**: in the except, next to the existing `... failed job=%s` warning
- **Level / criticality / error_code**: ERROR / P2 / `ARYX_ING_JOB_FAILED`
- **Class**: Outcome, pipeline
- **Context**: `task_id`, `final_status="failed"`, `duration_ms`, `stage` (the last stage reported to `JobStore.update_stage`), `result="error"`, `reason_code=error_class`, `impact_scope`, plus `error_class` and, for Oracle errors, `ora_code` (never the exception text, which can echo row values, filenames or URLs)
- **Gap closed**: the outer catches print `str(exc)` with no class and no stage

- **Id**: I5
- **Event**: `ingest.job.cancelled`
- **Function**: `_run_files` (the `PipelineCancelled` branch), `cancel_job`
- **Level / criticality / error_code**: INFO / P3 / —
- **Class**: State Transition
- **Context**: `object_id=job_id`, `previous_state`, `requested_state="cancelled"`, `final_state`, `trigger` (`"user"` in `cancel_job`, `"worker_stop"` in `_run_files`), `result`, `reason_code="USER_CANCEL"`
- **Gap closed**: "the cancel request itself writes no line"

- **Id**: I6
- **Event**: `ingest.job.unhandled`
- **Function**: the done-callback inside `file_ingest_router`
- **Level / criticality / error_code**: ERROR / P1 / `ARYX_ING_UNHANDLED`
- **Class**: Outcome
- **Context**: `final_status="unknown"`, `result="error"`, `reason_code=error_class`, `duration_ms`, `job_id`
- **Why P1**: reaching this callback means the worker's own catch failed, so the job row may never be finished

- **Id**: I7
- **Event**: `ingest.job.swept_stale` and `ingest.sweep.failed`
- **Function**: `JobStore.sweep_stale` (only when the count is above 0) and `_stale_job_sweep`
- **Level / criticality / error_code**: WARN / P2 / `ARYX_ING_JOB_STALE` and `ARYX_ING_SWEEP_FAILED`
- **Class**: State Transition (sweep) and Dependency (sweep error)
- **Context**: `object_id="jobs"`, `previous_state="running|queued"`, `final_state="failed"`, `trigger="stale_sweep"`, `result`, `reason_code="TIMEOUT"`, plus `count` and `timeout_min`
- **Flood note**: runs every 60 s, but writes only when something was swept or failed

### 4.2 Failures hidden behind a green job (the most valuable group)

Each of these is a WARN today that leaves the job "complete". Each new record also increments a per-job counter that I3 reads to set `result="partial"`. The counter is a plain dict on the job context, not a new abstraction.

- **Id**: I8
- **Event**: `ingest.datasource.register_failed`
- **Function**: `_run_files` (the datasource ensure block), `land_csv_directly`, `store_layout_file`
- **Level / criticality / error_code**: WARN / P3 / `ARYX_ING_DATASOURCE_FAILED`
- **Class**: Dependency
- **Context**: `dependency_name="adb"`, `operation="datasource_ensure"`, `duration_ms`, `result="error"`, `error_class`, `attempt=1`, `trace_id`, plus `filename` and `kind`
- **Impact**: the file is ingested but missing from Data > Sources

- **Id**: I9
- **Event**: `ingest.layout.skipped`
- **Function**: `_run_files` and `ingest_confirmed` (both have "layout file too large" / "failed to store layout file")
- **Level / criticality / error_code**: WARN / P3 / `ARYX_ING_LAYOUT_SKIPPED`
- **Class**: Recovery
- **Context**: `triggering_error`, `attempt=1`, `max_attempts=1`, `backoff_ms=0`, `recovery_selected="skip_file"`, `fallback_target=None`, `exit_condition="skipped"`, `result`

- **Id**: I10
- **Event**: `ingest.raw_graph.write_failed`
- **Function**: `project_raw_graph_and_flatten`
- **Level / criticality / error_code**: WARN / P2 / `ARYX_ING_RAW_GRAPH_FAILED`
- **Class**: Recovery
- **Context**: `triggering_error`, `recovery_selected="continue_csv_ingest"`, `fallback_target="csv_flatten"`, `exit_condition="degraded"`, `result`, plus `stem` and `workspace_id`
- **Why P2**: the CPQ retrieval side depends on this graph

- **Id**: I11
- **Event**: `ingest.xml.fallback_raw`
- **Function**: `_xml_to_csvs` (the parse-failed, no-entity and zero-rows branches)
- **Level / criticality / error_code**: WARN / P3 / `ARYX_ING_XML_FALLBACK`
- **Class**: Recovery
- **Context**: `triggering_error` or `reason_code` (`PARSE_FAILED` / `NO_ENTITIES` / `ZERO_ROWS`), `recovery_selected="raw_upload"`, `fallback_target="single_row"`, `exit_condition="degraded"`, `result`
- **Not here**: the row-cap warning is information only; it is folded into I3's `impact_scope` instead

- **Id**: I12
- **Event**: `ingest.rest.page_failed`
- **Function**: `RestApiConnector.extract` (the "rest fetch failed page=" branch that returns early)
- **Level / criticality / error_code**: WARN / P2 / `ARYX_ING_REST_PARTIAL`
- **Class**: Dependency
- **Context**: `dependency_name="rest_source"`, `operation="fetch_page"`, `duration_ms`, `result="partial"`, `error_class`, `attempt`, `trace_id`, plus `page`, `records_kept`, and `url_host` (the host only, never the full URL or headers)
- **Why**: the earlier pages are kept and the rest is silently dropped

- **Id**: I13
- **Event**: `ingest.docs.summary`
- **Function**: `DocumentRouterConnector.extract`, after its loop (or after the parallel loop in `ingest_documents_parallel`)
- **Level / criticality / error_code**: INFO / P4 when nothing was skipped, WARN / P2 / `ARYX_ING_DOCS_SKIPPED` when any document failed or timed out
- **Class**: Outcome, pipeline (a loop summary, per raven-flood)
- **Context**: `task_id`, `final_status`, `duration_ms`, `stage="documents"`, `result`, `reason_code`, `impact_scope` (`docs_total`, `docs_ok`, `docs_failed`, `docs_timed_out`, `skipped_names` capped at 20)
- **Flood rule**: no per-document raven record. The existing per-document `ingest failed path=` and `ingest TIMED OUT` stdlib lines stay as they are.

- **Id**: I14
- **Event**: `ingest.mentions.all_failed`
- **Function**: `extract_mentions` (the existing "ALL %d chunk(s) failed" branch)
- **Level / criticality / error_code**: ERROR / P2 / `ARYX_ING_LLM_EXTRACT_FAILED`
- **Class**: Dependency, an LLM call, so the raven-eval gate applies
- **Context**: `dependency_name="oci_genai"`, `operation="extract_mentions"`, `duration_ms`, `result="error"`, `error_class`, `attempt` (= max retries), `trace_id`, plus `chunks`, `model`, `prompt_version` (if the code has one; otherwise `"unversioned"`)
- **Flood rule**: per-chunk retry warnings stay stdlib only. One record per document, and only when every chunk failed.

- **Id**: I15
- **Event**: `ingest.confirm.plans_failed`, `ingest.csv_direct.failed`, `ingest.validation.failed`, `ingest.cache_invalidate.failed`
- **Function**: `ingest_confirmed`, at its four best-effort catches: the "skipping %d failed plan(s)" summary, the csv_direct except, the validation result (one record with all failed checks, not one per check), and the two cache-invalidation excepts
- **Level / criticality / error_code**: WARN / P2 / `ARYX_ING_PLAN_FAILED`, `ARYX_ING_CSV_DIRECT_FAILED`, `ARYX_ING_VALIDATION_FAILED`, `ARYX_ING_CACHE_INVALIDATE_FAILED`
- **Class**: Recovery for the plan and csv skips, Outcome for validation, Dependency for the cache marker
- **Context**: the class fields, plus `failed_files` (capped at 20), `checks_failed`, and `stale_risk_ttl_s` for the cache marker
- **Why P2**: today these are the "green job, missing data" cases on the confirm road

### 4.3 Degradations inside the pipeline stages

- **Id**: I16
- **Event**: `ingest.resolve.summary`
- **Function**: `resolve_run`, next to the existing `resolve_run complete` line
- **Level / criticality / error_code**: INFO / P4. Switches to WARN / P3 / `ARYX_ING_RESOLVE_DEGRADED` when the review sink was unavailable, adjudication failed at least once, any pair was dropped, or the edge cap hit (`_cluster_pass`).
- **Class**: Outcome, pipeline (a loop summary)
- **Context**: `task_id`, `final_status`, `duration_ms`, `stage="resolve"`, `result`, `reason_code`, `impact_scope` (`records`, `entities`, `merged`, `adjudicated`, `adjudication_failed`, `review_dropped`, `blocks_skipped_oversized`, `edge_cap_hit`), plus `pipeline_run_id`
- **Needs**: `resolve` already returns most of these counts in its summary line; `adjudication_failed` needs one counter in `_route_pair`
- **Flood rule**: no per-pair record (section 6)

- **Id**: I17
- **Event**: `ingest.relate.summary` and `ingest.fk.aborted`
- **Function**: `_relate` (next to its existing "%d/%d pair inference(s) failed" line), `_infer_schema_fk_links` (on its catch), and `link_by_attribute` (on the ABORTED branch)
- **Level / criticality / error_code**: WARN / P3 / `ARYX_ING_RELATE_DEGRADED` and `ARYX_ING_FK_ABORTED` (only when something failed or aborted; silent on a clean run)
- **Class**: Recovery for relate, Policy or Guard for the selectivity abort
- **Context**: relate uses the Recovery fields plus `pairs_total` and `pairs_failed`. The FK abort uses `actor="pipeline"`, `requested_action="link_fk"`, `resource="<src_type>.<attr>-><tgt_type>.<attr>"`, `required_permission="max_relationships_per_fk_spec"`, `decision="deny"`, `reason_code="NOT_SELECTIVE"`, `policy_version` (the value of the setting)

- **Id**: I18
- **Event**: `ingest.project.completed` and `ingest.project.failed`
- **Function**: `project_workspace_graph`
- **Place**: after `project_auto` returns, and in a log-and-re-raise around it
- **Level / criticality / error_code**: INFO / P4; failure is ERROR / P1 / `ARYX_ING_PROJECT_FAILED`
- **Class**: Outcome, pipeline (completed) and Dependency (failed)
- **Context**: `stage="project"`, `mode` (`full` or `incremental`), `backend`, `graph_ref`, `duration_ms`, the counts; for a failure also `cleared_before_failure=true/false`
- **Why P1 on failure**: a failure after the clear step leaves the workspace graph empty or half built, so retrieval is down for that workspace

### 4.4 Shared database and LLM layers (failures only)

- **Id**: I-DB
- **Event**: `db.oracle.call_failed` and `db.oracle.connection_dropped`
- **Function**: `OracleCursorWrapper.execute`, `executemany`, `executemany_returning` (their existing ERROR branches) and `OraclePool.connection` (the DPY-4011 branch)
- **Level / criticality / error_code**: ERROR / P2 / `ARYX_DB_CALL_FAILED`; WARN / P2 / `ARYX_DB_CONN_DROPPED`
- **Class**: Dependency
- **Context**: `dependency_name="oracle_adb"`, `operation` (the SQL verb and table name only), `duration_ms`, `result="error"`, `error_class`, `ora_code`, `attempt`, `trace_id`. **Never** `params` or `row0`.
- **Flood rule**: none (F6 dropped). Logs every failing statement.

- **Id**: I-LLM
- **Event**: `llm.call.failed`, `llm.retry.scheduled`, `llm.retry.exhausted`
- **Function**: `post_json` (its 429 and network retry loop, per the raven-retry lifecycle), `oci_genai_json` (the truncated-JSON retry), and `_oci_chat_raw` (its except)
- **Level / criticality / error_code**: WARN / P3 for each retry, ERROR / P2 when exhausted or failed, with `ARYX_LLM_RETRY` / `ARYX_LLM_FAILED`
- **Class**: Recovery for retries, Dependency for the LLM call, with raven-eval fields
- **Context**: Recovery fields (`attempt`, `max_attempts=5`, `backoff_ms`, `triggering_error`, `exit_condition`), plus `model`, `provider="oci_genai"`, `role`, `tokens_in`/`tokens_out` when known, and `input_ref`/`output_ref` set to the LLM call row id from `_log_llm_call` (never the prompt text)
- **Not here**: successful calls get no raven record; the LLM call table already records them

> **In plain words**: Ingestion gets a start record, an end record (complete, partial, failed or cancelled), and one record for each place where work is quietly dropped today. The end record says "partial" if any of the quiet drops happened, so a green job that lost data finally shows up.

## 5. Retrieval placements

Shared field rules: `trace_id` is the CPQ run id (`get_run_id()`, via F2), plus `context.thread_id` and `context.request_id` where they are known. Error codes use the namespace `ARYX_ASK_*`. User text never goes in `context`; record lengths or a field name instead.

- **Id**: R1
- **Event**: `ask.turn.completed`
- **Function**: `submit_message`, next to the existing `ask_run_end` line
- **Level / criticality / error_code**: INFO / P4
- **Class**: Outcome, synchronous
- **Context**: `final_status` (the session status, or `"answered"` on the question road), `result`, `reason_code` (the road: `quote`/`qa`/`standard`/`replay`), `duration_ms`, plus `thread_id`, `request_id`, `run_id`, `workspace_id`, `persisted` (true/false)
- **Gap closed**: "nothing ties the web call to the run_id" and "no turn-finished line" (retrieval doc, phases 1 and 11). Implementation check: confirm that `get_run_id()` still returns the id after `run_ask` returns in the same context (it is a ContextVar set in the same thread, so it should).

- **Id**: R2
- **Event**: `ask.turn.failed`
- **Function**: `submit_message`, the "ask run failed" except
- **Level / criticality / error_code**: ERROR / P2 / `ARYX_ASK_RUN_FAILED`
- **Class**: Outcome
- **Context**: `final_status="failed"`, `result="error"`, `reason_code=error_class`, `duration_ms`, `last_step` (the last `cpq_step` name, if cheap to read), plus the ids
- **Gap closed**: the WARNING has no error class and no traceback

- **Id**: R3
- **Event**: `ask.persist.failed`
- **Function**: `submit_message` (the prompt, failure-response and response persist excepts), `_release_failed_request_after_persist_error`, `_complete_request_after_success`
- **Level / criticality / error_code**: WARN / P2 / `ARYX_ASK_PERSIST_FAILED`
- **Class**: Dependency
- **Context**: `dependency_name="adb"`, `operation` (`save_prompt`/`save_response`/`release`/`complete`), `duration_ms`, `result`, `error_class`, `attempt=1`, `trace_id`

- **Id**: R4
- **Event**: `ask.route.selected`
- **Function**: `run_ask`, at each `return` that hands to a road (live session, hard_off_topic, feature_region_search, router result, escape hatch)
- **Level / criticality / error_code**: INFO / P4
- **Class**: Routing
- **Context**: `selected_option` (`quote`/`qa`/`standard`/`feature_search`), `available_options`, `reason_code` (`LIVE_SESSION`/`HARD_OFF_TOPIC`/`FEATURE_REGION`/`LLM_ROUTE`/`ESCAPE_HATCH`), `policy_version` (`cpq_intent_mode`), `trace_id`, plus `llm_route`, `det_is_cpq` and `confidence` when they exist
- **Gap closed**: "there is no route chosen line"

- **Id**: R5
- **Event**: `ask.router.failed_surfaced`
- **Function**: `_handle_router_error`, in both branches
- **Level / criticality / error_code**: ERROR / P2 in llm_first mode (the customer sees the sorry message); WARN / P3 in shadow mode (the fallback is used). Error code `ARYX_ASK_ROUTER_FAILED`.
- **Class**: Dependency (LLM) plus Recovery
- **Context**: `dependency_name="oci_genai"`, `operation="classify_ask_route"`, `duration_ms`, `result`, `error_class`, `attempt`, `trace_id`, `recovery_selected` (`customer_error`/`deterministic_fallback`), `timed_out`
- **Why**: in llm_first mode the turn is recorded as a success today

- **Id**: R6
- **Event**: `ask.answer.degraded`
- **Function**: `_standard_ask_pipeline` (the "ask failed" except that returns `LLM unavailable: ...`) and `_qa_graph_search` (the "cpq_qa synthesis failed" except that returns `Couldn't reach the graph: ...`)
- **Level / criticality / error_code**: ERROR / P2 / `ARYX_ASK_ANSWER_DEGRADED`
- **Class**: Dependency plus Outcome
- **Context**: `dependency_name` (`oci_genai` or `graph`), `operation`, `duration_ms`, `result="error_answer_returned"`, `error_class`, `attempt`, `trace_id`
- **Why**: an error sentence is returned as HTTP 200 and saved as a replayable answer; this record is the only signal that it was a failure

- **Id**: R7
- **Event**: `ask.rdb.read_failed`
- **Function**: the twelve `OracleCpqRdb` fetch methods (`fetch_entity_attributes`, `fetch_rules`, `fetch_value_rules` and the others), in each except that writes DEBUG and returns empty
- **Level / criticality / error_code**: ERROR / P2 / `ARYX_ASK_RDB_READ_FAILED`
- **Class**: Dependency
- **Context**: `dependency_name="oracle_adb"`, `operation` (the method name), `duration_ms`, `result="empty_returned"`, `error_class`, `attempt=1`, `trace_id`
- **Flood rule**: none (F6 dropped). An outage today looks like "loaded 0 rules" at INFO; this record makes it visible.
- **Implementation**: one shared helper inside `rdb_oracle.py` (12 identical excepts), not 12 copies

- **Id**: R8
- **Event**: `ask.bom_gate.decision`
- **Function**: `validate_before_payload`
- **Level / criticality / error_code**: INFO / P4 on PASS; WARN / P3 / `ARYX_ASK_BOM_HARD_FAIL` on HARD FAIL; WARN / P3 / `ARYX_ASK_BOM_MISSING_REQUIRED` on missing required fields; WARN / P3 / `ARYX_ASK_BOM_RECHECK_FAILED` on the constraint-recheck except
- **Class**: Policy or Guard
- **Context**: `actor` (the principal or `"customer"`), `requested_action="approve_quote"`, `resource` (product name), `required_permission="bom_gate"`, `decision` (`pass`/`fail`), `reason_code`, `policy_version` (`"bom_gate_v1"`), plus `fields_count` and `missing_fields`

- **Id**: R9
- **Event**: `ask.intent.dropped`
- **Function**: `audit_intent_conservation`, next to the existing ERROR
- **Level / criticality / error_code**: WARN / P3 / `ARYX_ASK_INTENT_DROPPED`
- **Class**: Outcome
- **Context**: `final_status`, `result="dropped"`, `reason_code`, `duration_ms`, plus `turn`, `dropped_fields` (field names, not the user's question)

- **Id**: R10
- **Event**: `auth.api_key.check_failed`
- **Function**: `_verify_key`, in the "failing closed" except
- **Level / criticality / error_code**: ERROR / P1 / `ARYX_AUTH_STORE_FAILED`
- **Class**: Policy or Guard
- **Context**: `actor="unknown"`, `requested_action` (method + path), `resource="api"`, `required_permission="api_key"`, `decision="deny"`, `reason_code="TOKEN_STORE_ERROR"`, `policy_version`
- **Why P1**: if the token store is down, every authenticated call is refused
- **Not here**: plain bad-key 401s get no record; that would be per-request noise and a brute-force amplifier

- **Id**: R11
- **Event**: `ask.rule_trace.durable_failed`
- **Function**: `record_fire` and `seal`, at their `logger.exception` branches
- **Level / criticality / error_code**: WARN / P3 / `ARYX_ASK_RULE_TRACE_FAILED`
- **Class**: Dependency
- **Flood rule**: none (F6 dropped); the existing ERROR repeats once per fired rule and so will this record

- **Id**: R12
- **Event**: `ask.invariant.orphan_question` and `ask.country_rederive.failed`
- **Function**: `assert_conversational_invariant`, `_rederive_and_revalidate_for_country_change`
- **Level / criticality / error_code**: WARN / P3 / `ARYX_ASK_ORPHAN_QUESTION` and `ARYX_ASK_COUNTRY_REDERIVE_FAILED`
- **Class**: State Transition (orphan question) and Recovery (country re-derive)
- **Context**: the class fields; no answer text (`answer_tail` stays only in the stdlib line)

> **In plain words**: Each quote or question turn gets one "route chosen" record and one "turn finished" or "turn failed" record, all with the run id. On top of that, every place where the customer gets an error dressed up as an answer, or where a database outage looks like an empty catalog, now writes a loud record.

## 6. Deep debug layer (added 2026-10-02 on developer request — supersedes the exclusions below)

The developer asked for deep logs for debugging and for the right level at each place, not a separate mechanism. So the exclusion list below is withdrawn. Every function that decides something gets a plain `raven_log(level, ...)` call at the right level: ERROR and WARN for failures and degradations, INFO for milestones and chosen roads, DEBUG for the deep trail (the result of every deciding condition, per-item events inside loops). One env, `ARYX_RAVEN_LOG_LEVEL`, decides how much is emitted. The level rules, the env contract and the S3 batching emitter are in `design.md` in the repo root and are folded into this doc when the work lands.

### Originally excluded (withdrawn — now logged at DEBUG)

- Per-pair resolve decisions (`_route_pair`), per-block lines, and entity save batches: these become counts in I16.
- Per-chunk mention extraction, per-chunk PII screening, per-document steps 1/8 to 8/8: these become counts in I13 and I14.
- `_load_all_tables` and `_load_attr_var_mapping_rows` cache hits and misses (thousands per run), per-rule load lines, and `record_fire` success lines.
- The fill stages in `resolve_one_attr` and `commit_value`: hundreds per pass. They are an evidence gap, but the rule trace file and table are the right channel, not `raven_log`.
- Successful LLM calls (already in the LLM call table) and successful Oracle statements.
- Graph batch start/done lines: covered by I18.
- Request start/end middleware lines: covered by I1, R1 and R2.

## 7. Removal and redaction candidates (listed only, nothing is removed)

Each candidate below needs a separate yes from the developer. The `--yes` flag does not cover any of them.

- **Candidate**: the `health` raven record
- **Where**: `health` route
- **Problem**: one JSON record every 15 s with a random trace id (65 in 16 minutes in the real log). It is pure noise in the raven channel.
- **Suggested**: remove it, or downgrade it to DEBUG

- **Candidate**: `OracleCursorWrapper.execute` / `executemany` error lines
- **Where**: the stdlib ERROR lines
- **Problem**: they print `params=%r` and `row0=%r`, which are real customer record values, into the server log
- **Suggested**: redact to the column count and types. This is a separate security fix, not part of this plan.

- **Candidate**: the `oci_client` auth line
- **Where**: `_get_auth`
- **Problem**: it prints the OCI user OCID in full, once per process
- **Suggested**: mask it the way the pool DSN is already masked

- **Candidate**: `cpq_apply_answer_miss reply=%r`
- **Where**: `_step9_match_pending_answer`
- **Problem**: it logs the raw customer reply text
- **Suggested**: log only the reply length

- **Candidate**: `_load_all_tables` INFO per call
- **Where**: `_load_all_tables`
- **Problem**: thousands of lines per run that hide everything else
- **Suggested**: move cache hits to DEBUG and keep misses at INFO

- **Candidate**: `_route_pair` INFO per merged pair
- **Where**: `_route_pair`
- **Problem**: one line per pair on big runs
- **Suggested**: move to DEBUG once I16 exists

## 8. Decisions (all answered by the developer on 2026-10-02; options kept for the record)

- **Answered**: D1 — sink chosen by env, S3 provisioned from env, plus a control env. D2 — yes, bind the job id with `set_run_id`. D3 — one PR with several commits on a new branch `feat/ravenlogger`; changes are staged only and nothing is committed until the developer says so. Detail level — deep logs for debugging, the right level at each place, every deciding condition logged (section 9a).
- **Still open**: the developer's "approved" on `design.md` so the design gate can freeze and code edits can start.

- **Id**: D1
- **Question**: where should the raven records go?
- **Options**: (a) stdout JSON, as today: zero setup, mixed into the container log, readable with `docker logs | grep '^{'`; (b) S3 via `S3Emitter`: needs a bucket path and the env var names this deployment uses; (c) OCI Logging / Object Storage: no adapter exists in `raven-logger` today, so this would be custom.
- **Recommendation**: (a) for this pass, so the call sites can be built and checked; switch to (b) later in F3 without touching any call site.

- **Id**: D2
- **Question**: should ingestion workers bind the job id with `set_run_id(job_id)` (F2)?
- **Options**: (a) yes: one id everywhere, and `cpq_llm_runtime` lines get it too; (b) no: pass `trace_id=job_id` explicitly at each ingestion call site, which is more lines but changes no existing log text.
- **Recommendation**: (a)

- **Id**: D3
- **Question**: rollout order?
- **Options**: (a) foundation plus ingestion lifecycle and hidden failures (F1 to F3, I1 to I15) first, then retrieval (R1 to R12), then the stage, DB and LLM layers (I16 to I18, I-DB, I-LLM); (b) everything in one change.
- **Recommendation**: (a), as three small PRs off `dev_oci`, each on its own work branch (source branches are pull-only per `PULL_UPDATES.md`)

## 9. How each step is checked

- One small test per foundation change: the wrapper does not raise when `raven_logger` is missing, and `trace_id` falls back to the bound run id.
- For each placement, a unit test that triggers the branch and captures the record through a stub `_emit`, then runs it through the raven-log validator (`raven-log-validator.py --record`). The validator checks the required fields, the enums, and that `error_code` is set on every WARN/ERROR.
- `log-coverage-check.py --file` on each touched file, run after raven-decision-map. The decision-map scan for this plan is in section 10.
- A real run on dev: one file upload, one doc read plus confirm, one quote turn. Then `grep '^{'` on the container log to confirm that every record of one job shares one `trace_id`.
- raven-signoff before each commit (the manifest says `signoff_mode: hard`).

## 9a. Level rules and the deep trail (layer 2) — where each level goes

Applied at every call site, in the function where the thing happens:

- **ERROR**: an operation failed, or a failure was caught and turned into a degraded result or a green job. Always has `error_code`. P1 if service is down or data is lost (graph cleared then failed, token store down, job row never finished), else P2.
- **WARN**: a degraded path was taken and the work continued (fallback, skip, limit hit, retry scheduled). Always has `error_code`. P2 if it repeats or degrades service, else P3.
- **INFO**: a milestone or a decision with a business result (job queued or finished, road chosen, route chosen, stage start and end with counts, product anchored, answer branch chosen, projection mode). P4, or P3 on a critical business path.
- **DEBUG**: the deep trail. The result of every `if`/`elif`/`else` that decides what happens next, on both sides of the branch, with the alternatives, the reason and the inputs (counts, scores, thresholds, flags, names, ids, timings). Per-item events inside loops are DEBUG. P4.
- **Decision rule**: where the code chooses between paths (routing, eligibility, guard or policy, state change, retry or fallback, loop exit, cache hit or miss, skip, keep, drop), one record carries `selected_option`, `available_options`, `reason_code` and the inputs.
- **Content rule**: ids, counts, scores, thresholds, flags, field, attribute and type names, timings, hashes, source tags. Never values: no row data, file content, SQL bind values, prompts, customer replies, URLs with query strings, headers.

DEBUG and decision records, by phase of the two observation docs (these add to the always-on events of sections 4 and 5; INFO/WARN/ERROR in the same functions follow the rules above):

Ingestion

- **Phase 1, request in**: the checks in the upload, REST, database and document routes (file count, size, total size, extension, workspace exists, URL guard, `fk_links` parse, dialect) each log pass or refuse, with the limit and the measured value. The refusals are not logged today.
- **Phase 2, choose the road**: `cpq_ingestion_pipeline_active`, `cpq_layout_upload_active`, `partition_cpq_ingestion_plans`, `partition_cpq_ingestion_csv_plans` and the extension split in `_run_files` log the road chosen per file with the flags in force (`ARYX_INGEST_PIPELINE`, `ARYX_INGEST_FILE_TYPE`, `ARYX_CPQ_LAYOUT_SOURCE`). The CSV chunking decision and the datasource kind chosen are logged too. Today these are DEBUG-only or silent.
- **Phase 3, hand off**: `effective_worker_backend` result, which branch (local, OCI Function, Data Flow) was taken, payload size, the executor submit, the Function `handler` entry and `_dispatch` branch.
- **Phase 4, read and parse**: per connector: size, encoding, delimiter, header column names, rows skipped or repaired, records read against expected (zero records flagged). `_xml_to_csvs` and `_xlsx_to_csvs` log each branch (detected types, capped, fallback, hidden or empty sheet). `_infer_type` logs whether the type came from the file name or the LLM and the match keys chosen. REST pages: each page fetched.
- **Phase 5, land**: `discover` and `run_spine` log batch size and time, rows dropped or changed by `clean()`, field-profile counts, tagging on or off, and each `_check_cancelled` check. `StageRunner.stage` logs each stage start, skip (resume list) and end.
- **Phase 6, documents**: per document, steps 1 to 8 with timing, reader chosen (`_connector_for`, local or OCI), pages, OCR skipped, PII counts per chunk, embedding batches, per-chunk extraction attempts, retry and give-up decisions, the timeout decision.
- **Phase 7, resolve**: `resolve_run` logs the path taken (exact ids, low key selectivity, chunked, normal) and why. `block` logs oversize skips. `_route_pair` logs each pair (ids, score, band, decision); `survivors` logs the attribute names chosen. Thresholds in force are logged at the start.
- **Phase 8, relate**: each FK candidate considered with the reason it was linked or not (`_detect_fk_links` passes, `generate_candidate_pairs`, `_judge_batch` verdicts), `link_by_attribute` counts and the selectivity check, `_relate` pair budget and each pair outcome, `_relate_isolated` per type, `detect_and_link_dimensions` per group, `resolve_and_relate_raw_graph` per tag.
- **Phase 9, project**: `project_auto` logs incremental or full and why (watermark found, dirty fraction against `ARYX_PROJECT_DIRTY_MAX`); per batch timing in `_write_chunks`; graph name and backend.
- **Phase 10, finish**: every `JobStore.update_stage` (stage, percent) and status change, temp file cleanup, datasource and catalog writes with whether the row already existed.
- **Phase 11, direct CSV landing**: the flag check that chose the direct road, rows landed, datasource kind, whether the datasource already existed.
- **Phase 12, discovery and confirm**: each decision in `ingest_confirmed` (plan lists built, layout split, direct CSV split, XML split, resume skip, parallel against last plan, validation run or skipped, cache steps).
- **Phase 13, failures**: each outer catch logs the stage reached and the error class (already ERROR in section 4).
- **Shared layers**: Oracle cursor and pool (verb, table, rows, duration, slow statements), LLM providers (role, model, tokens, latency, each retry), job store.

Retrieval

- **Phase 1, request**: `submit_message` logs replay found or not, claim result (409 or new), history size, and the persist result for the prompt and the answer. `_verify_key` logs allow or deny with the reason, never the key.
- **Phase 2, route**: `run_ask` logs the result of each check in order (live session, `hard_off_topic`, feature-region search, `_deterministic_cpq_gate`, `soft_quote_heuristic`, `classify_ask_route` result with confidence) and the road taken. `_handle_router_error` logs the mode and the choice made. The mid-session intent check (`classify_intent`, `_llm_first_gateway_turn`) logs its action and why, including "ran and did nothing".
- **Phase 3, rebuild the quote**: `_preamble_run` and each gate log whether they handled the turn and why (undo, summary, guided mode, quantity gates, country change); the session restored or new, the turn number, hints and country found (names only), and country validity.
- **Phase 4, find the product**: `_step1_resolve_product_anchor` logs which of the five ways found the product, the other candidates, and the outcome when the customer is asked instead. Product switch gates log confirm, decline and redetect decisions.
- **Phase 5, model**: `_resolve_model_leaf` logs the leaves, the pick or the ask; `_cpq_model_candidates` logs the candidates and any fallback; base model source; Hardware Version check.
- **Phase 6, load**: `load_product_config`, `load_hiding_rules`, `_load_value_rules`, `build_bml_evaluator`, `_load_all_tables` log the catalog prefix chosen, counts, cache hit or miss, and any scoping fallback. An empty result from the RDB reader is logged as such.
- **Phase 7, reply**: `_step9_*` log the pending field, the match tier, the miss, the LLM fallback and its confidence, the topic-switch decision, the batch reply.
- **Phase 8, rules loop**: per pass: rules fired by type, fields changed, constraint cache hit or change, the "going round in circles" check, and why the loop stopped; the sibling and multi-hint recompute decision.
- **Phase 9, fill**: `resolve_one_attr` and `commit_value` log, per attribute, the stage that decided and the source tag (hint, default, rule, data table, country-derived, region allow default, blind pick), without the value; fields left open; the in-loop against post-loop fill.
- **Phase 10, answer**: `_step11_build_turn_response` logs which branch built the answer (grid gap, stale re-ask, completion, turn cap, next question), the open-question count and field names, and the summary-guard outcome.
- **Phase 11, save**: the invariant check result, usage patch, and the closing turn record (already R1).
- **Phase 12, approval**: each `validate_before_payload` check and the seal result.
- **Phase 13, question road**: the road taken (route_qa, live-session QA, standard), search terms count, graph hit count, scope check result.

## 9e. Gaps found by checking the plan against the CPQ blind-pick bug doc (added 2026-10-02)

Source: `C:\Users\Admin\Desktop\Client\DOC\aryxent\aryxent_bug_cpq-blind-pick-unscoped-menu.md` (aryxent build). That bug took about 15 PRs to fix because the logs could not show which stage wrote which value, what it overwrote, or which model was in force. Each item below is a place where the bug doc had to add a log line or could not see something. Section 9a covered some of them only loosely; they are now explicit requirements.

State of dev_oci today (checked in code): none of the aryxent diagnostic tags exist here (`auto_fill set`, `model_scope`, `cpq_diag`, `model_resolution`, `rule_scope_filter`, `inferred_legal_values`). The fill stages are split across 27 stage modules and only 2 of them contain a logger call. `commit_value` writes the value, the display value and the source tag with no log at all.

- **Id**: G1
- **Gap**: attribute fills are not recorded with enough evidence. 9a said "stage and source tag, without the value", which would not have found this bug: the antenna value flipped between `WHIP (STANDARD)` and `STANDARD` across passes, and the bug doc only saw it from `auto_fill set vn=... value=... source=...` lines.
- **Requirement**: one record per attribute per pass from the fill coordinator, with `vn`, `pass`, `decided_by` (the stage), `source` tag, `previous_source`, `previous_value_set` (true/false), `changed` (true/false), and a `stage_trail` listing each stage tried and its outcome code (already filled, hidden, hint match, recommendation satisfied, default, governed, region or base-model allow, options, boolean fallback). Plus a DEBUG record at every write site: `commit_value`, and the direct writes in `tier6_single_b`, `multi_fallback_unconstrained`, `ask_data_gap` (`blind_pick_governed`), `ask_rule_governed_blind` (`blind_pick_rule_governed`), `tier6_single_a` and `tier5_governed_multi` (data table), `tier3_default_value`, `tier1_hint_match`, `tier2_satisfied_rec`, `region_and_base_model`.
- **Value in the record**: see decision D4 below. Without the value, the flip-flop is invisible.

- **Id**: G2
- **Gap**: overwrites are silent. `commit_value` uses `sources.setdefault`, so the first writer's source tag sticks even when a later pass writes a different value. The bug doc's "two brains, the old one wins silently" (PR 9, PR 10) and the "fourth and fifth write site" (PR 8 follow-up) were all this.
- **Requirement**: in `commit_value` and each direct write, if the attribute already has a different value, write a WARN `ARYX_ASK_FILL_OVERWRITTEN` (P3) with `vn`, `pass`, `old_source`, `new_source`, `changed`, and the values if D4 allows. If the same value is written again, DEBUG only.

- **Id**: G3
- **Gap**: the model-candidate fallback is the smoking gun and must be loud. In the bug, 298 of 298 `_cpq_model_candidates` calls returned the static `APXNEXT` pair for an APX 900 quote.
- **Requirement**: `_cpq_model_candidates` logs, per call, which tier produced the answer (tier 1, 2, 3 or the static fallback), the `product_name` it was given, and the result. DEBUG for tier hits. WARN `ARYX_ASK_MODEL_FALLBACK_STATIC` (P3) when the static APXNEXT fallback is used, once per turn per distinct result (per-turn dedupe, like the bug doc's own hooks; this is not rate limiting over time). Same for the model-leaf resolution: log the leaves, the pick, and "none picked, customer asked".

- **Id**: G4
- **Gap**: data-table lookups during fill. The bug's `_resolve_via_data_tables vn=... cpq_model='APXNEXT' values=[...] match=None` line showed that one value is used directly and several values are thrown away.
- **Requirement**: `_resolve_via_data_tables` and `_resolve_narrowed_legal_values` log `vn`, the CPQModel candidates used, the number of candidate values, the outcome (`single_match`, `ambiguous_discarded`, `none`), and the three-state legal-set result (`None` unknown, `[]` empty, list with its size). DEBUG each, WARN if the outcome discards values and the pick then falls to raw catalog order.

- **Id**: G5
- **Gap**: attributes dropped as "not applicable" or pruned. The bug doc's `named_attr_confirmed_not_applicable ... -> True` line showed the `_bm_model_*` context being deleted. dev_oci has no function with that name, so the equivalent pruning decisions must be found in `auto_fill_run`, `governance_flags`, `tier0_hidden`, `noise_var_default` and `multi_optout_and_empty`.
- **Requirement**: every place an attribute is removed, hidden, skipped or left open logs `vn` and the reason code. INFO when the attribute is a platform or model-context attribute (names starting `_bm_model`), DEBUG otherwise.

- **Id**: G6
- **Gap**: rule firing has no attribution. `record_fire` logs only rule id and type. The bug's turning point was seeing that rule "Set the base model for the G series hardware upgrades" (`ref_id` pointing at an unrelated catalog branch) fired and wrote the base model.
- **Requirement**: each fired-rule record also carries the rule name, its `ref_id` (catalog node), the target attribute, and the previous and new source for that attribute. Rule counts per turn are logged against the model's in-scope count when a model is known (the `rule_scope_filter total= kept=` idea).

- **Id**: G7
- **Gap**: base-model writes and the wildcard `'*'`. The bug doc's `would_reject_base_model value='*' wildcard=True` was how the wrong base model was found.
- **Requirement**: every write to the base-model attribute is logged with the source, the pass, and whether the value is a wildcard or a placeholder. WARN `ARYX_ASK_BASE_MODEL_PLACEHOLDER` (P3) if one is written.

- **Id**: G8
- **Gap**: the final state of the turn. The bug doc had to add a temporary `cpq_diag_TEMP` line that dumped the whole answer, because the only other way to see it was pulling it from the browser's network tab.
- **Requirement**: at the end of each quote turn, one DEBUG record with the `filled_source` map (attribute to source tag) and counts, and the values subject to D4. It is a permanent record, not a temporary one.

- **Id**: G9
- **Gap**: helper threads lose the run id. The bug's PR 3 failed live because the post-loop `auto_fill` ran in a thread pool, where context variables do not carry over, so the model scope was silently absent. In dev_oci the same problem applies to logging: F2 makes `trace_id` default to `get_run_id()`, which is empty inside any thread that did not copy the context, so those records would get random trace ids. dev_oci has many such pools (none copies the context): the ingest executor (`_get_executor`), `doc_router` and `doc_router_ingest`, `extract_mentions`, `resolution/run`, `dynamic_fk`, `enrich_relate`, `enrich_relate_isolated`, `enrich_schema_fk`, `doc_discovery` parallel plans, the intent gateway pools, the BML tier-2 pool, graph store and reader pools.
- **Requirement (F2b, added to the foundation)**: one small helper in `aryx.raven_log` that submits to an executor with `contextvars.copy_context().run`, and every pool above uses it. Where a pool cannot be changed, the call passes `trace_id` explicitly.

- **Id**: G10
- **Gap**: observation, not a code gap. My branch inventory for ingestion and retrieval is by phase (section 9a), not yet by function. The decision-map scanner under-reports (it found 0 entries in several files that have catches), so "every key decision place" cannot be claimed from the scan.
- **Requirement**: before coding each commit group, I produce a branch inventory for that group's files (every `if`/`elif`/`else`, `except`, early return, loop exit, flag check), written into this doc as a checklist. A group is done when every item on its checklist has a record or an explicit "no log" reason.

**Decision D4 (needs the developer's answer)**: the content rule says "never values". The bug doc shows the values were the evidence. Proposal:
- Log the value for enumerated and numeric attributes (catalog menu values such as `WHIP (STANDARD)`, base-model codes, quantities). These are catalog data, not customer data.
- For free-text attributes and anything the customer typed (names, labels, addresses, notes, the user's message), log only the length and a short keyed digest (HMAC-SHA256 with a deployment secret, so short guessable texts cannot be recovered by hashing candidates; see `ARYX_RAVEN_LOG_HASH_KEY` in section 9b).
- Keep banning row data, file content, SQL bind values, prompts, customer replies and credentials everywhere.

### Effort impact of 9e

The fill work (G1, G2, G4, G5, G6, G7, G8) adds about 6 to 8 hours to commit group 6. G9 adds about 3 hours to group 1 (the helper) plus about 2 hours to apply it across the pools in groups 2 to 4. Total estimate moves from 35 to 40 hours to about 46 to 53 hours.

## 9f. The G1-G8 events as raven records (validated 2026-10-02)

Each record below is a synthetic example in the exact raven-log format (14 fields, `schema_version` `"1.0"` as the SDK stamps it). The values are invented from the bug doc's own APX 900 trace; the field names and shapes are what the code will emit. All 11 passed the raven-log validator rules (required fields, enums, `error_code` non-empty on WARN and ERROR). G9 (thread context) is a helper, not a record. Values in `context` follow decision D4 (still open).

- **Id**: G1
- **Event**: `ask.fill.attribute`
- **Level / criticality**: DEBUG / P4
- **Emitted**: one per attribute per pass, from the fill coordinator
- **Notes**: Shows which stage decided, what it overwrote the source of, and every stage tried with its outcome. State Transition fields (`object_id`, `previous_state`, `requested_state`, `final_state`, `trigger`, `result`, `reason_code`) plus fill extras.

```json
{
  "schema_version": "1.0",
  "timestamp": "2026-10-02T09:00:44.230000+00:00",
  "level": "DEBUG",
  "criticality": "P4",
  "service": "aryx-api",
  "env": "dev",
  "trace_id": "9f3a1c7e5b2d4086a1e0c4d7b3f58a62",
  "span_id": "3c1f90aa",
  "principal": "service:aryx-api",
  "error_code": "",
  "message": "ask.fill.attribute decided",
  "context": {
    "object_id": "antennasType_astro",
    "previous_state": "unset",
    "requested_state": "WHIP (STANDARD)",
    "final_state": "WHIP (STANDARD)",
    "trigger": "auto_fill",
    "result": "filled",
    "reason_code": "MODEL_SCOPED_FIRST_LEGAL",
    "pass": 0,
    "decided_by": "tier6_single_b",
    "source": "default_first_available",
    "previous_source": null,
    "changed": true,
    "stage_trail": [
      [
        "tier0_already_filled",
        "not_filled"
      ],
      [
        "tier0_hidden",
        "visible"
      ],
      [
        "tier1_hint_match",
        "no_hint"
      ],
      [
        "tier2_satisfied_rec",
        "no_rule"
      ],
      [
        "tier3_default_value",
        "no_default"
      ],
      [
        "tier6_single_a",
        "data_table_no_single_match"
      ],
      [
        "tier6_single_b",
        "picked"
      ]
    ]
  },
  "sample_payload": "",
  "project": "aryx"
}
```

- **Id**: G1
- **Event**: `ask.fill.set`
- **Level / criticality**: DEBUG / P4
- **Emitted**: at every write site (`commit_value` and the direct writes in the tier and fallback stages)
- **Notes**: The value written, its display value, and the source tag. Written for enumerated and numeric attributes; free-text attributes carry `value_kind="free_text"`, a length and a hash instead of the value (decision D4).

```json
{
  "schema_version": "1.0",
  "timestamp": "2026-10-02T09:00:44.231000+00:00",
  "level": "DEBUG",
  "criticality": "P4",
  "service": "aryx-api",
  "env": "dev",
  "trace_id": "9f3a1c7e5b2d4086a1e0c4d7b3f58a62",
  "span_id": "3c1f90ab",
  "principal": "service:aryx-api",
  "error_code": "",
  "message": "ask.fill.set write site",
  "context": {
    "object_id": "antennasType_astro",
    "previous_state": "unset",
    "requested_state": "WHIP (STANDARD)",
    "final_state": "WHIP (STANDARD)",
    "trigger": "commit_value",
    "result": "written",
    "reason_code": "FIRST_WRITE",
    "pass": 0,
    "source": "default_first_available",
    "value_kind": "enumerated",
    "display_value": "Whip (Standard)"
  },
  "sample_payload": "",
  "project": "aryx"
}
```

- **Id**: G2
- **Event**: `ask.fill.overwritten`
- **Level / criticality**: WARN / P3
- **Emitted**: when a write replaces a different value
- **Notes**: This is the antenna flip-flop from the bug doc made visible: pass 0 wrote `WHIP (STANDARD)`, pass 2 replaced it with `STANDARD`.

```json
{
  "schema_version": "1.0",
  "timestamp": "2026-10-02T09:01:02.510000+00:00",
  "level": "WARN",
  "criticality": "P3",
  "service": "aryx-api",
  "env": "dev",
  "trace_id": "9f3a1c7e5b2d4086a1e0c4d7b3f58a62",
  "span_id": "3c1f90ac",
  "principal": "service:aryx-api",
  "error_code": "ARYX_ASK_FILL_OVERWRITTEN",
  "message": "ask.fill.overwritten a different value replaced an earlier one",
  "context": {
    "object_id": "antennasType_astro",
    "previous_state": "WHIP (STANDARD)",
    "requested_state": "STANDARD",
    "final_state": "STANDARD",
    "trigger": "blind_pick_rule_governed",
    "result": "overwritten",
    "reason_code": "LATER_PASS_UNSCOPED_PICK",
    "pass": 2,
    "old_source": "default_first_available",
    "new_source": "blind_pick_rule_governed",
    "value_kind": "enumerated"
  },
  "sample_payload": "",
  "project": "aryx"
}
```

- **Id**: G3
- **Event**: `ask.model.candidates`
- **Level / criticality**: DEBUG / P4
- **Emitted**: every `_cpq_model_candidates` call that a real tier answered
- **Notes**: Routing fields (`selected_option`, `available_options`, `reason_code`, `policy_version`, `trace_id`) plus the tier.

```json
{
  "schema_version": "1.0",
  "timestamp": "2026-10-02T09:00:09.402000+00:00",
  "level": "DEBUG",
  "criticality": "P4",
  "service": "aryx-api",
  "env": "dev",
  "trace_id": "9f3a1c7e5b2d4086a1e0c4d7b3f58a62",
  "span_id": "3c1f90ad",
  "principal": "service:aryx-api",
  "error_code": "",
  "message": "ask.model.candidates tier hit",
  "context": {
    "selected_option": [
      "APX900"
    ],
    "available_options": [
      "tier1_text_match",
      "tier2_model_resolution",
      "tier3_base_model",
      "static_fallback"
    ],
    "reason_code": "TIER1_TEXT_MATCH",
    "policy_version": "cpq_model_candidates_v1",
    "trace_id": "9f3a1c7e5b2d4086a1e0c4d7b3f58a62",
    "product_name": "APX 900",
    "tier": "tier1",
    "static_fallback_used": false
  },
  "sample_payload": "",
  "project": "aryx"
}
```

- **Id**: G3
- **Event**: `ask.model.fallback_static`
- **Level / criticality**: WARN / P3
- **Emitted**: `_cpq_model_candidates`, first time per turn per distinct result
- **Notes**: The record that would have shown the root cause on day one: the fixed APXNEXT pair used because no tier answered.

```json
{
  "schema_version": "1.0",
  "timestamp": "2026-10-02T09:00:09.520000+00:00",
  "level": "WARN",
  "criticality": "P3",
  "service": "aryx-api",
  "env": "dev",
  "trace_id": "9f3a1c7e5b2d4086a1e0c4d7b3f58a62",
  "span_id": "3c1f90ae",
  "principal": "service:aryx-api",
  "error_code": "ARYX_ASK_MODEL_FALLBACK_STATIC",
  "message": "ask.model.fallback_static used the fixed APXNEXT pair",
  "context": {
    "selected_option": [
      "APXNEXT",
      "APXNEXT_BOM"
    ],
    "available_options": [
      "tier1_text_match",
      "tier2_model_resolution",
      "tier3_base_model",
      "static_fallback"
    ],
    "reason_code": "NO_TIER_RESULT",
    "policy_version": "cpq_model_candidates_v1",
    "trace_id": "9f3a1c7e5b2d4086a1e0c4d7b3f58a62",
    "product_name": "",
    "tier": "static_fallback",
    "static_fallback_used": true,
    "first_in_turn": true
  },
  "sample_payload": "",
  "project": "aryx"
}
```

- **Id**: G4
- **Event**: `ask.datatable.lookup`
- **Level / criticality**: DEBUG / P4
- **Emitted**: every `_resolve_via_data_tables` / `_resolve_narrowed_legal_values` call
- **Notes**: Outcome and the three-state legal set (`None` unknown, `[]` empty, list with size).

```json
{
  "schema_version": "1.0",
  "timestamp": "2026-10-02T09:00:57.440000+00:00",
  "level": "DEBUG",
  "criticality": "P4",
  "service": "aryx-api",
  "env": "dev",
  "trace_id": "9f3a1c7e5b2d4086a1e0c4d7b3f58a62",
  "span_id": "3c1f90af",
  "principal": "service:aryx-api",
  "error_code": "",
  "message": "ask.datatable.lookup result",
  "context": {
    "selected_option": null,
    "available_options": [
      "single_match",
      "ambiguous_discarded",
      "none"
    ],
    "reason_code": "AMBIGUOUS_DISCARDED",
    "policy_version": "data_table_bridge_v1",
    "trace_id": "9f3a1c7e5b2d4086a1e0c4d7b3f58a62",
    "object_id": "antennasType_astro",
    "cpq_models": [
      "APXNEXT"
    ],
    "candidate_count": 7,
    "outcome": "ambiguous_discarded",
    "legal_set_state": "list",
    "legal_set_size": 7,
    "falls_to": "raw_catalog_order"
  },
  "sample_payload": "",
  "project": "aryx"
}
```

- **Id**: G4
- **Event**: `ask.datatable.discarded`
- **Level / criticality**: WARN / P3
- **Emitted**: when several legal values were dropped and the pick falls to raw catalog order
- **Notes**: Same lookup, raised to WARN because it leads to a wrong-model pick.

```json
{
  "schema_version": "1.0",
  "timestamp": "2026-10-02T09:00:57.441000+00:00",
  "level": "WARN",
  "criticality": "P3",
  "service": "aryx-api",
  "env": "dev",
  "trace_id": "9f3a1c7e5b2d4086a1e0c4d7b3f58a62",
  "span_id": "3c1f90b0",
  "principal": "service:aryx-api",
  "error_code": "ARYX_ASK_DATATABLE_DISCARDED",
  "message": "ask.datatable.discarded several legal values dropped, pick falls to raw catalog order",
  "context": {
    "selected_option": null,
    "available_options": [
      "single_match",
      "ambiguous_discarded",
      "none"
    ],
    "reason_code": "AMBIGUOUS_DISCARDED",
    "policy_version": "data_table_bridge_v1",
    "trace_id": "9f3a1c7e5b2d4086a1e0c4d7b3f58a62",
    "object_id": "antennasType_astro",
    "cpq_models": [
      "APXNEXT"
    ],
    "candidate_count": 7,
    "outcome": "ambiguous_discarded",
    "falls_to": "raw_catalog_order"
  },
  "sample_payload": "",
  "project": "aryx"
}
```

- **Id**: G5
- **Event**: `ask.attr.pruned`
- **Level / criticality**: INFO / P4 (DEBUG for ordinary attributes)
- **Emitted**: wherever an attribute is removed, hidden, skipped or left open
- **Notes**: INFO because the attribute here is the model context (`_bm_model_*`), the one the bug doc found being deleted.

```json
{
  "schema_version": "1.0",
  "timestamp": "2026-10-02T09:29:54.100000+00:00",
  "level": "INFO",
  "criticality": "P4",
  "service": "aryx-api",
  "env": "dev",
  "trace_id": "9f3a1c7e5b2d4086a1e0c4d7b3f58a62",
  "span_id": "3c1f90b1",
  "principal": "service:aryx-api",
  "error_code": "",
  "message": "ask.attr.pruned platform model-context attribute removed",
  "context": {
    "object_id": "_bm_model_variable_name",
    "previous_state": "present",
    "requested_state": "removed",
    "final_state": "removed",
    "trigger": "auto_fill_prune",
    "result": "pruned",
    "reason_code": "NOT_GOVERNED_BY_DATA_TABLE",
    "pass": 0,
    "is_model_context": true
  },
  "sample_payload": "",
  "project": "aryx"
}
```

- **Id**: G6
- **Event**: `ask.rule.fired`
- **Level / criticality**: DEBUG / P4
- **Emitted**: every fired rule, next to the existing rule-trace line
- **Notes**: Policy or Guard fields (`actor`, `requested_action`, `resource`, `required_permission`, `decision`, `reason_code`, `policy_version`) plus rule name, `ref_id`, target attribute and source change.

```json
{
  "schema_version": "1.0",
  "timestamp": "2026-10-02T09:29:55.489000+00:00",
  "level": "DEBUG",
  "criticality": "P4",
  "service": "aryx-api",
  "env": "dev",
  "trace_id": "9f3a1c7e5b2d4086a1e0c4d7b3f58a62",
  "span_id": "3c1f90b2",
  "principal": "service:aryx-api",
  "error_code": "",
  "message": "ask.rule.fired attributed to a target attribute",
  "context": {
    "actor": "rule_engine",
    "requested_action": "set_attribute",
    "resource": "modelSelectionbaseModel_astro",
    "required_permission": "rule_in_model_scope",
    "decision": "applied",
    "reason_code": "RULE_FIRED",
    "policy_version": "rule_scope_v0_unscoped",
    "rule_id": "7327941662",
    "rule_name": "Set Base Model For DMSO",
    "ref_id": 39185814,
    "rule_type": "recommendation",
    "target_attribute": "modelSelectionbaseModel_astro",
    "pass": 0,
    "old_source": null,
    "new_source": "rule",
    "rules_fired_this_turn": 2,
    "rules_in_scope_for_model": null
  },
  "sample_payload": "",
  "project": "aryx"
}
```

- **Id**: G7
- **Event**: `ask.base_model.write`
- **Level / criticality**: WARN / P3 for a placeholder (DEBUG for a normal write)
- **Emitted**: every write to the base-model attribute
- **Notes**: The `'*'` wildcard that a rule from an unrelated catalog branch wrote in the bug.

```json
{
  "schema_version": "1.0",
  "timestamp": "2026-10-02T09:29:55.490000+00:00",
  "level": "WARN",
  "criticality": "P3",
  "service": "aryx-api",
  "env": "dev",
  "trace_id": "9f3a1c7e5b2d4086a1e0c4d7b3f58a62",
  "span_id": "3c1f90b3",
  "principal": "service:aryx-api",
  "error_code": "ARYX_ASK_BASE_MODEL_PLACEHOLDER",
  "message": "ask.base_model.write a placeholder value was written",
  "context": {
    "object_id": "modelSelectionbaseModel_astro",
    "previous_state": "unset",
    "requested_state": "*",
    "final_state": "*",
    "trigger": "rule",
    "result": "written_placeholder",
    "reason_code": "WILDCARD_VALUE",
    "pass": 0,
    "source": "rule",
    "is_wildcard": true,
    "rule_name": "Set Base Model For DMSO"
  },
  "sample_payload": "",
  "project": "aryx"
}
```

- **Id**: G8
- **Event**: `ask.turn.state`
- **Level / criticality**: DEBUG / P4
- **Emitted**: end of each quote turn
- **Notes**: Outcome fields (`task_id`, `final_status`, `duration_ms`, `stage`, `result`, `reason_code`, `impact_scope`) plus the attribute-to-source map. Replaces the temporary `cpq_diag_TEMP` line.

```json
{
  "schema_version": "1.0",
  "timestamp": "2026-10-02T09:01:12.112000+00:00",
  "level": "DEBUG",
  "criticality": "P4",
  "service": "aryx-api",
  "env": "dev",
  "trace_id": "9f3a1c7e5b2d4086a1e0c4d7b3f58a62",
  "span_id": "3c1f90b4",
  "principal": "service:aryx-api",
  "error_code": "",
  "message": "ask.turn.state final fill sources",
  "context": {
    "task_id": "9f3a1c7e5b2d4086a1e0c4d7b3f58a62",
    "final_status": "configuring",
    "duration_ms": 53046,
    "stage": "turn_end",
    "result": "ok",
    "reason_code": "TURN_COMPLETE",
    "impact_scope": "quote_session",
    "attributes_filled": 212,
    "attributes_open": 7,
    "overwritten_count": 3,
    "filled_source": {
      "antennasType_astro": "blind_pick_rule_governed",
      "modelSelectionKeypadType_astro": "default_first_available",
      "beltClipType_astro": "data_table"
    }
  },
  "sample_payload": "",
  "project": "aryx"
}
```

## 9g. Hand-off status (2026-10-02, written when the developer's token limit was near)

> **SUPERSEDED**: the current hand-off is `aryx-oci_todo_raven_logging_handoff.md` in this folder. The work is now committed (5 commits) and pushed to `origin/feat/ravenlogger`; read that document first. The text below is kept as the earlier snapshot.

Branch `feat/ravenlogger` in `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise`, built on dev_oci `cac516f`. Everything is staged or in the working tree; NOTHING is committed. Design is frozen (`design.md` in the repo root, temporary, do not stage).

- **Done and staged (79 files)**: foundation (`aryx.raven_log` rewrite, S3 batching emitter, kill switch, level filter, context helpers, compose passthrough, Function requirements, 19 wrapper tests); area B ingestion pipeline plus the database and LLM layers (23 tests); area D retrieval load, rules and attribute fill (12 tests). 54 new tests pass together.
- **Not finished when this was written**: area A (ingestion intake and job lifecycle: I1 to I15, `worker/job_partial.py` is untracked) and area C (retrieval request and turn flow: R1 to R6, R8 to R10, R12). Both were asked to stop at a consistent point and list what remains in their inventory files. Their changed files are in the working tree, not staged. Check `git status` and their tests (`tests/test_raven_log_ingest_intake.py`, `tests/test_raven_log_ask_turn.py`) before staging.
- **To do next**: (1) stage A and C once their tests pass; (2) add the one end-of-turn call `fill_log.build_turn_state_record(session, attrs)` at the end of each quote turn in `api/ask_api.py` (G8); (3) compare existing tests against a clean checkout of HEAD, file by file for the touched areas (the full suite is too slow to run whole; B saw cross-test pollution when many files ran together); (4) add the env block of section 9b to `.env.example.oci` and `.env.example.oci-local` by hand (the zero-access rule blocks edits to them), including `ARYX_RAVEN_LOG_S3_QUEUE_MAX`; (5) one real run on dev: an upload, a document read plus confirm, a quote turn, then check the container log for JSON lines sharing one `trace_id`; (6) then commit in groups on the developer's say-so.
- **Known gaps from the agents' reports**: area B did not cover `pipeline/profile.py`, `tag.py`, `embed.py`, `pii.py`, `ingest_validation/*`, the Falkor writers, the empty-text skips in exact resolve, the bad `ARYX_PROJECT_DIRTY_MAX` branch, and could not fill `input_ref`/`output_ref` for LLM calls (the call-row insert returns no id). Area D: rules carry no `ref_id`, so `ask.rule.fired` has `ref_id` null; `single_model_variable_name` and `model_variable_candidates` (owned by area C's files) are not instrumented; the constraint-cache hit has no new log.
- **Behaviour changes to check on dev**: `evaluate_rules_loop` now sets a flag instead of using a bare `break`; `bml.py` submits tier-2 jobs with `submit_ctx` and collects results in order; `_resolve_via_data_tables` turns the candidate tuple into a list; `run_late_pass` stores the stability result in a variable before returning it.
- **Rollback**: `ARYX_RAVEN_LOG_ENABLED=false`. Default level `INFO` and sink `stdout` keep volume low; `ARYX_RAVEN_LOG_LEVEL=DEBUG` turns on the deep trail.
- **Gate note**: the write-time gate hides its deny message (stderr goes to /dev/null). `src/aryx/raven_log.py` was written through the shell with the developer's approval because the gate flags the logger's own plumbing. The inventory files `aryx-oci_todo_raven_logging_inventory_*.md` (one per area) hold the branch-by-branch checklist.

## 9b. Env contract

All read lazily, none hardcoded. New in `aryx.raven_log`; documented in both OCI `.env.example` files and passed through both OCI compose files.

- **Variable**: `ARYX_RAVEN_LOG_ENABLED`
- **Meaning**: master switch; `false` makes `raven_log()` a no-op
- **Default**: `true`

- **Variable**: `ARYX_RAVEN_LOG_LEVEL`
- **Meaning**: minimum level emitted: `DEBUG`, `INFO`, `WARN`, `ERROR`
- **Default**: `INFO`

- **Variable**: `ARYX_RAVEN_LOG_SINK`
- **Meaning**: `stdout`, `s3` or `both`
- **Default**: `stdout`

- **Variable**: `ARYX_RAVEN_LOG_S3_PATH`
- **Meaning**: `s3://bucket/prefix/`
- **Default**: none

- **Variable**: `ARYX_RAVEN_LOG_S3_ACCESS_ID` and `ARYX_RAVEN_LOG_S3_ACCESS_TOKEN`
- **Meaning**: credentials, from env only
- **Default**: none

- **Variable**: `ARYX_RAVEN_LOG_S3_REGION`
- **Meaning**: bucket region; a missing region fails loudly
- **Default**: none

- **Variable**: `ARYX_RAVEN_LOG_S3_FLUSH_SECONDS` and `ARYX_RAVEN_LOG_S3_BATCH_MAX`
- **Meaning**: batch flush time and size (section 9c)
- **Default**: `5` seconds and `500` records

- **Variable**: `ARYX_RAVEN_LOG_S3_QUEUE_MAX`
- **Meaning**: size of the in-memory queue in front of the S3 uploader; when it is full, DEBUG records are dropped first, then INFO (added during the build; it was missing from the first version of this list)
- **Default**: `20000`

- **Variable**: `ARYX_RAVEN_LOG_HASH_KEY`
- **Meaning**: secret used to turn customer text into the short digest shown in log lines (added after the peer review of PR 422); set the same value on every pod so equal texts match across the deployment
- **Default**: unset, which means a random key per process (equal texts match only within one process, and the digest can never be reproduced from outside)

## 9c. S3 emitter

- The SDK's `S3Emitter` writes one object per record and blocks the caller on each upload. At DEBUG that means thousands of uploads per job.
- The wrapper uses its own emitter instead: records go to a bounded in-memory queue, and a daemon thread writes them to S3 as JSON-lines batches (one object per batch). A batch is flushed after `ARYX_RAVEN_LOG_S3_FLUSH_SECONDS`, at `ARYX_RAVEN_LOG_S3_BATCH_MAX` records, and at shutdown. Key: `<prefix>/<yyyy>/<mm>/<dd>/<service>-<host>-<ts>-<n>.jsonl`.
- When the queue is full, DEBUG records are dropped first, then INFO. WARN and ERROR are dropped last. The count dropped is written as one WARN record when the queue drains.
- Uses `boto3` (already in `requirements.txt`; not in the OCI Function image, where S3 is therefore unavailable and the sink falls back to stdout unless the image gets `boto3`).

## 9d. Branch, commits and effort

- **Branch**: `feat/ravenlogger`, created from `work/2026-10-02-local` (dev_oci `cac516f`). One PR.
- **Staging rule**: staged only, one commit group at a time; no commit until the developer says so. Unrelated modified files already in the working tree (`.claude/scripts/*`) are not staged. `design.md` is a temporary design-gate file and is not staged.
- **Commit groups**:
  1. Foundation (F1, F2, F3, F5): wrapper, env, level filter, S3 batching emitter, deps, compose and env samples, tests.
  2. Ingestion lifecycle and hidden failures (I1 to I15, `set_run_id` in the workers).
  3. Ingestion deep trail, intake side (phases 1 to 6).
  4. Ingestion deep trail, pipeline side (phases 7 to 13, I16 to I18, I-DB, I-LLM).
  5. Retrieval always-on events (R1 to R12).
  6. Retrieval deep trail (phases 2 to 13 of section 9a).
- **Effort (rough, hands-on; review and a dev run are extra)**:
  - Group 1: 3 to 4 hours.
  - Group 2: about 6 hours.
  - Groups 3 and 4: 8 to 10 hours together.
  - Group 5: about 4 hours.
  - Group 6: 8 to 10 hours (the rule and fill code has the most branches).
  - Tests and validator runs across all groups: about 5 hours.
  - **Total: about 35 to 40 hours, roughly 5 to 6 working days**, with more than 150 new calls. The real branch count shows up only when each file is worked through, so treat this as an estimate to be re-checked after group 3.
- **Risks**: no rate limit, so a database outage writes one ERROR per failing statement; `set_run_id(job_id)` makes four existing loggers append `[run_id=<job id>]` to their lines during ingestion; DEBUG volume at hot loops (fill stages, resolve pairs, DB statements) is large by design; S3 is unavailable in the OCI Function image without `boto3`.

## 10. raven-decision-map scan (run 2026-10-02 on 26 target files)

- **Ran**: `ast_decision_scanner.py --file` on each target file of sections 4 and 5.
- **Flagged as mandatory and not logged**: `ingest_file`, `connect`/`discover`/`ingest_multi`, `_confirm_job`, `_read_job`, `handler`, `submit_to_oci_function`, `_request` (REST), the router branches in `_run_files` and `read_files`/`_run_one_plan`, the persist try in `submit_message`, `_handle_router_error`, `_standard_ask_pipeline`, `_qa_graph_search`. All of these are covered by I1 to I4, I12, I15, R2, R3, R5 and R6.
- **Scanner misses, found by reading the code**: it scored `land_csv_directly` as a "pure calculation" (it writes to the database), and it found nothing in `rest_ingest_job.py`, `admin_api.py`, `bom_gate.py`, `doc_router.py` or `fk_edges.py`, even though each has a catch that turns a failure into a green result. Per raven-decision-map's own guidance, the Outcome and Routing findings above come from reading the code, not from the scanner.
- **False positives ignored**: "Dependency" on calls to the repo's own `aryx.*` modules (D-324).

## Citations

- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\raven_log.py` — `raven_log`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\api\graph_api.py` — `health`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\source\source_catalog_oracle_budget.py` — `apply_oracle_json_budget`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\cpq\logging_context.py` — `set_run_id`, `get_run_id`, `RunIdLogFilter`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\requirements.txt` — `raven-logger~=1.0`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\functions\aryx-ingest-fn\requirements_oci.txt` — (no raven-logger)
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\api\file_ingest\file_ingest_api.py` — `file_ingest_router` (upload handler, done-callback)
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\api\file_ingest\file_ingest_run.py` — `_run_files`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\api\rest_ingest\rest_ingest_api.py` — `rest_ingest_router`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\api\rest_ingest\rest_ingest_job.py` — `_run_rest`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\api\connect_api.py` — `connect_router`, `_run_multi`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\api\admin_api.py` — `admin_router`, `_run_db`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\api\doc_discover\doc_discover_api.py` — `doc_discover_router`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\api\doc_discover\doc_discover_read_job.py` — `_read_job`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\api\doc_discover\doc_discover_confirm_job.py` — `_confirm_job`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\api\jobs_api.py` — `cancel_job`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\api\main_lifespan.py` — `_stale_job_sweep`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\store\job_store.py` — `JobStore.create`, `JobStore.update_stage`, `JobStore.finish`, `JobStore.sweep_stale`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\worker\fn_handler.py` — `handler`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\worker\oci_functions_worker.py` — `submit_to_oci_function`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\worker\oci_dataflow_worker.py` — `submit_to_dataflow`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\cpq_ingestion\csv_land.py` — `land_csv_directly`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\cpq_ingestion\layout_store.py` — `store_layout_file`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\cpq_ingestion\pipeline.py` — `project_raw_graph_and_flatten`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\pipeline\doc_discovery\doc_discovery_xml.py` — `_xml_to_csvs`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\pipeline\doc_discovery\doc_discovery.py` — `read_files`, `ingest_confirmed`, `_run_one_plan`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\connectors\rest_api.py` — `RestApiConnector.extract`, `_request`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\connectors\doc_router.py` — `DocumentRouterConnector.extract`, `ingest_documents_parallel`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\connectors\doc_router_ingest.py` — `_log_timed_out`, `ingest_document`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\ontology\extract.py` — `extract_mentions`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\resolve_entities.py` — `resolve_run`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\resolution\run.py` — `resolve`, `_route_pair`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\resolution\chunked.py` — `_cluster_pass`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\pipeline\enrich\enrich_relate.py` — `_relate`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\pipeline\enrich\enrich_schema_fk.py` — `_infer_schema_fk_links`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\pipeline\fk_edges.py` — `link_by_attribute`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\pipeline\orchestrate.py` — `project_workspace_graph`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\project\__init__.py` — `project_auto`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\store\oracle_cursor.py` — `OracleCursorWrapper.execute`, `OracleCursorWrapper.executemany`, `OracleCursorWrapper.executemany_returning`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\store\oracle_connection_pool.py` — `OraclePool.connection`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\llm\llm_providers.py` — `post_json`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\llm\llm_providers_oci.py` — `_oci_chat_raw`, `oci_genai_json`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\llm\llm_call_log.py` — `_log_llm_call`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\api\ask_thread_api.py` — `submit_message`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\api\ask_thread_helpers.py` — `_release_failed_request_after_persist_error`, `_complete_request_after_success`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\api\ask_run_ask.py` — `run_ask`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\api\ask_run_ask_router_error.py` — `_handle_router_error`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\api\ask_standard_pipeline\_pipeline.py` — `_standard_ask_pipeline`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\api\ask_qa\ask_qa_graph_search.py` — `_qa_graph_search`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\cpq\rdb\rdb_oracle.py` — `fetch_entity_attributes`, `fetch_entities_by_type`, `fetch_entities_by_exact_type`, `fetch_all_entities_grouped_by_type`, `list_ontology_types`, `fetch_rules`, `fetch_value_rules`, `fetch_rule_inputs`, `fetch_rule_actions`, `fetch_marked_attrs`, `fetch_rule_chain_links`, `fetch_layout_attr_assoc`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\cpq\bom_gate\bom_gate.py` — `validate_before_payload`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\cpq\intent_queue\intent_queue.py` — `audit_intent_conservation`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\api\security.py` — `_verify_key`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\cpq\rule_trace\rule_trace.py` — `record_fire`, `seal`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\cpq\session_guard\session_guard_invariant.py` — `assert_conversational_invariant`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\api\ask_country_change_revalidate.py` — `_rederive_and_revalidate_for_country_change`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\api\ask_turn_steps\ask_step9_match_answer.py` — `_step9_match_pending_answer`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\cpq\data_table\data_table_loader.py` — `_load_all_tables`

- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\oci_client.py` — `_get_auth`

- `C:\Users\Admin\Desktop\Client\DOC\aryxent\aryxent_bug_cpq-blind-pick-unscoped-menu.md` — source of section 9e
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\cpq\auto_fill_stages\` — `commit_value`, `tier1_hint_match`, `tier2_satisfied_rec`, `tier3_default_value`, `tier5_governed_multi`, `tier6_single_a`, `tier6_single_b`, `multi_fallback_unconstrained`, `ask_data_gap`, `ask_rule_governed_blind`, `region_and_base_model`, `tier0_hidden`, `governance_flags`, `noise_var_default`, `multi_optout_and_empty`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\cpq\data_table_bridge\conflicts.py` — `_resolve_via_data_tables`
- `C:\Users\Admin\Desktop\Client\OCI\aryx-enterprise\src\aryx\cpq\data_table_bridge\candidates.py` — `_cpq_model_candidates`

Every cited path was checked to exist, and every function name was checked against its definition. `_request` in `rest_api.py` is a module-level function, not a method.
