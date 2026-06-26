-- Aryx attribute schema column for ontology types.
-- Stores per-column semantic metadata wired from aryx_field_tag after each run.
ALTER TABLE aryx_ontology_type
    ADD COLUMN IF NOT EXISTS attribute_schema JSONB DEFAULT '{}'::jsonb;
