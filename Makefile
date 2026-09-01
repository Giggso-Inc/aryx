.PHONY: help er-bench er-bench-quick test lint cpq-intent-bench cpq-regression

help:
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*##"}; {printf "  %-20s %s\n", $$1, $$2}'

er-bench: ## Full ER benchmark on all datasets; appends rows to docs/wiki/BENCHMARKS.md
	@echo "=== Running full ER benchmark ==="
	PYTHONPATH=src python -m benchmarks.run_bench --dataset febrl1 --compare-legacy
	PYTHONPATH=src python -m benchmarks.run_bench --dataset febrl2 --compare-legacy --no-append
	PYTHONPATH=src python -m benchmarks.run_bench --dataset mfg    --compare-legacy --no-append
	@echo ""
	@echo "=== Done. Results appended to docs/wiki/BENCHMARKS.md ==="

er-bench-quick: ## Febrl1 only, <60s; emits parseable P=x.xx R=x.xx F1=x.xx for CI gate
	PYTHONPATH=src python -m benchmarks.run_bench --dataset febrl1 --quick --no-append

test: ## Run all tests (gap-specific suite, no Docker)
	PYTHONPATH=src python -m pytest tests/test_resolution_funnel.py tests/test_blocking.py -v
	$(MAKE) cpq-regression

cpq-intent-bench: ## CPQ intent golden-set replay (50 JSON cases, offline, exit 1 on regression)
	PYTHONPATH=src python3 benchmarks/cpq_intent/run_bench.py

cpq-regression: ## CPQ 50+50 markdown suite (CPQ_REGRESSION_SUITE.md) — runs on every push via pre-push hook
	PYTHONPATH=src python3 benchmarks/cpq_intent/run_bench.py
	PYTHONPATH=src python3 benchmarks/cpq_intent/run_regression.py

lint: ## Raven style check
	@echo "Run: git commit (Raven pre-commit hook enforces style)"
