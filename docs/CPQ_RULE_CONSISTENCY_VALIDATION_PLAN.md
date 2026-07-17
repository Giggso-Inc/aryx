# CPQ Deterministic Rule-Consistency Validation

## Status

Implemented as a separate, read-only checker. It does not participate in an Ask
turn, mutate a CPQ session, fix a payload, or use the production `apply_*`
methods to calculate expected results.

The earlier in-engine `find_rule_inconsistencies()` proposal was rejected as the
primary validator because reusing the implementation under test cannot detect a
shared evaluator defect. The checker instead loads the same raw catalog inputs,
evaluates them through an independent oracle, and compares the result with the
production rule loop.

## Entry point

```bash
PYTHONPATH=src python scripts/check_cpq_rule_loop.py \
  --workspace-id 1 \
  --product "APX Next" \
  --strict-unknown \
  --output cpq-rule-report.json
```

Exit codes:

- `0`: every generated scenario converged and matched production.
- `1`: an oracle invariant, production comparison, or ordering check failed.
- `2`: configuration, catalog loading, scenario limit, or report I/O failed.

## Deterministic flow

For each scenario, the independent runner repeatedly executes:

1. Recompute dynamic hide/show actions from the immutable full attribute list.
2. Apply active recommendations without overwriting explicit user values.
3. Intersect active constraints and invalidate non-user values outside them.
4. Run final auto-fill using a valid default or exactly one allowed option.
5. Fingerprint filled values, provenance, visibility, constraints, pending
   attributes, scalar and multi-select values, and unknown scripts.
6. Stop only when the complete fingerprint is unchanged. A repeated earlier
   fingerprint is a cycle; reaching the guard limit is a failure.

Source-hidden helpers remain invisible but retain valid internal defaults so BML
rules can reference them. Dynamically hidden targets are removed from the
effective state before recommendation, constraint, and auto-fill phases.

## Scenario coverage

Scenario generation is deterministic and bounded rather than a Cartesian
product across every attribute. It includes:

- Every menu option of every loaded attribute.
- Multi-select options in the separate multi-value state used by production.
- Every literal and every `~`-delimited member in declarative conditions.
- A satisfying AND-of-OR condition combination and available false boundaries.
- Every comparison literal discoverable in a script or condition script.
- Unset/baseline state.
- Every target option through the catalog-option scenarios.

The configurable scenario limit fails loudly; coverage is never silently
truncated.

## Independent rule semantics

The reference oracle independently implements:

- Declarative condition grouping: values for one attribute are OR; different
  condition attributes are AND.
- Tilde-delimited OR values, case-insensitively.
- Hide/show conflict reporting without relying on rule list order.
- Recommendation conflict reporting and user-override preservation.
- Constraint intersection and empty-intersection reporting.
- Constraint validation before final auto-fill.

The BML oracle intentionally supports only a conservative flat `if/else` subset
with literal comparisons and boolean or `returnVal` actions. It never calls an
LLM. Unsupported scripts are recorded as unknown and become failures with
`--strict-unknown`.

## Production comparison

Each scenario is also passed to `CpqEngine.evaluate_rules_loop()` using copies of
the seed state. The checker compares:

- Filled values.
- Visible attributes.
- Active constraint sets.
- Pending attributes.

Production is run again with each rule list reversed. Any result change is
reported as `rule_order_dependence`.

## Report contents

The stable JSON report includes the scenario ID, minimal seed reproduction,
iteration trace, final oracle state, unknown rules, invariant issues, and
expected-versus-actual production differences.

## File structure

- `scripts/check_cpq_rule_loop.py`: CLI, catalog loading, exit codes.
- `src/aryx/cpq/validation/models.py`: immutable report/value objects.
- `conditions.py`: target resolution and declarative conditions.
- `constraint_phase.py`: active constraint intersection.
- `script_oracle.py`: deterministic BML subset.
- `oracle.py`: hide/recommend/constraint reference outcomes.
- `transitions.py`: recommendation, constraint, and final auto-fill mutations.
- `runner.py`: convergence, cycle detection, and traces.
- `trace.py`: complete-state fingerprints and iteration records.
- `scenarios.py` and `scenario_support.py`: deterministic rule/option coverage.
- `production.py`: read-only production-loop adapter.
- `compare.py` and `report.py`: mismatch classification and JSON aggregation.

## Verification

Focused pytest coverage checks tilde conditions, hide/show conflicts,
constraint-before-auto-fill ordering, explicit recommendation overrides,
self-hiding cycles, source-hidden defaults, supported and unsupported BML,
complete option scenarios, report traces, and production-state comparison.
