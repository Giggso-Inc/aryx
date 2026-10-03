# Raven structured logging (PR #422): hand-off

> **DOC CONTRACT**
>
> - **Purpose**: Tells the next person continuing the Raven structured-logging work what is done, what is pending and how to carry on. Read this first.
> - **Status**: LIVING
> - **Last updated**: 2026-10-03, third session (Windows). Closed the remaining ingestion logging gaps, passed `ref_id` to `ask.rule.fired`, ran the full suite on the final tip (section 7). Earlier: 2026-10-02, second session (macOS): merged `dev_oci` and instrumented the retrieval deep trail (area C).
> - **Supersedes**: the first-session hand-off `aryx-oci_todo_raven_logging_handoff.md`, which lives outside the repo on the first developer's machine. Section 6 lists where that document is now out of date. The plan and spec (`aryx-oci_todo_raven_logging.md`, event catalogue, level rules, env contract) also live there and are not in the repo.
> - **Formatting**: no markdown tables.

## 1. Where things are

- **Branch**: `feat/ravenlogger`. **PR**: https://github.com/Giggso-Inc/aryx-enterprise/pull/422 (target `dev_oci`; still marked WIP).
- **Commits on the branch, in order**:
  1. 5 commits from the first session: foundation, ingestion intake, ingestion pipeline, retrieval turn flow (partial), CPQ engine.
  2. `9e458f2`: merge of `dev_oci` (44 upstream commits, `cac516f..ed84ab4`), with logging added to the new upstream decision points.
  3. `f1a4144`: the area C deep trail (see section 3).
  4. A second merge of `dev_oci`, bringing in PR #423 (attribute-first product discovery, the `attribute_search` route). See section 3a.
- **Rule from the hub**: `dev_oci` is pull-only. Never commit or push to it; changes reach it only through this PR.

## 2. What the merge commit did (`9e458f2`)

- **Conflicts**: 13 resolved, keeping both the upstream logic and the `raven_log` calls.
- **Merge bugs fixed**:
  - The auto-merge dropped `import time` from `file_ingest_run.py`, which would have crashed every upload.
  - A csv_bml rejection (new upstream) finishes the job as failed but still logged `ingest.job.completed`. It now logs `ingest.job.failed` / `ARYX_ING_CSV_BML_FAILED`.
- **New records on upstream code**:
  - post-loop timeout (504) and pool saturation (503)
  - DB call timeouts (`db.call.timed_out`)
  - the model-resolution result
  - rule-scope filter counts (`ask.rule_scope.filtered`, with `rules_in_scope_for_model`)
  - model-scoped, inferred and derived picks
  - Basemodeltoconfig reads
  - raw-graph enrichment
  - the csv_bml upload hook and re-run endpoints
  - workspace CSV purge steps
- **Other fixes**:
  - The csv_bml `RunTracker` now uses the bound job id as `trace_id`. It was a fresh id per file, so those records could not be joined to the upload.
  - 35 log contexts now read `session.turn` with `getattr`.
  - G8 `ask.turn.state` is now also written for turns that end before step 11 (`fill_log.turn_state_from_session_data`).
- **Verified**:
  - Full suite (3,966 tests) run on the merged branch and on a clean `dev_oci`: 190 vs 191 failures.
  - The one failure only on the branch was an ordering problem in this PR's own test. It is fixed.

## 3. Area C deep trail (the commit after the merge)

- **What**: about 215 new `raven_log` call sites in 61 retrieval files, covering:
  - product switch gates, preamble (country change, quantity gates), model-leaf pending reply, `model_leaves.py`
  - response builders and summary narration (LLM narration failure and mismatch are WARN with `error_code`)
  - the question road: `ask_qa` fast path, label collision, multi-attribute options, resume prompt, status short-circuit
  - turn steps 1, 2 and 6 to 11, and grid batch quantity
