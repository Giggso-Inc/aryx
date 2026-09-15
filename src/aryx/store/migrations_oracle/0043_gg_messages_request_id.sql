-- Oracle equivalent of migrations/0033_ask_thread_messages.sql's follow-up
-- ALTER TABLE. GG_MESSAGES on Oracle carried over the full base shape from
-- Postgres's original CREATE TABLE gg_messages (migrations/0028_shay_skin.sql,
-- all 19 columns present, confirmed via user_tab_columns) but never got this
-- later, separate ALTER TABLE ADD COLUMN request_id -- whatever ported the
-- table missed the follow-up migration. Confirmed live: no REQUEST_ID column,
-- no idx_gg_messages_thread_sequence index, on the running Oracle ADB
-- instance (only the PK index existed).
--
-- The partial UNIQUE index Postgres also has here
-- (uq_gg_messages_thread_request_type, UNIQUE (thread_id, request_id,
-- message_type) WHERE request_id IS NOT NULL, enforcing per-thread request
-- idempotency) is deliberately NOT ported in this file. Oracle has no
-- WHERE-clause-qualified CREATE UNIQUE INDEX; Oracle's own equivalent
-- (relying on NULL values never colliding in a composite unique index) needs
-- verification against real data before asserting it here -- follow-up, not
-- bundled with this fix.

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE gg_messages ADD (request_id VARCHAR2(36))';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_gg_messages_thread_sequence
    ON gg_messages (thread_id, sequence_number)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 AND SQLCODE != -1408 THEN RAISE; END IF;
END;
/
