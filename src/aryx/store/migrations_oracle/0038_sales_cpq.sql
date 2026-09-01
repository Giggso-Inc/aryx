-- Oracle equivalent of migrations/0038_sales_cpq.sql — sales chat threads and
-- durable MSI workflow state.
--
-- The aryx_mcp_token column additions from the Postgres migration are
-- already covered by 0034_mcp_sales_scope.sql (dev_oci added the same
-- purpose/allowed_tools/workspace_id/shay_workspace_id/expires_at columns
-- independently) -- not repeated here.
--
-- UUID -> VARCHAR2(36), JSONB -> native JSON (Oracle ADB 23ai).

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_sales_chat_thread (
    thread_id         VARCHAR2(36)             NOT NULL,
    actor_id          VARCHAR2(4000)           NOT NULL,
    workspace_id      NUMBER(19)               NOT NULL,
    shay_workspace_id VARCHAR2(36)             NOT NULL,
    created_at        TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT pk_aryx_sales_chat_thread PRIMARY KEY (thread_id),
    CONSTRAINT fk_sales_chat_thread_ws FOREIGN KEY (workspace_id)
        REFERENCES aryx_workspace (id)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_sales_chat_actor
    ON aryx_sales_chat_thread (actor_id, workspace_id, shay_workspace_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_sales_msi_workflow (
    workflow_id      VARCHAR2(36)             NOT NULL,
    confirmation_id  VARCHAR2(36)             NOT NULL,
    actor_id         VARCHAR2(4000)           NOT NULL,
    thread_id        VARCHAR2(36)             NOT NULL,
    status           VARCHAR2(64)             NOT NULL,
    current_step     VARCHAR2(4000)           DEFAULT '' '' NOT NULL,
    request_payload  JSON                     NOT NULL,
    identifiers      JSON                     DEFAULT ''{}'' NOT NULL,
    steps            JSON                     DEFAULT ''[]'' NOT NULL,
    error_message    VARCHAR2(4000)           DEFAULT '' '' NOT NULL,
    created_at       TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    updated_at       TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    completed_at     TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_aryx_sales_msi_workflow PRIMARY KEY (workflow_id),
    CONSTRAINT uq_sales_msi_confirmation UNIQUE (confirmation_id)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_sales_msi_actor_updated
    ON aryx_sales_msi_workflow (actor_id, updated_at DESC)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/
