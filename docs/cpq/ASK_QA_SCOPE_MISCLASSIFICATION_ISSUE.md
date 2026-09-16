# Ask Feature — Blanket "Outside What I Track" Refusal

**Status: Fixed.** Root cause identified in `src/aryx/api/ask_api.py`;
Option A (below) was implemented — a separate `_llm_classify_is_ask_in_scope`
classifier now gates the general Ask synthesis path, leaving
`_llm_classify_is_cpq_question` unchanged for CPQ routing. See
`fix/ask-scope-misclassification-devrv` (PR against `dev-rv`).

**Reported by:** g.sivasankari@giggso.com — user was getting the canned
refusal *"This question falls outside of what I track, which is limited to
product configuration and quoting."* for effectively every question asked
through Ask, including questions that should be answerable from tracked
graph data (example given: *"what are the entities present in suppliers?"*).

**Log evidence:** `aryx-api-1h.log` (1-hour capture, provided by user,
2026-07-29 11:26–12:24 UTC).

---

## 1. Symptom

User query through the Ask UI (`POST /ask/threads/message`):

> "what are the entities present in suppliers?"

Response:

> "This question falls outside of what I track, which is limited to
> product configuration and quoting."

User reports this same canned refusal came back for **every** question
asked in the session, not just off-topic ones.

## 2. What the log shows

Only one line in the captured hour shows the scope-check actually firing,
but it confirms the mechanism:

```
2026-07-29T11:56:05.173097212Z 2026-07-29 11:56:05,172 aryx.api.ask_api INFO
cpq_qa_scope: has_context=True for 'Show me the underlying records' -> is_cpq_relevant=False
```

`has_context=True` — the graph search DID resolve relevant entities for the
question — but the scope classifier still returned `is_cpq_relevant=False`,
which forces the refusal path regardless of what data was actually found.
This is the exact shape of the user's complaint: a question with real,
available data still gets blocked.

Ruled out during investigation (present in the log but not the cause):

| Observation | Location | Verdict |
|---|---|---|
| `POST /ask/threads/message` → `502 Bad Gateway`, `"ask run failed: Max pending queries exceeded"` | line 19433-19434, 12:01:37 | Separate issue — a queue-cap failure, unrelated to the scope refusal. Only one occurrence. |
| `data sources failed: could not resize shared memory segment ... No space left on device` | line 1922, 11:31:21 | Postgres disk-space warning against `data_api`, not on the Ask scope-check code path. |
| `openai_json: no JSON block found` / `_relate_isolated inference failed` | lines 2183-2184 | Ingestion-pipeline entity-relation inference, unrelated to `ask_api`'s classifier. |
| No `"ask failed: %s"` or LLM-exception log lines anywhere in the hour | — | Rules out the classifier throwing/erroring and falling back to `False` by exception. The `False` values seen are the classifier's genuine (mis)judgment, not a crash. |

## 3. Root cause

`src/aryx/api/ask_api.py:214` gates the **entire** Ask answer on a single
boolean:

```python
is_cpq_relevant = _llm_classify_is_cpq_question(question, workspace_id)
logger.info(
    "cpq_qa_scope: has_context=%s for %r -> is_cpq_relevant=%s",
    has_context, question, is_cpq_relevant,
)

if not is_cpq_relevant:
    empty_rule = (
        "- The question is not about product configuration, quoting, or "
        "enterprise data at all → say plainly that this is outside what "
        "you track (product configuration and quoting) ..."
    )
```

But `_llm_classify_is_cpq_question` (`ask_api.py:2030-2070`) was written for
a narrower purpose — deciding whether to route into the CPQ configurator —
and its own system prompt says so:

```python
sys = (
    "You classify whether a customer's message is asking to "
    "configure, quote, or order a product — a CPQ/configuration "
    "request — versus a general question or something unrelated. "
    "Bias toward \"quote\" whenever the message plausibly could be "
    "about ordering or configuring something, even if phrased "
    "unusually or missing an obvious trigger word; only classify as "
    "\"not_quote\" when you are confident it is NOT that at all."
)
```

This function answers exactly one question: *"is this an order/quote/
configure request?"* It has no notion of "general enterprise data
question." It is called from two places in `ask_api.py`:

- **Line 4820** — correct use: deciding whether to route the turn into the
  CPQ engine (`_run_cpq_turn`). Being biased toward "quote" here is
  intentional and documented (see the function's own docstring: a false
  "no" silently bypasses the CPQ engine's "never guess" discipline; a
  false "yes" only costs a clarifying question).
- **Line 214** — incorrect reuse: gating whether the *general* Ask
  synthesis step is allowed to answer at all, including from graph facts
  that have nothing to do with quoting (e.g. "what suppliers exist",
  "show me the underlying records").

Because the classifier only ever says "yes" for literal order/configure/
quote phrasing, any legitimate data-lookup question — which is most of
what a general "Ask" feature is for — gets `not_quote`, and the code at
line 220 then treats that `not_quote` as "this is off-topic," producing the
blanket refusal seen for nearly every question.

**In short:** one narrowly-scoped classifier is being asked two different
questions ("is this a quote intent?" vs. "is this in-scope for Ask at
all?"), and it was only ever built to correctly answer the first one.

## 4. Fix implemented

**Option A — split the classifier (implemented).** Kept
`_llm_classify_is_cpq_question` exactly as-is for CPQ routing (line 4820).
Added a second, separately-prompted classifier,
`_llm_classify_is_ask_in_scope`, for the line-214 scope check, whose system
prompt explicitly includes "questions about tracked enterprise/catalog
data" as in-scope, only rejecting things genuinely unrelated to the
product/catalog domain (weather, general chit-chat, unrelated topics).

The new classifier also fails **open**, not closed: a malformed LLM reply
or a call exception (both surfaced as `None` by the shared
`_llm_classify_intent_core` skeleton) is treated as in-scope, not
out-of-scope. Only an explicit `out_of_scope` classification rejects the
question — an unavailable classification provides no evidence either way,
and treating it as a rejection would silently reproduce this exact bug
under a different trigger (an LLM/parse failure instead of a genuine
"not_quote" judgment).

**Option B (not taken) — broaden the existing prompt.** Change
`_llm_classify_is_cpq_question`'s system prompt to also accept "a question
about enterprise data this system tracks" as a "quote"-equivalent
classification. Smaller change, but re-couples the CPQ-routing decision
and the Ask-scope decision again — risks reintroducing this same
confusion later if the two concerns diverge further. Option A was chosen
instead: the two call sites already have documented, different
tolerances for false positives/negatives (see the docstring at
`ask_api.py:2040-2050`); forcing them to share one classifier is what
caused this bug in the first place.

## 5. Attachments

- Raw log: `aryx-api-1h.log` (user-supplied, 1-hour capture, retained at
  `C:\Users\ajayr\Downloads\aryx-api-1h.log`).
- Relevant log lines quoted in §2 above.
- Code references: `src/aryx/api/ask_api.py:199-281` (scope-gated
  synthesis), `src/aryx/api/ask_api.py:2030-2070` (classifier),
  `src/aryx/api/ask_api.py:4815-4827` (CPQ-routing call site).
