"""BML (BigMachines Markup Language) rule-script evaluation.

CPQ rules whose logic lives in a BmFunction script (condition_function_id or
action function_id != -1) were previously dropped by the rule loaders, making
the engine blind to constraints like "restrict allowed hardware by radio
frequency" — the exact class of rule that produces illegal configurations
when ignored.

Two evaluation tiers:

Tier 1 — deterministic mini-evaluator for the dominant BML idiom::

    if (hWVersion_astro == "NEXT ENHANCED LTE PLUS 5G") {
        returnVal = "APX NEXT ENHANCED"|"APX NEXT XE 4G LTE PLUS 5G";
    } else {
        returnVal = "APX NEXT INTL FED"|"APX NEXT XN SINGLE BAND";
    }
    return returnVal;

    An if/else-if/else chain of equality comparisons on variable names,
    each branch assigning a pipe-delimited list of allowed values.

Tier 2 — LLM fallback: scripts Tier 1 cannot parse are handed to the reason
model (ARYX_LLM_REASON_MODEL, role="answer") with the current variable
state; the reply is a JSON allowed-values list. Results are cached per
(script, relevant-variable-state).

Both tiers return ``None`` when the outcome is unknown (unparseable script,
referenced variable not yet filled, LLM unavailable) — the caller treats
None as "no constraint derived", never as "everything allowed".

As of the Raven Style Compliance Plan's Phase 2a (2026-09-03), the Tier-1
parsing/evaluation machinery is split across 7 focused modules — bml_text
(comment-safe text utilities), bml_conditions (single-comparison + mixed
AND/OR boolean parsing), bml_branches (if/else-if/else chain parsing +
allowed-value/bool extraction), bml_analysis (referenced-variable scanning,
literal-comparison harvesting, array-iteration idiom), bml_declarative
(bm_config_rule_input operator-code evaluation), bml_hide_idioms (the two
"hide unless in master list" structural idioms), and bml_tier1 (the
branch-walking entry points + process-wide script cache) — all re-imported
here. This was the cleanest split of the whole plan: confirmed via grep
before starting that **zero** whitebox patches exist anywhere in the test
suite against `aryx.cpq.bml.*`, so every function moved with no
patch-retargeting risk at all; splitting was purely mechanical (verified
functionally end-to-end after each extraction). `BmlEvaluator` (Tier 2 LLM
+ caching) stays here as the one remaining large, cohesive class.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from aryx.cpq.bml.bml_analysis import ArrayIterationShape, extract_literal_comparisons, parse_array_iteration, referenced_variables
from aryx.cpq.bml.bml_branches import _branch_bool, _branch_values, _parse_branches
from aryx.cpq.bml.bml_conditions import _parse_condition
from aryx.cpq.bml.bml_declarative import _operator_hit, evaluate_declarative_conditions
from aryx.cpq.bml.bml_hide_idioms import evaluate_hide_master_list_unguarded
from aryx.cpq.bml.bml_text import _strip_line_comments
from aryx.cpq.bml.bml_tier1 import (
    _first_matching_branch,
    _MAX_SHARED_CACHE_ENTRIES,
    _SHARED_SCRIPT_CACHE,
    clear_shared_bml_cache,
    evaluate_constant_return,
    evaluate_hide_tier1,
    evaluate_tier1,
)
from aryx.cpq.logging_context import install_run_id_logging
from aryx.raven_log import raven_log, submit_ctx, would_log

__all__ = [
    "ArrayIterationShape",
    "BmlEvaluator",
    "_branch_values",
    "_operator_hit",
    "_parse_branches",
    "_parse_condition",
    "_strip_line_comments",
    "clear_shared_bml_cache",
    "evaluate_constant_return",
    "evaluate_declarative_conditions",
    "evaluate_hide_master_list_unguarded",
    "evaluate_hide_tier1",
    "evaluate_tier1",
    "extract_literal_comparisons",
    "parse_array_iteration",
    "referenced_variables",
]

logger = logging.getLogger(__name__)
install_run_id_logging(__name__)


class BmlEvaluator:
    """Two-tier BML evaluation with a process-wide (workspace, script, state) cache."""

    def __init__(
        self, scripts: dict[int, str], use_llm: bool = True,
        workspace_id: int = 0, catalog_prefix: str = "",
        tier2_max_per_turn: int | None = None,
        run_id: str = "",
    ) -> None:
        """scripts — {bm_function_id: script_text} from the RDB.

        run_id — optional, log correlation only (see _call_tier2).

        workspace_id/catalog_prefix scope the shared cache (see
        _SHARED_SCRIPT_CACHE) so results never cross-contaminate between
        catalogs or workspaces that happen to reuse the same BM-native
        function id.

        tier2_max_per_turn (Amendment 18): a hard ceiling on distinct
        Tier-2 attempts across this evaluator's WHOLE lifetime — one
        instance lives for exactly one CPQ turn (built fresh per turn by
        CpqEngine.build_bml_evaluator), so this naturally caps "per turn,
        across every pass of evaluate_rules_loop combined." None defaults
        to settings.bml_tier2_max_per_turn. A `threading.Lock` guards the
        check-and-increment since prefetch_tier2 dispatches concurrently
        from multiple threads.
        """
        self._scripts = scripts
        self._use_llm = use_llm
        self._workspace_id = workspace_id
        self._catalog_prefix = catalog_prefix
        self._run_id = run_id
        if tier2_max_per_turn is None:
            from aryx.config import get_settings
            tier2_max_per_turn = get_settings().bml_tier2_max_per_turn
        self._tier2_cap = tier2_max_per_turn
        self._tier2_count = 0
        self._tier2_lock = threading.Lock()
        self._cap_warned = False
        self.stats = {
            "tier1": 0, "tier2": 0, "unknown": 0, "missing": 0, "cached": 0,
            "capped": 0, "durable_hit": 0,
            # docs/CPQ_Usage_Reporting_Gap — real token usage from every
            # Tier-2 LLM call this evaluator makes (hide/condition/values/
            # ask_worthy), accumulated across its whole lifetime (one
            # instance per turn, same scope as _tier2_count above). Every
            # _evaluate_llm_* method adds into these via _record_llm_usage
            # instead of discarding llm_runtime.chat's token counts —
            # previously silently thrown away (indexed [0] for text only),
            # so a turn with real Tier-2 activity still reported 0 tokens.
            "prompt_tokens": 0, "completion_tokens": 0,
        }

    def _record_llm_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Accumulate one Tier-2 LLM call's real token usage into self.stats.

        Called from every _evaluate_llm_* method right after a successful
        llm_runtime.chat call, regardless of whether the reply parsed to a
        usable result — the call itself happened and cost real tokens/
        latency either way, same as any other LLM call in this codebase.
        """
        self.stats["prompt_tokens"] += prompt_tokens
        self.stats["completion_tokens"] += completion_tokens

    def script_for(self, function_id: int) -> str | None:
        return self._scripts.get(function_id)

    def _prepare(
        self, kind: str, tier1_fn: Any, script: str, variables: dict[str, str],
        cache_id: int | None,
    ) -> tuple[tuple, Any, bool]:
        """Shared key/cache/Tier-1 step for hide_for_script/condition_holds/
        allowed_values_for_script (Amendment 18, docs/CPQ_UNIFIED_INTENT_
        CLASSIFIER_PLAN.md) — factored out so `prefetch_tier2` can run this
        same cheap, local, no-network step for a whole batch of scripts
        before deciding which ones genuinely need a Tier-2 call, without
        duplicating (and risking drift in) the cache-key formula each of
        those three methods already relied on individually.

        Returns (key, result, needs_tier2). When needs_tier2 is False,
        `result` is already final — a cache hit, a Tier-1 resolution, an
        unresolvable-due-to-missing-variable, or LLM disabled — and the
        caller should write it to the cache and return it directly, exactly
        as before this refactor. tier1_fn is evaluate_tier1 (allowed-values
        idiom) or evaluate_hide_tier1 (bool idiom, shared by hide_for_script
        and condition_holds) — both return (result, blocked_by_missing_var).
        """
        key = (kind, self._workspace_id, self._catalog_prefix,
               cache_id if cache_id is not None else hash(script),
               frozenset(variables.items()))
        if key in _SHARED_SCRIPT_CACHE:
            self.stats["cached"] += 1
            return key, _SHARED_SCRIPT_CACHE[key], False
        result, blocked_by_missing_var = tier1_fn(script, variables)
        if result is not None:
            self.stats["tier1"] += 1
            return key, result, False
        if blocked_by_missing_var:
            self.stats["unknown"] += 1
            return key, None, False
        if not self._use_llm:
            self.stats["unknown"] += 1
            return key, None, False
        if not self._reserve_tier2_slot():
            self.stats["capped"] += 1
            self.stats["unknown"] += 1
            return key, None, False
        return key, None, True

    def _reserve_tier2_slot(self) -> bool:
        """Claim one of this turn's Tier-2 attempts, or refuse once the cap
        (Amendment 18, `bml_tier2_max_per_turn`) is reached.

        Thread-safe (prefetch_tier2 dispatches from multiple threads at
        once) — a plain unguarded read-then-increment could let concurrent
        callers overshoot the cap. Logs a single warning the first time this
        turn hits the ceiling, so a truncated turn is visible in logs rather
        than silently incomplete.
        """
        with self._tier2_lock:
            if self._tier2_count >= self._tier2_cap:
                if not self._cap_warned:
                    self._cap_warned = True
                    logger.warning(
                        "bml: Tier-2 cap (%d) reached this turn (workspace=%s "
                        "catalog=%r) — further script-backed rules fall back "
                        "to 'unknown' (never guess) for the rest of this turn",
                        self._tier2_cap, self._workspace_id, self._catalog_prefix,
                    )
                return False
            self._tier2_count += 1
            return True

    def _store(self, key: tuple, result: Any) -> Any:
        """Write a final result to the shared cache (same cap-and-clear
        policy every call site already used) and return it, so both the
        single-script methods and prefetch_tier2's batch path share one
        write path."""
        if len(_SHARED_SCRIPT_CACHE) >= _MAX_SHARED_CACHE_ENTRIES:
            _SHARED_SCRIPT_CACHE.clear()
        _SHARED_SCRIPT_CACHE[key] = result
        return result

    def _durable_key(
        self, kind: str, script: str, variables: dict[str, str],
        cache_id: int | None,
    ) -> str:
        """Stable, cross-process cache key for the durable Tier-2 store
        (Amendment 18 option 4, docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md).

        Deliberately NOT Python's built-in hash() — string hashing is
        randomized per-process by default (PYTHONHASHSEED), so hash(script)
        (what the in-memory _SHARED_SCRIPT_CACHE key uses when cache_id is
        None) would compute a DIFFERENT value after every restart, making a
        durable store keyed on it a permanent, silent miss. sha256 over a
        canonical (sorted-keys JSON) representation is stable across
        processes, machines, and Python versions — the actual property this
        needs. Same identity components as the in-memory key (kind,
        workspace, catalog, script-or-cache_id, full variable state) — this
        durable layer changes WHERE a result is cached, never WHAT is
        treated as "the same state," so it carries no new correctness risk
        beyond the in-memory cache's own already-established semantics.
        """
        ident = cache_id if cache_id is not None else script
        canonical = json.dumps(
            {"kind": kind, "ws": self._workspace_id, "cat": self._catalog_prefix,
             "ident": ident, "vars": dict(sorted(variables.items()))},
            sort_keys=True, default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _durable_get(self, cache_key: str) -> tuple[Any, bool]:
        """Look up a Tier-2 result in the durable store. Returns (result,
        found) — best-effort: any DB error is treated as a miss, never
        raised, since this is a pure optimization layer over the same
        network-call fallback that already exists."""
        try:
            from aryx.config import get_settings
            from aryx.queries import load
            from aryx.store.pool import get_pool
            with get_pool(get_settings().effective_dsn()).connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(load("select_bml_tier2_cache"), (cache_key,))
                    row = cur.fetchone()
            if row is None:
                return None, False
            return json.loads(row[0]) if isinstance(row[0], str) else row[0], True
        except Exception:  # noqa: BLE001 — durable cache is best-effort only
            logger.debug("bml: durable tier-2 cache read failed", exc_info=True)
            return None, False

    def _durable_put(self, cache_key: str, kind: str, result: Any) -> None:
        """Persist a freshly-computed Tier-2 result. Best-effort: a write
        failure never blocks or fails the turn — the in-memory cache and
        the network fallback both still work exactly as before this layer
        existed."""
        try:
            from aryx.config import get_settings
            from aryx.queries import load
            from aryx.store.pool import get_pool
            settings = get_settings()
            result_json = json.dumps(result)
            with get_pool(settings.effective_dsn()).connection() as conn:
                with conn.cursor() as cur:
                    if settings.effective_db_backend() == "oci":
                        # Oracle has no ON CONFLICT ... DO UPDATE -- the
                        # translated upsert_bml_tier2_cache.sql only strips
                        # ON CONFLICT and swallows the resulting ORA-00001,
                        # which correctly emulates a fresh insert but would
                        # silently no-op instead of refreshing an existing
                        # row's result. Check for the existing row first.
                        cur.execute(load("select_bml_tier2_cache_exists"), (cache_key,))
                        if cur.fetchone() is not None:
                            cur.execute(load("update_bml_tier2_cache"), (result_json, cache_key))
                        else:
                            cur.execute(load("upsert_bml_tier2_cache"), (
                                cache_key, self._workspace_id, kind, result_json,
                            ))
                    else:
                        cur.execute(load("upsert_bml_tier2_cache"), (
                            cache_key, self._workspace_id, kind, result_json,
                        ))
        except Exception:  # noqa: BLE001 — durable cache is best-effort only
            logger.debug("bml: durable tier-2 cache write failed", exc_info=True)

    def _call_tier2(
        self, kind: str, script: str, variables: dict[str, str],
        cache_id: int | None = None,
    ) -> Any:
        """Single entry point for every actual Tier-2 network call — checks
        the durable cross-process cache first, only calls the LLM on a
        genuine miss, then persists the fresh result. Replaces calling
        _evaluate_llm_hide/_evaluate_llm_condition/_evaluate_llm directly so
        all four Tier-2 call sites (hide_for_script, condition_holds,
        allowed_values_for_script, prefetch_tier2) get durability for free.
        """
        durable_key = self._durable_key(kind, script, variables, cache_id)
        result, found = self._durable_get(durable_key)
        if found:
            self.stats["durable_hit"] += 1
            return result
        _t0 = time.monotonic()
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "bml_tier2: call kind=%s run_id=%s workspace_id=%s var_count=%d script=%r",
                kind, self._run_id, self._workspace_id, len(variables), script[:2000],
            )
        _before_pt = self.stats.get("prompt_tokens", 0)
        _before_ct = self.stats.get("completion_tokens", 0)
        result = {
            "hide": self._evaluate_llm_hide,
            "cond": self._evaluate_llm_condition,
            "values": self._evaluate_llm,
            "ask_worthy": self._evaluate_llm_ask_worthy,
        }[kind](script, dict(variables))
        logger.info(
            "bml_tier2: result kind=%s run_id=%s workspace_id=%s elapsed_s=%.3f "
            "prompt_tokens=%d completion_tokens=%d result_type=%s",
            kind, self._run_id, self._workspace_id, time.monotonic() - _t0,
            self.stats.get("prompt_tokens", 0) - _before_pt,
            self.stats.get("completion_tokens", 0) - _before_ct, type(result).__name__,
        )
        if logger.isEnabledFor(logging.DEBUG):
            # The result and the substituted script can carry customer-entered
            # values, so their text is DEBUG only, never INFO.
            logger.debug("bml_tier2: result text run_id=%s %.500r", self._run_id, result)
        self._durable_put(durable_key, kind, result)
        return result

    def classify_ask_worthy(
        self, attr_label: str, rule_message: str, rule_script: str, attr_key: int,
    ) -> bool:
        """Generic (not catalog-specific) Tier-2 judgment for a no-option,
        no-decision-keyword free-text attr that IS targeted by a
        ValidationRule: is this a value a sales rep configuring a quote
        would actively decide and enter, or an internal/advanced/system
        field the native UI doesn't normally prompt for?

        docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md Amendment 22 — every
        deterministic signal available (required flag, default_value,
        script shape, hiding-rule visibility) was confirmed identical
        between a genuine case (agencyDomainName_ID_swSoln,
        OfVideoStreamingDevices_3_swSoln) and a false-positive case
        (APX Next's systemID_astro / "Owner System ID", Amendment 20).
        Falls back to the LLM only because no cheaper signal exists —
        same escalation discipline as every other Tier-2 use in this file.
        Cached durably via the same `_call_tier2`/`aryx_bml_tier2_cache`
        machinery already used for script evaluation (kind="ask_worthy"),
        keyed by attr_key so it's a one-time cost per attribute, not per
        turn. Defaults to False (never guess toward asking) on any LLM
        failure or "unknown" — preserves the current safe/dormant
        behavior when the classifier can't decide.

        Routed through `_prepare` (Raven review, 2026-07-28) — previously
        called `_call_tier2` directly, which skipped BOTH the in-memory
        `_SHARED_SCRIPT_CACHE` check every other Tier-2 kind gets AND
        `bml_tier2_max_per_turn` (Amendment 18/PR #122) entirely, since only
        `_prepare` enforces that cap via `_reserve_tier2_slot()`. On an
        800+-attribute catalog with a cold durable cache, this reintroduced
        the exact unbounded-sequential-LLM-calls problem PR #122's cap
        exists to prevent. There's no Tier-1 idiom for "is this ask-worthy"
        (Amendment 22's whole premise is that no cheaper signal exists), so
        a tier1_fn that always defers to Tier-2 reuses `_prepare`'s cache/
        cap machinery without pretending a Tier-1 shortcut exists.
        """
        script = rule_script or ""
        # A gating condition (e.g. "only relevant when advancedFlag ==
        # YES") tends to sit in the script's FINAL return statement, not
        # its opening comments/setup — a head-only truncation can silently
        # cut it off on a long script (confirmed live: a 4407-char script
        # had its one gating clause at position 4315). Send both ends
        # rather than assume the interesting part is near the top.
        if len(script) > 4000:
            script = script[:2000] + "\n...\n" + script[-2000:]
        context = f"{attr_label}\n{rule_message or ''}\n{script}"
        key, result, needs_tier2 = self._prepare(
            "ask_worthy", lambda _s, _v: (None, False), context, {}, cache_id=attr_key)
        if needs_tier2:
            result = self._call_tier2("ask_worthy", context, {}, cache_id=attr_key)
            self.stats["tier2" if result is not None else "unknown"] += 1
        result = self._store(key, result)
        return bool(result) if isinstance(result, bool) else False

    def prefetch_tier2(
        self, requests: list[tuple[str, str, dict[str, str], int | None]],
    ) -> None:
        """Warm the shared cache for a batch of (kind, script, variables,
        cache_id) requests CONCURRENTLY, instead of the one-script-at-a-time
        sequential path every rule-application method otherwise takes.

        Amendment 18 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md): a single
        turn on a large catalog can leave 800+ distinct scripts needing
        Tier-2 — live-confirmed sequential evaluation of that many scripts
        can take tens of minutes. Every script's evaluation is independent
        given a fixed variable-state snapshot, so this dispatches all of
        them at once via a thread pool (Tier-2 calls are blocking network
        I/O — urllib releases the GIL while waiting, so threads, not
        asyncio, parallelize this with no change to the existing synchronous
        call sites) and lets each one's result land in `_SHARED_SCRIPT_CACHE`
        under the EXACT same key `hide_for_script`/`condition_holds`/
        `allowed_values_for_script` would compute themselves. Those methods
        are NOT changed by this — they still run sequentially, in whatever
        order the existing apply_hiding_rules/apply_recommendation_rules/
        apply_constraint_rules loops call them — but every one of those
        calls becomes a cache hit instead of a fresh network round-trip.

        This method never raises and never changes behavior, only latency:
        a request this caller failed to include (or got a kind/script/
        variables slightly wrong for) simply doesn't get pre-warmed and
        falls through to the normal sequential path for that one script,
        exactly as if prefetch had never run at all.

        Deduplicates by cache key first (multiple rules can share the exact
        same script text and current variable state) so an identical
        Tier-2 call is never fired twice concurrently for the same answer.
        """
        tier1_fn = {
            "hide": evaluate_hide_tier1,
            "cond": evaluate_hide_tier1,
            "values": evaluate_tier1,
        }
        pending: dict[tuple, tuple[str, str, dict[str, str]]] = {}
        for kind, script, variables, cache_id in requests:
            fn = tier1_fn.get(kind)
            if fn is None:
                continue  # unrecognized kind — skip, never guess a mapping
            key, result, needs_tier2 = self._prepare(kind, fn, script, variables, cache_id)
            if needs_tier2:
                pending.setdefault(key, (kind, script, variables))
            else:
                self._store(key, result)
        if not pending:
            return

        def _run(item: tuple[tuple, tuple[str, str, dict[str, str]]]) -> None:
            key, (kind, script, variables) = item
            result = self._call_tier2(kind, script, variables)
            self.stats["tier2" if result is not None else "unknown"] += 1
            self._store(key, result)

        with ThreadPoolExecutor(max_workers=min(16, len(pending))) as pool:
            if would_log("DEBUG"):
                raven_log("DEBUG", "P4", "ask.bml.tier2_batch tier-2 prefetch batch", context={
                    "pending_count": len(pending), "max_workers": min(16, len(pending))})
            # submit_ctx so each worker keeps the turn's trace_id (ordered .result() == pool.map semantics)
            for _fut in [submit_ctx(pool, _run, _it) for _it in pending.items()]:
                _fut.result()

    def allowed_values(
        self, function_id: int, variables: dict[str, str],
    ) -> list[str] | None:
        """Allowed-value list for a rule action's BML function, or None."""
        script = self._scripts.get(function_id)
        if not script:
            self.stats["missing"] += 1
            return None
        return self.allowed_values_for_script(script, variables, cache_id=function_id)

    def allowed_values_for_script(
        self, script: str, variables: dict[str, str],
        cache_id: int | None = None,
    ) -> list[str] | None:
        """Allowed-value list for a raw BML script body, or None if unknown.

        Cache key uses the FULL variable state, not a regex-filtered subset
        — live-confirmed bug: referenced_variables() can't see
        numeric-comparison/function-call variables (e.g. fmod(qty, 25)), so
        a key scoped to just those alone stayed IDENTICAL across genuinely
        different quantity values, and a cached True/False from one qty was
        wrongly reused for another. Key/cache/Tier-1 step factored into
        `_prepare` (Amendment 18) so `prefetch_tier2` can run the same cheap
        step for a whole batch before deciding what needs Tier 2 — this
        method's own behavior/return value is unchanged by that refactor.
        """
        key, result, needs_tier2 = self._prepare(
            "values", evaluate_tier1, script, variables, cache_id)
        if needs_tier2:
            # Full `variables`, not a regex-filtered subset — see
            # condition_holds' identical fix (docs/CPQ_UNIFIED_INTENT_
            # CLASSIFIER_PLAN.md Amendment 12/13 follow-up) for why:
            # referenced_variables() can't see numeric-comparison/
            # function-call variables, so a filtered subset can silently
            # omit the one variable a script actually depends on.
            result = self._call_tier2("values", script, variables, cache_id)
            self.stats["tier2" if result is not None else "unknown"] += 1
        return self._store(key, result)

    def _evaluate_llm(
        self, script: str, variables: dict[str, str],
    ) -> list[str] | None:
        """Tier 2: ask the reason model to evaluate the script."""
        try:
            from aryx import llm_runtime
            sys_p = ("You evaluate BigMachines BML rule scripts. Given the "
                     "script and the current variable values, determine which "
                     "values the script allows (its returnVal, split on '|').")
            user_p = (f"Variables:\n{json.dumps(variables, indent=1)}\n\n"
                      f"Script:\n{script[:4000]}\n\n"
                      'Reply ONLY as JSON: {"allowed_values": ["..."]} or '
                      '{"unknown": true} if it cannot be determined.')
            # Tier-2 script interpretation genuinely needs reasoning (parse a
            # real BML script, hold its logic against current variable state,
            # commit to true/false/allowed-values) — moved from "menial" to
            # "answer" (ARYX_LLM_REASON_MODEL) since this is not the
            # lightweight term-extraction task "menial" is meant for.
            txt, _it, _ot = llm_runtime.chat("answer", sys_p, user_p)
            self._record_llm_usage(_it, _ot)
            s, e = txt.find("{"), txt.rfind("}")
            if s == -1 or e <= s:
                return None
            d = json.loads(txt[s:e + 1])
            vals = d.get("allowed_values")
            if isinstance(vals, list):
                return [str(v) for v in vals if str(v).strip()]
        except Exception as exc:  # noqa: BLE001 — LLM unavailable → unknown, not fatal
            raven_log("WARN", "P3", "ask.bml.tier2_eval_failed tier-2 BML LLM evaluation failed",
                      error_code="ARYX_ASK_BML_EVAL_FAILED", context={
                          "dependency_name": "llm_runtime", "operation": "allowed_values",
                          "result": "failed", "error_class": type(exc).__name__, "attempt": 1})
            logger.debug("bml: tier-2 LLM evaluation failed", exc_info=True)
        return None

    def should_hide(
        self, function_id: int, variables: dict[str, str],
    ) -> bool | None:
        """Hide/show decision for a hiding rule's BML function, or None if
        unknown (caller must treat None as "don't hide" — see
        CpqEngine.apply_hiding_rules)."""
        script = self._scripts.get(function_id)
        if not script:
            self.stats["missing"] += 1
            return None
        return self.hide_for_script(script, variables, cache_id=function_id)

    def hide_for_script(
        self, script: str, variables: dict[str, str],
        cache_id: int | None = None,
    ) -> bool | None:
        """Hide/show decision for a raw hiding-rule BML script body, or None
        if unknown. Mirrors allowed_values_for_script's tiering/caching, but
        for the hide-rule idiom (see evaluate_hide_tier1) rather than the
        constraint/recommendation allowed-values idiom. Key/cache/Tier-1 step
        factored into `_prepare` (Amendment 18) — see allowed_values_for_
        script's docstring; this method's own behavior is unchanged."""
        key, result, needs_tier2 = self._prepare(
            "hide", evaluate_hide_tier1, script, variables, cache_id)
        if needs_tier2:
            # Full `variables`, not a regex-filtered subset — same fix as
            # allowed_values_for_script/condition_holds.
            result = self._call_tier2("hide", script, variables, cache_id)
            self.stats["tier2" if result is not None else "unknown"] += 1
        return self._store(key, result)

    def _evaluate_llm_hide(
        self, script: str, variables: dict[str, str],
    ) -> bool | None:
        """Tier 2: ask the reason model for a hiding rule's hide/show outcome."""
        try:
            from aryx import llm_runtime
            sys_p = ("You evaluate BigMachines BML hiding-rule scripts. Given "
                     "the script and the current variable values, determine "
                     "whether the script's logic hides the target attribute "
                     "(true) or keeps it visible (false).")
            user_p = (f"Variables:\n{json.dumps(variables, indent=1)}\n\n"
                      f"Script:\n{script[:4000]}\n\n"
                      'Reply ONLY as JSON: {"hide": true} or {"hide": false} '
                      'or {"unknown": true} if it cannot be determined.')
            # Tier-2 script interpretation genuinely needs reasoning (parse a
            # real BML script, hold its logic against current variable state,
            # commit to true/false/allowed-values) — moved from "menial" to
            # "answer" (ARYX_LLM_REASON_MODEL) since this is not the
            # lightweight term-extraction task "menial" is meant for.
            txt, _it, _ot = llm_runtime.chat("answer", sys_p, user_p)
            self._record_llm_usage(_it, _ot)
            s, e = txt.find("{"), txt.rfind("}")
            if s == -1 or e <= s:
                return None
            d = json.loads(txt[s:e + 1])
            if d.get("unknown"):
                return None
            hide = d.get("hide")
            if isinstance(hide, bool):
                return hide
        except Exception as exc:  # noqa: BLE001 — LLM unavailable → unknown, not fatal
            raven_log("WARN", "P3", "ask.bml.tier2_eval_failed tier-2 BML LLM evaluation failed",
                      error_code="ARYX_ASK_BML_EVAL_FAILED", context={
                          "dependency_name": "llm_runtime", "operation": "hide",
                          "result": "failed", "error_class": type(exc).__name__, "attempt": 1})
            logger.debug("bml: tier-2 LLM hide-evaluation failed", exc_info=True)
        return None

    def condition_holds(
        self, script: str, variables: dict[str, str],
        cache_id: int | None = None,
    ) -> bool | None:
        """True/False/unknown for a rule's own boolean condition script.

        Distinct from hide_for_script even though Tier 1 reuses the same
        structural if/else-chain-returning-true/false parser (evaluate_hide_tier1
        is generic — nothing about it is specific to hide/show semantics,
        only its NAME is). Kept as a separate method (not an alias) because
        Tier 2 needs its own LLM wording: hide_for_script's prompt explicitly
        asks the model to reason about "hides the target attribute," which
        is the wrong question for a rule condition that gates a declarative
        recommend/restrict action rather than a hide decision. Uses a
        distinct cache-key prefix ("cond") so a script's hide-decision and
        condition-decision can never collide even if reused across both
        (BM-native ids are only unique within one export, not globally).
        Key/cache/Tier-1 step factored into `_prepare` (Amendment 18) — see
        allowed_values_for_script's docstring; this method's own behavior
        is unchanged."""
        key, result, needs_tier2 = self._prepare(
            "cond", evaluate_hide_tier1, script, variables, cache_id)
        if needs_tier2:
            # Pass the FULL variables dict, not a regex-filtered subset —
            # live-confirmed: a script checking
            # `fmod(OfVideoStreamingDevices_3_swSoln, 25) <> 0` had that
            # exact variable silently excluded from a filtered subset,
            # leaving it unable to reason about the one variable the
            # condition actually depends on.
            result = self._call_tier2("cond", script, variables, cache_id)
            self.stats["tier2" if result is not None else "unknown"] += 1
        return self._store(key, result)

    def _evaluate_llm_condition(
        self, script: str, variables: dict[str, str],
    ) -> bool | None:
        """Tier 2: ask the reason model whether a rule's condition fires."""
        try:
            from aryx import llm_runtime
            sys_p = ("You evaluate BigMachines BML rule-condition scripts. Given "
                     "the script and the current variable values, determine "
                     "whether the script's condition evaluates to true (the "
                     "rule fires) or false (it does not).")
            user_p = (f"Variables:\n{json.dumps(variables, indent=1)}\n\n"
                      f"Script:\n{script[:4000]}\n\n"
                      'Reply ONLY as JSON: {"condition_true": true} or '
                      '{"condition_true": false} or {"unknown": true} if it '
                      'cannot be determined.')
            # Tier-2 script interpretation genuinely needs reasoning (parse a
            # real BML script, hold its logic against current variable state,
            # commit to true/false/allowed-values) — moved from "menial" to
            # "answer" (ARYX_LLM_REASON_MODEL) since this is not the
            # lightweight term-extraction task "menial" is meant for.
            txt, _it, _ot = llm_runtime.chat("answer", sys_p, user_p)
            self._record_llm_usage(_it, _ot)
            s, e = txt.find("{"), txt.rfind("}")
            if s == -1 or e <= s:
                return None
            d = json.loads(txt[s:e + 1])
            if d.get("unknown"):
                return None
            val = d.get("condition_true")
            if isinstance(val, bool):
                return val
        except Exception as exc:  # noqa: BLE001 — LLM unavailable → unknown, not fatal
            raven_log("WARN", "P3", "ask.bml.tier2_eval_failed tier-2 BML LLM evaluation failed",
                      error_code="ARYX_ASK_BML_EVAL_FAILED", context={
                          "dependency_name": "llm_runtime", "operation": "condition",
                          "result": "failed", "error_class": type(exc).__name__, "attempt": 1})
            logger.debug("bml: tier-2 LLM condition-evaluation failed", exc_info=True)
        return None

    def _evaluate_llm_ask_worthy(
        self, context: str, variables: dict[str, str],
    ) -> bool | None:
        """Tier 2: ask the reason model whether a no-option, validation-rule
        -governed free-text attribute is worth proactively asking a sales
        rep about (see classify_ask_worthy above). `variables` is unused —
        this is a static per-attribute judgment, not a per-turn one; kept
        only to match _call_tier2's shared dispatch signature.
        """
        try:
            from aryx import llm_runtime
            sys_p = (
                "You classify BigMachines CPQ configuration attributes. "
                "Given an attribute's display label and its validation "
                "rule's message/script, decide whether a sales rep "
                "configuring a customer quote would need to actively "
                "decide and enter this value (a genuine quote-relevant "
                "decision, e.g. a quantity, domain name, or setting the "
                "customer cares about), versus an internal, advanced, or "
                "system-integration field the native UI would not "
                "normally prompt a rep for.\n\n"
                "Read the FULL script, not just the label — it often "
                "contains the real signal. If the script's condition only "
                "matters when ANOTHER attribute (not this one) is set to "
                "an enabling/advanced value (e.g. an '...advanced...', "
                "'...key...', or similar toggle-style attribute name "
                "equals YES/enabled), that is a strong sign this is a "
                "conditional, advanced, or hardware-integration field a "
                "rep would not be asked about by default — answer false "
                "unless the label itself is unambiguously a core, always-"
                "relevant business fact (e.g. a domain name, a device "
                "count, a service duration)."
            )
            user_p = (
                f"Attribute label and validation rule context:\n{context[:4600]}\n\n"
                'Reply ONLY as JSON: {"ask_worthy": true} or '
                '{"ask_worthy": false} or {"unknown": true} if it cannot '
                "be determined."
            )
            txt, _it, _ot = llm_runtime.chat("answer", sys_p, user_p)
            self._record_llm_usage(_it, _ot)
            s, e = txt.find("{"), txt.rfind("}")
            if s == -1 or e <= s:
                return None
            d = json.loads(txt[s:e + 1])
            if d.get("unknown"):
                return None
            val = d.get("ask_worthy")
            if isinstance(val, bool):
                return val
        except Exception as exc:  # noqa: BLE001 — LLM unavailable → unknown, not fatal
            raven_log("WARN", "P3", "ask.bml.tier2_eval_failed tier-2 BML LLM evaluation failed",
                      error_code="ARYX_ASK_BML_EVAL_FAILED", context={
                          "dependency_name": "llm_runtime", "operation": "ask_worthy",
                          "result": "failed", "error_class": type(exc).__name__, "attempt": 1})
            logger.debug("bml: tier-2 LLM ask-worthy classification failed", exc_info=True)
        return None