- **Levels**: mostly DEBUG decision records (`selected_option`, `available_options`, `reason_code`). INFO where a gate handles the whole turn. WARN/ERROR with an `ARYX_ASK_*` code on caught exceptions and degraded paths.
- **Content rule**: no question, reply, answer, prompt or LLM text in any record; lengths only. Every new test file checks this with a sentinel string.
- **How it was done**: four agents, one per batch, following one brief (rules: no logic change, `getattr` reads, Edit tool so the Raven write-time gate checks each edit). Three of them hit an API session limit before writing their reports, so their changes were reviewed afterwards instead:
  - All 19 removed lines were read. Each is one of these:
    - an `if A and llm_confirm(...)` rewritten as `x = A and llm_confirm(...)`. Short-circuiting is kept, so the LLM is still only called when `A` is truthy.
    - a call result stored in a local variable before the same `if`.
    - an `except` given `as exc`.
    - `trailer_match` in `ask_mandatory_block_splice.py`, now computed as `None if count else ...`. That is equivalent, because the old code returned early when `count` was set.
  - One `else:` branch was added in `ask_step10_blocked_removal.py`. It only logs, before the unchanged `return None`.
  - pyflakes over all edited files: no undefined or unused names.
- **Tests**:
  - New files: `tests/test_raven_log_ask_switch_preamble.py`, `test_raven_log_ask_response_qa.py`, `test_raven_log_ask_steps_1_to_8.py`, `test_raven_log_ask_steps_8_to_11.py`.
  - All Raven-log tests together: 164 pass.
  - The existing tests that import the area C modules were run on the branch and on clean `dev_oci`; see the commit message for the comparison.
- **Not reviewed line by line**: batches A, B and C have no agent report because of the limit. A reviewer should skim the diffs of `ask_turn_switch/*`, `ask_preamble/*`, `ask_response_building/*`, `ask_qa/*` and `ask_step1/2/678_*` for anything the checks above would not catch, such as a log record placed in the wrong branch.

## 3a. Second merge of `dev_oci` (PR #423, attribute search)

- **Conflicts**: one, in `cpq/intent_gateway/intent_gateway.py`. Kept both the logging wrapper around `classify_intent` and the new `_parse_route(raw, *, allow_attribute_search=False)` signature.
- **Bug fixed**: `ask.route.selected` logged every `attribute_search` turn as `standard`, because `_ROADS` in `ask_run_ask.py` did not list the new road. `attribute_search` is now in `_ROADS`; that list is only used for logging.
- **New records on the attribute-search code**:
  - `ask.attr_search.skipped`: the message names a product, so the quote path is taken.
  - `ask.attr_search.over_budget` (WARN): the lookup was over budget or too many were in flight.
  - `ask.attr_search.lookup_failed` (ERROR).
  - `ask.attr_search.lookup`: grounded or not.
  - `ask.attr_search.product_check_failed` (WARN).
  - `ask.attr_search.followup_failed` (WARN).
  - `ask.attr_search.family_skipped` (WARN, in `menu_source`).
- **Already fine**: `budget.run_with_budget` already submits with `contextvars.copy_context()`, so the run id reaches the lookup thread.
- **Not changed (privacy)**: `ask_attribute_followup.py` logs the customer's raw reply in a stdlib line (`"follow-up %r is not a %r value"`). This belongs with the personal-data fixes in section 4, item 6.

## 4. What is still pending (in priority order)

1. **A real run on dev**. It has never run against a real database. Deploy the branch to dev with the defaults, then:
   - upload one CSV or XML file
   - do one document read plus confirm
   - run one quote turn ("I want APX 900 for US")

   Check that JSON lines appear in the container log, that every record of one job shares a `trace_id`, and that `ingest.job.completed` and `ask.turn.completed` appear. Repeat once with `ARYX_RAVEN_LOG_LEVEL=DEBUG` and read one turn's trail. Then try `ARYX_RAVEN_LOG_SINK=s3` with a test bucket.
