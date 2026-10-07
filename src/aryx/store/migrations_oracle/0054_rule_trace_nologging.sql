-- Sets aryx_rule_trace_entry and aryx_rule_trace_session to NOLOGGING.
--
-- Does NOT speed up this table's actual write path: both tables are only
-- ever written via conventional-path INSERT (RuleTraceStore.append_entry /
-- append_entries_batch's cur.execute()/cur.executemany() with bind
-- variables -- src/aryx/store/rule_trace_store.py). Oracle's NOLOGGING
-- table attribute only skips redo generation for DIRECT-PATH operations
-- (INSERT /*+ APPEND */, CREATE TABLE AS SELECT, SQL*Loader direct path,
-- ALTER TABLE MOVE) -- conventional DML always generates full redo
-- regardless of this setting, since redo there also backs transaction
-- rollback/consistency, not just media recovery. Requested anyway
-- (2026-10-07 perf discussion) as a harmless, no-downside default for an
-- audit/trace table that doesn't need redo-logged recovery guarantees for
-- every byte -- it only matters if something later does a genuine
-- direct-path bulk load against these tables (a migration, an export/
-- import, a future SQL*Loader-style ingest), which none of today's code
-- does.
--
-- Confirmed live, 2026-10-07: this is a no-op on this ADB instance. Ran
-- the ALTER directly against both tables -- it completes with zero
-- errors, but SELECT logging FROM user_tables still reports 'YES'
-- immediately afterward for both, meaning the ADB doesn't even accept
-- the dictionary-level attribute change, not just "accepts it but
-- enforces logging anyway" (the usual FORCE LOGGING behavior). This
-- session's restricted user has no v$parameter access to confirm FORCE_
-- LOGGING directly, but the observed behavior is consistent with it.
-- Kept anyway as harmless, documented groundwork -- a correctness risk
-- only if a future reader mistakes it for an active optimization; the
-- comment above says plainly it isn't one, on this real workload or on
-- this ADB instance.

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_rule_trace_entry NOLOGGING';
EXCEPTION WHEN OTHERS THEN RAISE; END;
/

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_rule_trace_session NOLOGGING';
EXCEPTION WHEN OTHERS THEN RAISE; END;
/
