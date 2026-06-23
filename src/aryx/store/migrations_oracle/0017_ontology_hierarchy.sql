-- Oracle ADB 23ai: ontology type hierarchy (parent_type column).

ALTER TABLE aryx_ontology_type ADD (parent_type VARCHAR2(4000) REFERENCES aryx_ontology_type (name) ON DELETE SET NULL);
