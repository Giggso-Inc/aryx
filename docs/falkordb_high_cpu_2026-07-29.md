# FalkorDB Slowness — What Happened, Why, and How to Fix It

**Date of incident:** 2026-07-29
**Affected service:** `aryx-falkordb-1` (the graph database behind Aryx)
**Severity:** High — the database ran at 185–199% CPU for about an hour
**Status:** Root causes verified against the actual code. Fixes below are proposed, not yet applied.

---

## In plain English

Someone kicked off a large data import (think: uploading a big spreadsheet-like file so the system could "learn" about a customer's product catalog). That import alone was heavy enough to max out the database. On top of that, two smaller problems made things worse:

1. Some of the data being imported had names the database *can't store safely as-is*, so the system was throwing away those pieces and writing a warning message for every single one — thousands of them, all at once.
2. While the import was still running, people using the app triggered a few *very* expensive "show me everything" queries against the exact same database, competing for the same CPU.

None of this caused data loss or an outage — it caused things to be **slow** for about an hour while the import was in progress. The fixes below stop it from happening again, and make future imports safer even if someone runs one during business hours by accident.

---

## The problem, in one sentence

**One big import + two smaller inefficiencies all hit the same database at the same time, and none of them were slowed down or isolated from each other.**

---

## Root Cause #1 — The import itself (the main cause, ~80% of the load)

**What happened:** A bulk import job loaded a large configuration file into the system —132,449 new records and 540,215 relationships between them, all for one customer workspace.

**Why it maxed out the CPU:** The import writes data in small batches, one after another, and each batch is a moderately expensive database operation (40–95 milliseconds each). That doesn't sound like much, but multiply it by thousands of batches back-to-back with no pauses, and the database has no idle time to catch its breath — CPU usage stays pinned near its ceiling for the entire ~50 minutes the import runs.

Even after the import finished, the database kept working hard for a few more minutes doing routine housekeeping (rebuilding lookup indexes and saving everything safely to disk) — this is normal and expected after any large import, not a bug.

**Is this a bug?** Not exactly — it's a **missing safety net**. The import doing real work at high CPU is expected. What's missing is anything that (a) warns people before it happens, or (b) slows the import down / schedules it for a quiet time so it doesn't compete with people actively using the app.

---

## Root Cause #2 — Bad data caused a flood of warning messages

**What happened:** Database "labels" (think: category tags, like `Person` or `Product`) have strict naming rules — no spaces, must start with a letter. One of the imported categories was named:

> `Svx Video Remote Speaker MicrophoneBmConfigLayoutAttrProp`

That name has spaces in it, so it breaks the naming rule.

**What the code actually does today** (verified in `src/aryx/graph/falkor_store.py`, function `_safe_labels`):

```python
if not _LABEL_RE.match(raw):
    logger.warning("dropping invalid label %r (not a Cypher identifier)", raw)
    continue
```

In plain terms: when the system sees a bad label, it **throws that piece of data away** and writes a warning to the log. During this import, that happened thousands of times in a row — which means:
- Thousands of tiny pieces of data were silently lost instead of imported.
- Thousands of log lines were written in a burst, adding extra load and burying other, more useful log messages underneath the noise.

**Is this a bug?** Yes — losing data silently (even "just" a bad label) is worse than fixing the name and keeping the data.

---

## Root Cause #3 — A few very expensive "show everything" queries ran at the same time

While the import was running, people browsing the app triggered some database lookups that turned out to be far more expensive than they look:

| What the query does | How long it took |
|---|---|
| "Show me a sample of the graph to browse" | **8.5 seconds** |
| Part of the import itself, writing relationships | 4.9 seconds |
| "List every distinct relationship type in the graph" | 0.86 seconds |
| "Show me up to 2000 records of this type" | 0.145 seconds |

**Why the 8.5-second one is so slow:** it's used by the app's graph-browsing feature (verified in `src/aryx/graph/reader.py`, function `subgraph()`). To build a preview, it fetches the **full detail** of every matching record — not just the id and name, but every single field — before trimming the results down to a small preview list. On a graph with over half a million relationships, fetching full detail for far more records than are actually shown wastes a huge amount of work. It also does this once for every distinct relationship type in the graph — so the more variety of relationships, the more of these expensive lookups run back-to-back.

**Why the 0.86-second one matters even though it looks fast:** it's the query that lists all relationship types (verified at `src/aryx/graph/reader.py` lines 100 and 238) — it has to scan the *entire* set of 540,215 relationships every single time it's called, even though the answer barely ever changes between imports. Calling it often, or from a page that refreshes automatically, adds up.

**Is this a bug?** Yes — both queries do more work than the feature actually needs.

---

## What actually fixed it, on the day

Nothing needed to be manually fixed to stop the incident — it resolved itself once the import finished and the database completed its normal post-import housekeeping. The team confirmed:
- The import genuinely finished successfully (all 132,449 records + 540,215 relationships written).
- The database already had the index it needed for relationship lookups, so that wasn't a missing piece.

The fixes below are about **preventing this from being disruptive next time**, not about anything that was broken and needed emergency repair.

---

## Recommended Fixes

### Fix 1 — Don't throw away data with a bad name; rename it instead

**File:** `src/aryx/graph/falkor_store.py`, function `_safe_labels`

Instead of dropping a label that breaks the naming rule, clean it up so it's safe to store, and keep a note that it was renamed:

```python
import re

_LABEL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")  # already exists in this file

def sanitize_label(label: str) -> str:
    """Turn any string into a safe label name instead of discarding it."""
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", label)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"_{cleaned}"   # labels can't start with a digit either
    return cleaned
```

> **Note:** a naive "replace bad characters with `_`" fix isn't quite enough on its own — the naming rule also says a label can't *start* with a digit (e.g. a label like `"3D Printer"` would sanitize to `"3D_Printer"`, which is still invalid). The version above handles that case too, so it's safe for names we haven't seen yet, not just today's example.

Then replace the current "drop it" behavior with "sanitize it and keep going":

```python
# Before — silently loses the data
logger.warning("dropping invalid label %r (not a Cypher identifier)", raw)
continue

# After — keeps the data under a safe, renamed label
sanitized = sanitize_label(raw)
logger.warning("sanitizing invalid label %r -> %r", raw, sanitized)
out.append(sanitized)
```

---

### Fix 2 — Stop fetching full detail when only a preview is needed

**File:** `src/aryx/graph/reader.py`, function `subgraph()`

This function currently asks the database for every field of every matched record, for every relationship type, before trimming down to a small sample. Instead, it should only ask for the small set of fields the preview actually displays (id, type, name), and only fetch full detail later, if and when a person clicks into a specific record.

This turns an "expensive for everyone, all the time" query into a "cheap most of the time, expensive only when someone actually needs the detail" query.

---

### Fix 3 — Stop recalculating the same answer over and over

**File:** `src/aryx/graph/reader.py` (the `"MATCH ()-[r:REL]->() RETURN DISTINCT r.name ORDER BY r.name"` query, used in two places)

This query answers "what kinds of relationships exist in this workspace?" — an answer that only changes when new data is imported. Today it re-scans the entire graph every time it's asked. Instead:

- Calculate it once, right after an import finishes, and save the answer.
- Reuse the saved answer for every request until the next import.
- Never call it on a timer / auto-refresh from the UI — only when something has actually changed.

---

### Fix 4 — Keep heavy "browse everything" features out of the way during an active import

There's currently nothing stopping someone from browsing the graph UI for a workspace while a big import into that *same* workspace is still running — which is exactly what added extra load during this incident. Options, roughly in order of effort:

- Simplest: show a friendly "this workspace is being updated, check back in a few minutes" message on the browse page while an import job for that workspace is active.
- More robust: have the browse endpoints politely decline (with a clear "import in progress" response) while a matching import job is active, instead of running the expensive query anyway.

---

## Ingestion Pipeline — Broader Bottleneck Investigation

The fixes above are about *this specific incident*. This section looks wider: is there anything in the ingestion pipeline itself (the process that turns an uploaded file into graph data) that's slower than it needs to be, in general — not just on the day of the incident? Verified directly against the code, not assumed.

### What "good" already looks like here

Worth saying up front: the team already found and fixed a much bigger version of this exact class of problem before. A note left in the code (`falkor_store.py`, in the function that wipes and rebuilds a workspace's graph) describes an earlier incident where **missing database indexes** made every single write get slower than the last one as the graph grew — on an 83,000-record workspace, that alone caused **69 of 70 minutes** in the write stage. That's already fixed: the three indexes that matter (on entity ID, on the internal "source" record, and on relationship names) are now created automatically at the start of every full import. The big bulk-write functions also already batch hundreds of records into one request instead of one request per record, which was measured at roughly **8x faster** than writing one at a time. Good foundation — the two findings below are gaps in that same standard, not a wholesale rewrite.

### Bottleneck A — "small update" imports don't use the fast path the "full import" ones do — FIXED

**Where:** `src/aryx/project.py`, function `project_incremental()` (used for day-to-day small updates — e.g. someone edits a few rows — as opposed to a brand-new full import).

There are two ways new data gets written into the graph:
- **`project_graph()`** — used for a full, from-scratch import. This one already uses the fast, batched write path described above.
- **`project_incremental()`** — used for small, everyday updates to data that's already been imported. This one writes every changed record **one at a time**, in a loop — the same slower pattern that was already proven to be much slower for full imports.

In plain terms: the fast lane exists and works, but the *most commonly used* road (small daily updates, which happen far more often than big one-time imports) isn't using it. On a small update this is barely noticeable. On a workspace where many rows change at once (e.g. a source system pushes a large daily batch of changes), this path would hit the exact same kind of slowdown a full import would — just via a different door.

**Fix applied:** `project_incremental()` now collects its changed entities and provenance records into a list first, then calls the same batched `add_entities_batch()` / `add_provenance_batch()` functions `project_graph()` already uses, instead of writing them one by one. (Relationship writes in this same function already did this correctly — only entities and provenance needed the change.) Falls back to the original one-row-at-a-time behavior automatically if a graph store doesn't support the batch methods, so nothing else needed to change.

3 new tests added (`tests/test_graph_projection_performance.py`): confirms the batched path is used (UNWIND queries, not per-row MERGE) and produces the same counts as before; confirms tombstone handling and watermark advancement are unaffected; confirms the fallback path still works for a graph store without batch support. All 27 tests in the affected file pass.

**One honest caveat found while implementing this:** `project_incremental()` (and its dispatcher, `project_auto()`, which picks incremental vs. full based on how much of the workspace changed) aren't currently called from anywhere in the live ingestion pipeline (`orchestrate.py` and the API routes only call `project_graph()` directly) — they appear to be built for a planned "G8 mode=auto" incremental-update flow that isn't wired up yet. The fix is still correct and ready for whenever that gets connected, but it won't change today's production behavior until it is.

### Bottleneck B — a full import always rewrites everything, even if almost nothing changed

**Where:** `src/aryx/project.py`, function `project_graph()`, and `src/aryx/graph/falkor_store.py`, function `clear()`.

Every full import starts by **deleting that workspace's entire graph** and writing it all back from scratch — every entity, every relationship, every provenance link — even if only a small fraction of the underlying data actually changed since the last import. This is safe and simple (nothing gets left over or out of sync), but it means the *cost* of a full import scales with the size of the *whole workspace*, not with the size of the *change*.

This isn't a bug — it's a reasonable, deliberate design choice for a "start clean" operation, and the existing `project_incremental()` path (Bottleneck A above) is exactly the tool meant to avoid paying this cost for small changes. The practical takeaway is less "fix the code" and more "use the right tool": routine updates should go through the incremental path (once Bottleneck A is fixed, that path will actually be fast), and the full wipe-and-rebuild path should be reserved for genuinely new imports or full re-syncs — not run routinely on a large, mostly-unchanged workspace.

### What wasn't found to be a bottleneck (checked, and ruled out)

- **Entity matching/deduplication** (deciding whether an imported row is a new entity or matches one already known) — this already went through its own dedicated performance fix in an earlier round of work and wasn't re-investigated here.
- **The batch size used for writes (500 records per database round-trip)** — reasonable and already in active use; not a bottleneck at the scale seen in this incident.
- **Cross-table "dimension" linking** (a step that connects records across different tables that share a common value, like the same state or category) — this does compare pairs of columns to each other, which sounds expensive, but it only compares the *distinct columns* found across the whole import (typically a few dozen to a few hundred), never individual records — so it doesn't scale with the number of rows imported and isn't a concern at this incident's scale.

---

## Timeline of the incident

| Time | What happened |
|---|---|
| ~10:40 | Import job starts for the affected workspace |
| 11:09 | First stage of the import (29 files) finishes |
| 11:28 | High CPU usage is noticed |
| 11:35 | All 132,449 records finish importing |
| 11:35 | All 540,215 relationships finish importing |
| ~11:50 | Database finishes its post-import housekeeping; CPU returns to normal |

---

## How to prevent this going forward

1. **Run large imports outside business hours** when possible, so they don't compete with people actively using the app.
2. **Add a simple "import in progress" lock** so heavy browse features back off automatically instead of piling on more load (Fix 4).
3. **Fix the label-naming problem** so bad data gets safely renamed instead of silently thrown away, and so future imports don't flood the logs (Fix 1).
4. **Stop recalculating answers that rarely change** — cache them instead, and only refresh after an import (Fix 3).
5. **Make the graph-browse feature ask for only what it needs**, not everything, on every request (Fix 2).
6. ~~Make small, everyday updates use the same fast batched writes as full imports~~ — **done** (Bottleneck A).
7. **Wire up the incremental path and route routine updates through it** instead of a full wipe-and-rebuild (Bottleneck B) — the code is ready (Bottleneck A's fix applies to it), it just isn't called from the live pipeline yet.

None of these fixes have been applied to the code yet — this document is the analysis and the plan. Let us know which of these you'd like implemented first.