2. **Env example files (done)**. The Raven block was appended to the end of `.env.example.oci` and `.env.example.oci-local`; the sample below is for reference:

   ```
   ARYX_RAVEN_LOG_ENABLED=true
   ARYX_RAVEN_LOG_LEVEL=INFO
   ARYX_RAVEN_LOG_SINK=stdout
   # ARYX_RAVEN_LOG_S3_PATH=s3://your-bucket/raven-logs/
   # ARYX_RAVEN_LOG_S3_ACCESS_ID=
   # ARYX_RAVEN_LOG_S3_ACCESS_TOKEN=
   # ARYX_RAVEN_LOG_S3_REGION=
   # ARYX_RAVEN_LOG_S3_FLUSH_SECONDS=5
   # ARYX_RAVEN_LOG_S3_BATCH_MAX=500
   # ARYX_RAVEN_LOG_S3_QUEUE_MAX=20000
   ```
3. **Ingestion and engine gaps** (done in the 2026-10-03 session except where section 7 says otherwise):
   - Not yet logged: `pipeline/profile.py`, `tag.py`, `schema_agent.py`, `embed.py`, `pii.py`, `ingest_validation/*`, the Falkor writers and other graph readers, the empty-text skips in exact resolve, and the bad `ARYX_PROJECT_DIRTY_MAX` branch in `project_auto`.
   - The Postgres RDB fetches have no per-call failure record (local only; their timeouts are logged).
