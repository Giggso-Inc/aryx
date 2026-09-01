# Why the engine never asks "which Product?" — root cause

**Status:** Analysis only. No code changed per explicit instruction.
**Source analyzed:** `apx_payload.json` (repo root, untracked) — a full final
`configData` payload for an APX Next (`aSTRO25_bom`) order.
**Reference:** `src/aryx/cpq/engine.py`, `evaluate_rules_loop` (~lines
4210–4400).

## The observation

In `apx_payload.json`, `productSelectionProduct_all` ends up filled with a
specific value, with no visible turn in the conversation where the customer
was ever asked to choose it:

```json
"hWVersion_astro": {"value": "NEXT ENHANCED LTE PLUS 5G", "displayValue": "APX NEXT (4G LTE+5G)"},
"productSelectionProduct_all": {"value": "APX NEXT Enhanced", "displayValue": "APX NEXT Enhanced"}
```

`productSelectionProduct_all` is deliberately designed to **always ask** —
it is one of a small set of catalog-wide attributes (325+ product-line
codes spanning every product family) where a blind "first option" guess has
been live-confirmed to silently pick the wrong product line entirely (e.g.
a prior incident where an APX NEXT quote's Product silently resolved to
`APX6500`). That protection lives in `engine.py`'s `is_decision_attr`
computation:

```python
is_decision_attr = (
    any(dk in vn_flat for dk in _DECISION_REQUIRED_KEYS)
    or (
        vn == "productSelectionProduct_all"
        and vn not in (skip_always_ask or ())
    )
    ...
)
```

So on paper, this attribute should never be silently filled — it should
always surface a question, unless the caller explicitly opted it out via
`skip_always_ask`.

## Root cause: a different, earlier branch bypasses that protection entirely

`is_decision_attr` is only consulted **after** an earlier, unconditional
branch has already had a chance to act (engine.py ~line 4286–4317):

```python
if not value and attr.options:
    allowed_for_attr = (
        set(constrained_opts.get(attr.entity_id, []))
        if constrained_opts else None
    )
    valid_opts = [
        o for o in attr.options
        if _valid(o.item_value)
        and (allowed_for_attr is None or o.item_value in allowed_for_attr)
    ]
    if len(valid_opts) == 1 and attr.entity_id not in user_answered_dropped_ids:
        # Exactly one choice — auto-fill, no user decision needed.
        value = valid_opts[0].item_value
        display = valid_opts[0].display_name
    elif (
        is_governed and not is_decision_attr and valid_opts
        ...
```

This "exactly one valid option → auto-fill" branch has **no
`is_decision_attr` check at all**. It only checks whether the
rule-constrained candidate list (`allowed_for_attr`) has narrowed to a
single value. `is_decision_attr` is only ever consulted in the `elif`
below it — which is unreachable once the `if` branch above has already
matched and filled the value.

### Why the candidate list narrows to exactly one here

The rule `restrictAPXNextProductSelectionBasedOnHWVersionSelection`
("Restrict APX Next Product Selection based on HW Version selection")
constrains `productSelectionProduct_all` based on `hWVersion_astro`:

```
if (hWVersion_astro == "NEXT ENHANCED LTE PLUS 5G")
    allow: APX NEXT ENHANCED | APX NEXT XE 4G LTE PLUS 5G
else
    allow: APX NEXT INTL FED | APX NEXT XN SINGLE BAND | ... (8 values)
```

On its own, that rule narrows the list to **two** values, not one — that
alone would not trigger the auto-fill branch. But `constrained_opts`
reflects the **combined intersection of every active constraint rule**
touching this attribute in the same evaluation pass, not just this one
rule. Other filled attributes in this same payload — `modelSelectionbaseModel_astro`
(`H45TGU9PW8AN`), the frequency/band selections, `packages_astro`
(`GOLD`), etc. — feed their own constraint rules against
`productSelectionProduct_all`'s shared option list. Once the intersection
of every active constraint is taken, only one of the two HW-Version-gated
candidates (`APX NEXT ENHANCED`) remains compatible with everything else
already answered — collapsing `valid_opts` to exactly one entry before
`is_decision_attr` is ever consulted.

## Why this isn't necessarily wrong, but is worth flagging

Functionally, the end value is very likely correct — it's the one product
line consistent with everything else the customer selected. The concern is
purely about **transparency**: the customer never saw or confirmed the
choice, even though this exact attribute was hardened specifically so that
a Product selection is never silently made. The "always ask"
protection and the "exactly one option → auto-fill" shortcut are two
separate code paths that were never made mutually aware of each other —
the second one was written first (an efficiency/UX shortcut for any
genuinely single-option attribute) and the `is_decision_attr` carve-out for
`productSelectionProduct_all` was added later, further down, without also
excluding this earlier branch.

## Suggested (not implemented) fix shape

Add `and not is_decision_attr` (or an equivalent narrower guard scoped to
`productSelectionProduct_all`/`is_decision_attr`) to the `len(valid_opts) == 1`
branch's condition, so a decision-required attribute always surfaces a
confirmation question — even when only one candidate remains — instead of
silently auto-filling. This would need to preserve the resume-prompt UX
already described in that branch's own comment (telling the customer the
one remaining valid option) rather than just asking a bare, unscoped
question.
