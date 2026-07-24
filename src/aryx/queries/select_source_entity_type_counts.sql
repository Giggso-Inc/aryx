WITH source_map AS (
    SELECT source_key, source_system, source_dataset
    FROM jsonb_to_recordset(%(source_map)s::jsonb) AS mapped(
        source_key TEXT,
        source_system TEXT,
        source_dataset TEXT
    )
), entity_links AS (
    SELECT DISTINCT mapped.source_key, entity.id, entity.ontology_type
    FROM source_map mapped
    JOIN aryx_landed_record landed
      ON landed.source_system = mapped.source_system
     AND landed.source_dataset = mapped.source_dataset
     AND landed.workspace_id = %(workspace_id)s
    JOIN aryx_entity_member member
      ON member.landed_record_id = landed.id
     AND member.workspace_id = landed.workspace_id
    JOIN aryx_entity entity
      ON entity.id = member.entity_id
     AND entity.workspace_id = member.workspace_id
)
SELECT source_key, ontology_type, COUNT(*)
FROM entity_links
GROUP BY source_key, ontology_type
ORDER BY source_key, COUNT(*) DESC, ontology_type
