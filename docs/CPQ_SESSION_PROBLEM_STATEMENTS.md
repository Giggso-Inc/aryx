# CPQ Problem Statements — Today's Session

Issues identified today, workspace 19 (SVX / APX Next Enhanced / SL3500e catalogs). Problem statements only.

## 1. "Select Model" panel missing from the conversation and payload
The native UI's "Select Model" radio group (SVX Mic / SVX Mic TAA / SVX Mic UL) never appeared as a question, and its options were invisible to the engine entirely (loaded as an empty list) — even though the attribute itself was present in the graph.

## 2. Missing menu options traced to a graph-ingestion gap
The "Select Model" attribute had real, correctly-linked option data in Postgres (4 rows, properly foreign-keyed), but zero corresponding edges in the FalkorDB graph — the two data stores had fallen out of sync for this attribute, so the graph-only lookup path found nothing.

## 3. Same ingestion gap present at much larger scale in SL3500e
The identical "real data in Postgres, no graph edge" pattern also affected SL3500e's `ultimateDestinationCountry` attribute (and others) — but at a much larger scale (thousands of menu rows across the catalog), not just one isolated attribute.

## 4. Bulk lookup silently truncated on large catalogs
The initial fix for #2 fetched all of a catalog's menu items in a single query, but the underlying data-access call silently caps the number of rows returned per call. SL3500e has more menu items than that cap, so the fix itself missed later items (including the real country list for `ultimateDestinationCountry`) without any error or warning.

## 5. Duplicate graph entities for the same real attribute collapsed into one
SL3500e's `ultimateDestinationCountry` attribute was ingested twice under two different internal graph identifiers, both pointing to the same real underlying record. Code that mapped "real record → graph entity" assumed a 1-to-1 relationship, so the second entity silently overwrote the first and only one of the two ended up with usable data.

## 6. Test doubles didn't stay in sync with the real data-access interface
After the data-access interface gained a new parameter (to support fixing #4), several test-only "fake" implementations of that same interface did not have the new parameter, so they raised errors when exercised — a shape mismatch between production and test code rather than a functional bug.

## 7. Unrelated, pre-existing failures observed during verification (not caused by today's changes)
Running the full test suite surfaced a set of failures unrelated to today's CPQ work (Oracle/OCI backend tests, port-swap tests, scalability-fixture tests, and two product-mention detection tests) — confirmed present independent of today's changes and out of scope for this fix set.
