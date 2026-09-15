-- aryx_rule_trace_entry.outcome was ported to Oracle as VARCHAR2(64), but
-- Postgres's original migrations/0037_rule_trace.sql declares it as
-- unbounded TEXT -- the Oracle port picked an arbitrary, too-small size.
-- Confirmed live: real rule-outcome descriptions (e.g. "allowed=[...]"
-- constraint summaries) run up to 138+ chars, causing every rule fire on
-- some catalogs to fail durable trace logging with ORA-12899, silently
-- (caught by record_fire's own try/except -- doesn't break the
-- conversation, but loses rule-trace audit data for that catalog
-- entirely).
--
-- Widened to VARCHAR2(4000), matching this same table's own `attr` column
-- precedent (also free-text, already sized at 4000). MODIFY to a larger
-- size is always safe against existing shorter data -- no data migration
-- needed.

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_rule_trace_entry MODIFY (outcome VARCHAR2(4000))';
EXCEPTION WHEN OTHERS THEN RAISE;
END;
/
