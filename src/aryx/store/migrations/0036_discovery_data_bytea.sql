-- Switch aryx_discovery.data from JSONB to BYTEA (gzip-compressed JSON).
--
-- Real incident: a 33-file SL3500e tabular batch's serialized discovery
-- result (~732MB, inflated further by base64-encoding each file's raw
-- bytes to fit inside JSON) hit Postgres's own hard, non-configurable
-- limit on a single JSONB array's serialized size (268,435,455 bytes,
-- ~256MB) — psycopg.errors.ProgramLimitExceeded. That ceiling cannot be
-- raised by any setting; it is a fixed database-engine constant. A single
-- BYTEA value has no such array-size restriction (Postgres TOASTs it up
-- to ~1GB), and gzip-compressing the JSON before writing shrinks
-- text-heavy CSV payloads substantially on top of that headroom.
--
-- aryx_discovery only holds transient, awaiting-confirmation results for
-- in-flight discovery jobs (see 0035_discoveries.sql) — nothing depends
-- on any row surviving this migration, so existing rows are cleared
-- rather than converted (their JSON text is not gzip-compressed, so a
-- byte-for-byte cast would not be readable by the new get()/put() pair).
DELETE FROM aryx_discovery;

ALTER TABLE aryx_discovery ALTER COLUMN data DROP NOT NULL;
ALTER TABLE aryx_discovery ALTER COLUMN data TYPE BYTEA USING NULL;
ALTER TABLE aryx_discovery ALTER COLUMN data SET NOT NULL;
