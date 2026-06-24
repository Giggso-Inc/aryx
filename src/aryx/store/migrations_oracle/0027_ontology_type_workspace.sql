-- Oracle ADB 23ai: multi-tenant ontology types.
-- Adds workspace_id, replaces UNIQUE(name) with UNIQUE(workspace_id, name).
-- The inline UNIQUE on name is system-named; discover and drop dynamically.
-- parent_type FK depends on the old UNIQUE — drop it first, then the UNIQUE.

DECLARE
  v_fk   VARCHAR2(200);
  v_uq   VARCHAR2(200);
BEGIN
  -- drop parent_type self-referential FK (depends on UNIQUE name)
  BEGIN
    SELECT constraint_name INTO v_fk
      FROM user_constraints
     WHERE table_name = 'ARYX_ONTOLOGY_TYPE'
       AND constraint_type = 'R'
       AND ROWNUM = 1;
    EXECUTE IMMEDIATE 'ALTER TABLE aryx_ontology_type DROP CONSTRAINT "' || v_fk || '"';
  EXCEPTION WHEN NO_DATA_FOUND THEN NULL;
  END;
  -- drop inline UNIQUE(name)
  BEGIN
    SELECT uc.constraint_name INTO v_uq
      FROM user_constraints uc
      JOIN user_cons_columns ucc ON uc.constraint_name = ucc.constraint_name
     WHERE uc.table_name      = 'ARYX_ONTOLOGY_TYPE'
       AND uc.constraint_type = 'U'
       AND ucc.column_name    = 'NAME'
       AND ROWNUM = 1;
    EXECUTE IMMEDIATE 'ALTER TABLE aryx_ontology_type DROP CONSTRAINT "' || v_uq || '"';
  EXCEPTION WHEN NO_DATA_FOUND THEN NULL;
  END;
END;
/

-- Add workspace_id (backfill existing rows to workspace 1)
ALTER TABLE aryx_ontology_type ADD (workspace_id NUMBER(19) DEFAULT 1 NOT NULL);

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_ontology_type ADD CONSTRAINT aryx_ontology_type_ws_name_key UNIQUE (workspace_id, name)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -2261 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_ontology_type_ws ON aryx_ontology_type (workspace_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
