# CPQ Conversation Engine — Plain-Language Summary of Today's Work

This is a non-technical write-up of what was wrong and what was fixed today in
the CPQ (configure-price-quote) conversation engine — the part of Aryx that
carries on a back-and-forth conversation with a customer to build out a
product quote. No code, no file names, no technical jargon — just what the
problem was, why it mattered, and what changed.

---

## The Main Issue: The System Couldn't Tell When It Was Being Asked for a Quote

### The Problem

When a customer typed a message, the system had to make a first decision
before anything else could happen: *is this person asking me to configure or
quote a product, or are they asking something else entirely?*

Up to today, that decision was made by a very rigid method: the system
scanned the sentence for a short list of specific trigger words — things
like "quote," "configure," "radio," "5G," and a handful of others. If none
of those exact words appeared, the system assumed the customer was NOT
asking for a quote, and quietly handed the conversation off to a completely
different, more generic part of the system — one that isn't built to walk
a customer through a real product configuration at all.

This went wrong in two separate real cases discovered this session:

1. A customer asked for "APX Next **radios**" (plural). The trigger list
   only recognized the singular word "radio," so the plural form slipped
   through unnoticed, and the system failed to realize this was a genuine
   quote request.
2. A customer named a real product by its everyday name. The system's
   fallback check for product names only recognized internal, behind-the-
   scenes product codes — not the actual names a customer would naturally
   type — so it also failed to recognize a completely legitimate request.

In both cases, the customer's message silently went to the wrong part of
the system. The customer got a generic, conversational-sounding answer
instead of a real, accurate, step-by-step quote conversation — and nothing
in the system flagged that anything had gone wrong. This is a serious
problem because the accurate, careful quoting logic (which double-checks
real prices, options, and rules) was being bypassed entirely, in favor of a
more free-form assistant that can sound helpful but has no real
guardrails around what it says.

### Where the Fix Lives

The fix lives in the very first decision point of the conversation — the
"traffic control" step that decides, for every single message a customer
sends, whether to route it into the careful, rule-following quoting
conversation or into the general-purpose assistant. This is the earliest
possible point in the pipeline, before any actual quoting logic runs.

### What the Fix Does

Two things changed:

**First**, the immediate bugs were fixed — the plural "radios" is now
recognized just as well as "radio," and the fallback check now also looks
at real, customer-facing product names, not just internal codes.

**Second, and more importantly**, a smarter safety net was added underneath
the whole system. Previously, if the simple word-matching check found
nothing, the system just gave up and assumed "not a quote request." Now,
when that simple check comes up empty, the system takes one extra step: it
asks an AI model to read the sentence and make a judgment call — "does this
sound like someone trying to order, configure, or get pricing on a
product, even if they didn't use an obvious trigger word?" If the answer is
yes, the conversation is routed into the careful, accurate quoting flow
instead of being silently lost.

This extra step is deliberately used sparingly — it only kicks in when the
simple, fast check already failed to find anything, so it adds no delay at
all to the vast majority of messages that are recognized immediately. It
was tested against a range of real and made-up examples: genuine quote
requests with unusual phrasing were correctly caught and routed properly;
genuinely unrelated questions, and even ordinary questions about the data
in the system, were correctly left alone and NOT mistaken for quote
requests. The system was also deliberately tuned to lean toward giving the
customer the careful quoting experience whenever there's real doubt, rather
than risking another silent miss — because a customer wrongly denied the
proper quoting flow is a worse outcome than an ordinary question
occasionally getting an extra check.

