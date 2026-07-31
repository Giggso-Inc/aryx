# cpq-intent-bench

Golden-set replay for CPQ intent classification and post-failure guards.

## Run (CI / pre-push)

```bash
cd aryx
PYTHONPATH=src python3 benchmarks/cpq_intent/run_bench.py
```

Exit codes: `0` pass · `1` regression.

## Golden set

`golden_set.json` — 50 canned questions with `expected_intent` (and optional
`expected_variable_name`). Offline checks cover:

- schema enum coverage
- undo detector phrases
- gateway quarantine invariants
- session snapshot/undo restore

Live LLM scoring is optional (`--live`) and not required for CI green.

## Related modules

- `aryx.cpq.intent_gateway` — LLM-first classify + quarantine
- `aryx.cpq.session_guard` — snapshots, undo, loop exits
- `aryx.cpq.bom_gate` — Step-8 provenance hard-fail
- `aryx.cpq.summary_guard` — summary field-diff
- `aryx.cpq.telemetry` — divergence rate

## Regression suite (push gate)

`CPQ_REGRESSION_SUITE.md` — 50 positive + 50 negative cases in markdown
tables, parsed by `run_regression.py`. Runs on every `git push` via the
`.git/hooks/pre-push` hook (`make cpq-regression`), and inside `make test`.

```bash
make cpq-regression                 # offline gate (no LLM)
PYTHONPATH=src python3 benchmarks/cpq_intent/run_regression.py --live   # full gateway scoring
```

Append-only: add new cases with the next free P##/N## id, never renumber.
