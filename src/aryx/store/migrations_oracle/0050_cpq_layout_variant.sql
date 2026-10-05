-- Oracle equivalent of migrations/0050_cpq_layout_variant.sql -- see that
-- file for the rationale. NOT NULL sentinel default ('' would be NULL here).
-- The literal must equal DEFAULT_LAYOUT_VARIANT in aryx/cpq/layout_source.py.

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_cpq_layout_file ADD (variant VARCHAR2(256) DEFAULT ''default'' NOT NULL)';
-- ORA-01430: column already exists (re-run).
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'DROP INDEX idx_aryx_cpq_layout_ws_catalog';
-- ORA-01418: index does not exist (already dropped).
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1418 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE UNIQUE INDEX idx_aryx_cpq_layout_ws_catalog_variant
    ON aryx_cpq_layout_file (workspace_id, catalog_prefix, variant)';
-- ORA-00955 / ORA-01408: already created (re-run).
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 AND SQLCODE != -1408 THEN RAISE; END IF;
END;
/