A second, related improvement was made to how the system asks clarifying
questions once a customer IS in the quoting conversation. Previously, when
the system needed to ask the customer to disambiguate something — for
example, "there are two different settings both called 'Package,' which one
did you mean?" — it would show a flat, robotic list, sometimes even using
internal technical field names the customer has no way of understanding.
Now, the system composes a more natural, conversational question that
reflects back what the customer already told it (their country, the
product they're configuring, and so on) instead of asking them to repeat
themselves, and phrases the remaining question in a way a real person would
actually ask it. If anything goes wrong composing that more natural
question — for instance, if it accidentally left out one of the real
choices — the system automatically falls back to the older, plainer wording
rather than risk showing something incomplete or misleading. So the
worst-case outcome is exactly what customers experienced before; the
improvement only ever makes things better, never worse.

---

## Other Main Issues Fixed Today

**1. Quotes on a large, complex product were taking many minutes to
complete, sometimes appearing to hang entirely.**
Some products in the catalog have an enormous number of internal business
rules attached to them — far more than a typical product. Each time the
system needed help from the AI to work out one of these rules, it did so
one at a time, in a strict queue, and on the largest products this queue
could run into the hundreds. That made some configurations take upwards of
twenty-five minutes, which is not a workable experience for a live
conversation. Several improvements were made together: the system now asks
the AI multiple questions at once instead of one at a time wherever
possible, dramatically cutting the wait; a number of these business rules
turned out to follow a simple, repeatable pattern that the system can now
recognize and resolve instantly on its own, without needing to ask the AI
at all; a safety limit was added so that even in a worst-case scenario, one
single conversation turn cannot run away and consume unlimited time; and
finally, once the system has asked the AI to work out a particular rule, it
now remembers that answer permanently, so if the exact same situation ever
comes up again — even after a system restart — it does not have to ask the
AI a second time. Together, these changes make large, complex product
quotes dramatically faster and put a hard ceiling on the worst case.

**2. Customers were sometimes shown a confusing, overly technical question
they had no way of answering.**
After a customer finished a quote and asked to change one small detail
(for example, a compliance-related setting), the system would sometimes
respond by asking the customer to choose between two internal system field
names — names that only make sense to the people who built the product
catalog, not to an actual customer placing an order. Digging into why this
happened revealed that an existing safeguard — one that was supposed to
prevent exactly this kind of confusing question — had only ever been built
into the very first part of a conversation (getting the initial quote
started), and was never extended to cover the "make a change to an existing
quote" part of the conversation. So the protection worked perfectly the
first time through, but disappeared the moment a customer asked for any
follow-up change. That gap has now been closed, so the same protection
applies consistently, whether a customer is starting a fresh quote or
asking to adjust one that's already complete.

**3. A specific technical setting was quietly hiding a device-count
question the customer should have been able to answer.**
While investigating a customer's specific configuration, it became clear
that one particular field — the number of video streaming devices in a
security/compliance product — was correctly and intentionally hidden
whenever a certain compliance setting ("FedRamp required") was turned on,
because that combination genuinely doesn't need that field. That part was
working exactly as intended. However, tracing this further uncovered a
separate, smaller flaw in how the system reads one very common style of
internal business rule — one written as "if this condition is true, hide
the field; otherwise don't," but without spelling out the "otherwise" part
explicitly. The system was correctly handling the "hide it" half of that
instruction but not confidently recognizing the unwritten "otherwise, don't
hide it" half, which meant it sometimes couldn't make a confident decision
on its own and needed extra, unnecessary help from the AI to work out
something it should have been able to figure out by itself. That specific
gap was corrected, so this very common style of rule is now handled
instantly and confidently every time, without needing outside help — and
end-to-end confirmation that this specific customer's field now appears
correctly under the right conditions was still in progress when this
summary was written.

---

## In Short

Today's work centered on making the quoting conversation more reliable at
its two most important moments: **deciding whether a customer is actually
asking for a quote in the first place**, and **asking the customer clear,
natural, understandable questions once they are**. Alongside that, a real
performance problem on the system's largest, most complex product was
substantially fixed, and two more specific, real customer-facing confusions
were found and corrected. Every change was tested against the existing
safety checks that already protect this system, and none of those checks
were weakened in the process.
