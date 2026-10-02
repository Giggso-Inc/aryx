# Raven structured logging (PR #422): hand-off

> **DOC CONTRACT**
>
> - **Purpose**: Tells the next person continuing the Raven structured-logging work what is done, what is pending and how to carry on. Read this first.
> - **Status**: LIVING
> - **Last updated**: 2026-10-02, second session (macOS). Merged `dev_oci` into the branch and instrumented the retrieval deep trail (area C).
> - **Supersedes**: the first-session hand-off `aryx-oci_todo_raven_logging_handoff.md`, which lives outside the repo on the first developer's machine. Section 6 lists where that document is now out of date. The plan and spec (`aryx-oci_todo_raven_logging.md`, event catalogue, level rules, env contract) also live there and are not in the repo.
> - **Formatting**: no markdown tables.

## 1. Where things are

- **Branch**: `feat/ravenlogger`. **PR**: https://github.com/Giggso-Inc/aryx-enterprise/pull/422 (target `dev_oci`; still marked WIP).
- **Commits on the branch, in order**:
  1. 5 commits from the first session: foundation, ingestion intake, ingestion pipeline, retrieval turn flow (partial), CPQ engine.
  2. `9e458f2`: merge of `dev_oci` (44 upstream commits, `cac516f..ed84ab4`), with logging added to the new upstream decision points.
  3. The area C deep trail commit, which follows the merge (see section 3).
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

## 4. What is still pending (in priority order)

1. **A real run on dev**. It has never run against a real database. Deploy the branch to dev with the defaults, then:
   - upload one CSV or XML file
   - do one document read plus confirm
   - run one quote turn ("I want APX 900 for US")

   Check that JSON lines appear in the container log, that every record of one job shares a `trace_id`, and that `ingest.job.completed` and `ask.turn.completed` appear. Repeat once with `ARYX_RAVEN_LOG_LEVEL=DEBUG` and read one turn's trail. Then try `ARYX_RAVEN_LOG_SINK=s3` with a test bucket.
2. **Env example files**. `.env.example.oci` and `.env.example.oci-local` still need the block below added by hand after `ARYX_LOG_LEVEL=INFO` (the assistant is blocked from these files):

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
3. **Ingestion and engine gaps**:
   - Not yet logged: `pipeline/profile.py`, `tag.py`, `schema_agent.py`, `embed.py`, `pii.py`, `ingest_validation/*`, the Falkor writers and other graph readers, the empty-text skips in exact resolve, and the bad `ARYX_PROJECT_DIRTY_MAX` branch in `project_auto`.
   - The Postgres RDB fetches have no per-call failure record (local only; their timeouts are logged).
4. **`ref_id` in `ask.rule.fired`**. Rules now carry `ref_id` when `cpq_rule_scope_filter_enabled` is on, but about 10 `record_fire` call sites do not pass it. Passing it also changes what the durable rule-trace table stores, so it needs the developer's OK.
5. **Small items**:
   - `input_ref` / `output_ref` on LLM records are null, because the call-row insert returns no id.
   - The per-page and per-chunk records in `extract_mentions` and the REST connector build their context before the level check.
   - `boto3` is not in the OCI Function image, so the S3 sink cannot work there.
   - The health route writes a record every 15 seconds.
6. **Separate PR (needs a yes)**: personal data in existing log lines. The Oracle error lines print bind values and the first row; the OCI user id is printed in full; `cpq_apply_answer_miss` logs the raw reply.
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
- **Sections 0 to 3 of that document**: done for this round. The branch is up to date with `dev_oci` as of `ed84ab4`. If `dev_oci` moves again, repeat its section 0 (merge, not rebase, so PR #422 stays valid).
