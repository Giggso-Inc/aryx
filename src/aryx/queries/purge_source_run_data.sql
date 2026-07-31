UPDATE aryx_job
SET run_id = NULL
WHERE workspace_id = %(workspace_id)s
  AND run_id IN (
    SELECT run_id
    FROM aryx_run
    WHERE workspace_id = %(workspace_id)s
      AND source_system = %(source_system)s
      AND source_dataset = %(source_dataset)s
  );
UPDATE aryx_job_archive
SET run_id = NULL
WHERE run_id IN (
    SELECT run_id
    FROM aryx_run
    WHERE workspace_id = %(workspace_id)s
      AND source_system = %(source_system)s
      AND source_dataset = %(source_dataset)s
  );
DELETE FROM aryx_adjudication
WHERE workspace_id = %(workspace_id)s
  AND run_id IN (
    SELECT run_id
    FROM aryx_run
    WHERE workspace_id = %(workspace_id)s
      AND source_system = %(source_system)s
      AND source_dataset = %(source_dataset)s
  );
DELETE FROM aryx_field_profile
WHERE run_id IN (
    SELECT run_id
    FROM aryx_run
    WHERE workspace_id = %(workspace_id)s
      AND source_system = %(source_system)s
      AND source_dataset = %(source_dataset)s
  );
DELETE FROM aryx_field_tag
WHERE run_id IN (
    SELECT run_id
    FROM aryx_run
    WHERE workspace_id = %(workspace_id)s
      AND source_system = %(source_system)s
      AND source_dataset = %(source_dataset)s
  );
DELETE FROM aryx_run_stage
WHERE run_id IN (
    SELECT run_id
    FROM aryx_run
    WHERE workspace_id = %(workspace_id)s
      AND source_system = %(source_system)s
      AND source_dataset = %(source_dataset)s
  );
DELETE FROM aryx_match_edge
WHERE run_id IN (
    SELECT run_id
    FROM aryx_run
    WHERE workspace_id = %(workspace_id)s
      AND source_system = %(source_system)s
      AND source_dataset = %(source_dataset)s
  );
DELETE FROM aryx_block_done
WHERE run_id IN (
    SELECT run_id
    FROM aryx_run
    WHERE workspace_id = %(workspace_id)s
      AND source_system = %(source_system)s
      AND source_dataset = %(source_dataset)s
  );
DELETE FROM aryx_block_member
WHERE run_id IN (
    SELECT run_id
    FROM aryx_run
    WHERE workspace_id = %(workspace_id)s
      AND source_system = %(source_system)s
      AND source_dataset = %(source_dataset)s
  );
DELETE FROM aryx_schema_mapping
WHERE run_id IN (
    SELECT run_id
    FROM aryx_run
    WHERE workspace_id = %(workspace_id)s
      AND source_system = %(source_system)s
      AND source_dataset = %(source_dataset)s
  );
DELETE FROM aryx_run
WHERE workspace_id = %(workspace_id)s
  AND source_system = %(source_system)s
  AND source_dataset = %(source_dataset)s;