4. **`ref_id` in `ask.rule.fired`** (done on 2026-10-03 with the developer's OK; see section 7). Rules now carry `ref_id` when `cpq_rule_scope_filter_enabled` is on, but about 10 `record_fire` call sites do not pass it. Passing it also changes what the durable rule-trace table stores, so it needs the developer's OK.
5. **Small items**:
   - `input_ref` / `output_ref` on LLM records are null, because the call-row insert returns no id.
   - The per-page and per-chunk records in `extract_mentions` and the REST connector build their context before the level check.
   - `boto3` is not in the OCI Function image, so the S3 sink cannot work there.
   - The health route writes a record every 15 seconds.
6. **Personal data in existing log lines** (done in this PR on 2026-10-03, commit `917be39`, see section 7; the original description follows). The Oracle error lines print bind values and the first row; the OCI user id is printed in full; `cpq_apply_answer_miss` and the attribute-search follow-up line log the raw reply.
7. When all of the above is done, drop "WIP" from the PR title.

## 5. How to run the checks (macOS notes from this session)

- **Python**: use `python3.12` (it has the project deps). The default `python3` (3.14) does not.
- **Test path**: `PYTHONPATH=.:src:tests`. The `.` is needed because a site-packages `scripts` package shadows the repo's `scripts/`. Skip `tests/test_reembed_gemini.py`, which fails to import for the same reason on both trees.
- **Full suite**: hangs at 0% CPU without a per-test timeout. Some tests open a real `psycopg_pool` against a mocked DSN and retry for 300 s, and some need Postgres on `localhost:5432`. Install `pytest-xdist` and `pytest-timeout` into a scratch folder (not the project) and run:
  `PYTHONPATH=.:src:tests:<scratch> python3.12 -m pytest tests -q -p no:cacheprovider -n 5 --timeout=180 --ignore=tests/test_reembed_gemini.py --junitxml=<out>.xml`
  It takes about an hour. Run the same command on a clean `dev_oci` checkout (`git archive origin/dev_oci | tar -x -C <dir>`) and compare the failing test ids from the two junit files. Only ids that fail on the branch alone count as regressions. About 190 failures are environmental on this machine.
- **Raven-log tests only** (seconds): `PYTHONPATH=.:src:tests python3.12 -m pytest tests/test_raven_log*.py -q -p no:cacheprovider`
- **Secret scan**: `python3.12 raven-core/secret-scan.py < /dev/null`. Without `< /dev/null` it waits forever for hook JSON on stdin when it is not run from a terminal, which is what blocks a `git commit` that runs it.
- **Coverage gate**: the decision-map scanner (`raven-decision-map/scripts/ast_decision_scanner.py`) is not installed on this machine, so `raven-core/decision-map-gate.py` fails open. The merge used a small AST check instead: every upstream-added `except` without a `raven_log`.

## 6. Corrections to the first-session hand-off

- **5.1 "G8 call site, the most important one"**: done. The step-11 call was already in commit 4, and the early-exit path was added in the merge commit.
- **5.1 deep trail**: done for the files listed in section 3, with the review caveat there.
- **5.2 compare against a clean base**: done, for the merge and for the area C related tests.
- **5.5 "rules carry only rule_name"**: no longer true after the merge (`ref_id` exists). See section 4, item 4.
- **Sections 0 to 3 of that document**: done for this round. The branch is up to date with `dev_oci` as of `6567b4f` (PR #423). If `dev_oci` moves again, repeat its section 0 (merge, not rebase, so PR #422 stays valid).

## 7. Third session (2026-10-03, Windows machine)

- **Sync**: fast-forwarded to the second session's tip (`5b63f8b2`). `dev_oci` had not moved (its tip `6567b4f`, PR #423, was already in the branch), so no new merge was needed.
- **Two new commits** (on top of `5b63f8b2`):
  - `504c9a5` `ref_id` plumbing: the 10 rule-based `record_fire` call sites (hiding, recommendation, constraint) now pass the rule's `ref_id` as `getattr(rule, "ref_id", None) or None`. Finding that changes the earlier caution: `ref_id` is only used by the `ask.rule.fired` log record (`_log_fired`); `append_entry` and the local trace file do not take it, so **the durable rule-trace table is unchanged**. The three sites that only know a rule name (`commit_value`, `tier5_governed_multi`, `multi_fallback`) still pass none.
  - `9af7b4c` remaining ingestion gaps, with 18 tests (`tests/test_raven_log_gaps_2026_10_03.py`):
    - `pipeline/tag.py`: `ingest.tag.skipped`, `ingest.tag.completed`, `ingest.tag.incomplete` (WARN, fewer tags than fields), `ingest.tag.failed` (ERROR, re-raised). Sample values are never logged.
    - `pipeline/embed.py`: `ingest.embed.skipped`, `.batch` (DEBUG), `.completed` (INFO), and ERROR records for no model, empty vectors and dimension mismatch before the existing `RuntimeError`.
    - `pipeline/pii.py`: engine-load failure is logged (ERROR, still fail-closed) and a summary with counts of PII entity types and actions; no text is logged.
    - `pipeline/profile.py`: WARN once per field when the distinct-count cap is reached, plus a DEBUG result.
    - `pipeline/schema_agent.py`: WARN when the LLM mapping fails and the heuristic is used, plus DEBUG records.
    - `resolution/run_exact.py`: WARN when records with blank match text are kept separate, DEBUG otherwise.
    - `project/__init__.py`: the bad `ARYX_PROJECT_DIRTY_MAX` branch (was `pass`) now logs WARN `ARYX_ING_PROJECT_DIRTY_MAX_INVALID` and keeps the default.
    - `graph/falkor_store.py`, `graph/falkor_write_entities.py` (the non-OCI backend): index-creation failures (WARN), graph clear when no graph existed, per-batch and summary DEBUG records.
    - `cpq/rdb/rdb_postgres.py`: the 12 swallowed fetch failures now call a `_read_failed` helper (ERROR `ARYX_ASK_RDB_READ_FAILED`), mirroring the Oracle one.
- **Checked, no change needed**: the per-chunk records in `extract_mentions` and the per-page records in the REST connector are already guarded or fire once per page. `ingest_validation/*`, `pipeline/profile.py` etc. have no further decision points the scanner can find. `oracle_graph_reader_*` and the other graph readers are read-only paths with no swallowed failures.
- **Gate check**: the offline decision-map check over every source file this branch changed versus `dev_oci` found 23 files with "new" findings, all in the CPQ engine area, where stage code calls the shared `fill_log` helper (and the scanner treats calls into another project module as unlogged dependencies). This is the known own-module false positive; the helper writes the records. This round's own 14 files: 0 findings.
- **Personal-data fixes in existing log lines** (commit `917be39`, decision D8: per-line fixes plus one helper, in this same PR; truncation was rejected as redaction because the first characters of a message are where names and phone numbers are):
  - New `src/aryx/log_safe.py`: `text_ref` (length plus 8-character hash, never the text), `mask_ocid`, `params_shape` and `rows_shape` (counts and type names).
  - `store/oracle_cursor.py`: the DEBUG and ERROR lines no longer print bind values or the first row of a failed batch (they print counts and types); the IntegrityError line prints argument types. The DEBUG shape is only computed when DEBUG is on.
  - `oci_client.py`: the user OCID is masked (type prefix and last four characters).
  - Customer text replaced by `text_ref` in 12 lines: intent gateway (`HARD_OFF_TOPIC`, veto shadow), pending scope (`retained`, `lost`), country alias, shadow intent (message, clarifying question, rationale), QA scope, answer miss (reply and hint), product-switch confirm reply, intent count, attribute-search follow-up, the product-anchor question gate, and the orphan-question answer tail. Every line keeps its prefix and other fields.
  - `tests/test_log_personal_data_2026_10_03.py` (9 tests): a sentinel string is fed through the Oracle, OCI and CPQ paths and must be absent from the captured log; a repo-wide AST lint fails if any `logger.*` call is given `req.question`, `user_answer`, `user_text` or `utterance` directly.
  - Sweep note: other stdlib lines that mention a question or answer by word were checked and are not customer text (ids, variable names, counts). The Raven records already carried lengths only.
- **Developer decisions this session**: `ref_id` plumbing yes; LLM `input_ref` / `output_ref` left null (not done); personal-data fixes first planned as a separate PR, then moved into this PR (above); copying the plan and spec into `docs/` not done; the health-route record and `boto3` in the Function image left as they are.
- **Full test suite, run on the exact tip `917be39` and on a clean `dev_oci` (`6567b4f`)** (`pytest-xdist` 4 workers, 180 s per-test timeout, junit xml compared by test id, 53 to 55 minutes each on this machine):
  - Clean `dev_oci`: 3,622 passed, 167 failed, 51 skipped. Branch tip: 3,883 passed, 183 failed, 51 skipped. 164 failures are the same on both (no Postgres or Oracle here, `oracledb` not installed, an LLM endpoint that does not exist, xdist workers killed at the per-test timeout).
  - 19 tests failed only on the branch and 20 baseline tests never ran on the branch (workers killed at the timeout). Every one of these 39 was re-run **alone in its own process** on both trees: 37 behave identically (31 pass, 6 time out on both); the other 2 are explained, not regressions: `test_raven_log_requires_error_code_on_error` was renamed on purpose to `..._fails_open` (the wrapper no longer raises, plan F1), and `test_extract_mentions_all_failed_is_error_and_trace_crosses_pool` is a new test that does not exist on `dev_oci`. The branch-only failures were test interference (stand-in `oracledb` modules, 15 `test_oracle_pool` tests) and killed workers, not code changes.
  - All 191 Raven-log and personal-data tests pass together (13 files).
  - App check: the FastAPI app imports on both trees, `/health` returns 200, and all 250 changed modules import (no live database or startup hooks were available here).
  - Trap for the next person: on Windows `pytest-timeout` kills the **whole process** when one test passes its timeout, so a single-process run of a slow test file produces no summary at all. Use xdist workers, or run suspect tests one per process. Timings are kept in the hub's `claude-instructions/test-suite-timings.md`, not in the repo.
- **Still pending**: a real run on dev (needs deploy access); dropping "WIP" from PR #422 once the developer agrees. Not done and not planned here: LLM `input_ref` / `output_ref`, the health-route record, `boto3` in the Function image. The plan is copied to `docs/raven/RAVEN_LOGGING_PLAN.md`.
