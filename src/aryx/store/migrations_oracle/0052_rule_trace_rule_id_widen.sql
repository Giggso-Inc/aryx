-- aryx_rule_trace_entry.rule_id was ported to Oracle as VARCHAR2(128), but
-- Postgres's original migrations/0037_rule_trace.sql declares it as
-- unbounded TEXT -- the Oracle port picked an arbitrary, too-small size,
-- same root cause as 0044_rule_trace_outcome_widen.sql's `outcome` column.
-- Confirmed live, 2026-10-07 (ws 1267, Astro25Configdata): real rule names
-- run up to 165+ chars (e.g. "Restrict User to Deselect OTAP, Enhanced
-- Data and Group Services if System Wide Enhancement Bundle=..."),
-- failing durable trace logging with ORA-12899 on every fire of a
-- long-named rule -- 123 failed writes in a single turn, caught by
-- record_fire's own try/except (doesn't break the conversation, but
-- loses rule-trace audit data for every long-named rule on this catalog,
-- and adds a wasted DB round trip per failure on an already slow turn).
--
-- Widened to VARCHAR2(4000), matching this same table's own `attr` and
-- `outcome` columns (both free-text, already sized at 4000). MODIFY to a
-- larger size is always safe against existing shorter data -- no data
-- migration needed.

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_rule_trace_entry MODIFY (rule_id VARCHAR2(4000))';
EXCEPTION WHEN OTHERS THEN RAISE; END;
/
