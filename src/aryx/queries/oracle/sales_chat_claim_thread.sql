-- Oracle equivalent of sales_chat_claim_thread.sql. Postgres's
-- INSERT ... ON CONFLICT (thread_id) DO NOTHING ... RETURNING atomically
-- inserts-if-absent and hands back the winning row in one round trip --
-- Oracle has no ON CONFLICT. MERGE is the race-safe equivalent (atomic,
-- no exception handling needed), but unlike RETURNING it produces no
-- resultset readable via a normal fetchone() -- chat_store.py's
-- claim_thread() must always follow this with sales_chat_select_thread
-- on Oracle (not just when this query's fetchone() is None, since it
-- always is), to fetch the winning row either way.
-- Params in order: :1=thread_id :2=actor_id :3=workspace_id
-- :4=shay_workspace_id -- oracledb binds positionally by occurrence
-- order, not by :N label (see ask_thread_store.py's touch_thread_params
-- comment for the same caveat), so each bind is used exactly once here.
MERGE INTO aryx_sales_chat_thread t
USING (
    SELECT :1 AS thread_id, :2 AS actor_id, :3 AS workspace_id,
           :4 AS shay_workspace_id
    FROM dual
) s
ON (t.thread_id = s.thread_id)
WHEN NOT MATCHED THEN
    INSERT (thread_id, actor_id, workspace_id, shay_workspace_id)
    VALUES (s.thread_id, s.actor_id, s.workspace_id, s.shay_workspace_id)
