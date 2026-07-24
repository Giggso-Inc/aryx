-- Additive indexes for source-scoped entity aggregation at catalog scale.
CREATE INDEX IF NOT EXISTS idx_landed_ws_source
    ON aryx_landed_record (workspace_id, source_system, source_dataset, id);

CREATE INDEX IF NOT EXISTS idx_member_ws_landed_entity
    ON aryx_entity_member (workspace_id, landed_record_id, entity_id);
