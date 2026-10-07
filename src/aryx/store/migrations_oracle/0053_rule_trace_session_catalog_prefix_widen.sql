-- aryx_rule_trace_session.catalog_prefix was ported to Oracle as
-- VARCHAR2(64), but Postgres's original migrations/0037_rule_trace.sql
-- declares it as unbounded TEXT -- same root cause as 0044's `outcome`
-- and 0052's `rule_id` on this same table family's sibling table,
-- flagged by PR #454's review as "the likeliest next one" before it
-- becomes a third incident-by-incident fix.
--
-- aryx_cpq_layout_file.catalog_prefix (0046_cpq_layout_files.sql) already
-- uses VARCHAR2(256) for this identical semantic value (a raw, filename-
-- derived stem) -- widened to match that precedent rather than inventing
-- a third size for the same kind of string. Not yet a live failure
-- (confirmed live, 2026-10-07: current max catalog_prefix length in use
-- is 35 chars), but the same unbounded-TEXT-vs-arbitrary-VARCHAR2 gap
-- that already caused two real ORA-12899 incidents in this table family.
--
-- MODIFY to a larger size is always safe against existing shorter data --
-- no data migration needed.

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_rule_trace_session MODIFY (catalog_prefix VARCHAR2(256))';
EXCEPTION WHEN OTHERS THEN RAISE; END;
/
