SELECT id, ontology_type, attributes
FROM (
    SELECT id, ontology_type, attributes,
           ROW_NUMBER() OVER (PARTITION BY ontology_type ORDER BY id) AS rn
    FROM aryx_entity
    WHERE workspace_id = %s
) ranked
WHERE rn <= %s
