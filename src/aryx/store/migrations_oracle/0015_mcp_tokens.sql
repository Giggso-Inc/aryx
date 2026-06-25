-- Oracle ADB 23ai: MCP bearer tokens.
-- Partial index (WHERE revoked_at IS NULL) replaced with a standard index.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_mcp_token (
    id            NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    label         VARCHAR2(4000) DEFAULT '' '' NOT NULL,
    token_hash    VARCHAR2(4000) NOT NULL UNIQUE,
    prefix        VARCHAR2(100) NOT NULL,
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    last_used_at  TIMESTAMP WITH TIME ZONE,
    revoked_at    TIMESTAMP WITH TIME ZONE
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_mcp_token_hash ON aryx_mcp_token (token_hash)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;

/