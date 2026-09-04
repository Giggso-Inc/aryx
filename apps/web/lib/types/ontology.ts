export interface OntologyType {
  name: string;
  attributes: string[];
  status?: "proposed" | "approved" | string;
  source?: string;
  parent_type?: string | null;
  instance_count?: number;
}

export interface OntologyRelationship {
  /** Backend row id — present only for declared relationship types
   *  (W2 / aryx_relationship_type). Subclass + entity-derived edges have none. */
  id?: number;
  name: string;
  source_type?: string;
  target_type?: string;
  count?: number;
}

export interface OntologyDoc {
  types: OntologyType[];
  relationships: OntologyRelationship[];
  entity_count?: number;
}

export interface Axiom {
  id: number;
  kind: string;
  type_name: string;
  payload: Record<string, unknown>;
}

export interface Rule {
  name: string;
  when_type: string;
  attribute: string;
  operator: string;
  value: string;
  action: string;
  label?: string;
  target_type?: string;
  target_name?: string;
  enabled: boolean;
}

export interface SurvivorshipPolicy {
  default_strategy?: string;
  attribute_strategies?: Record<string, string>;
  source_priority?: string[];
}

export interface OntologyVersion {
  id: number;
  workspace_id: number;
  label?: string;
  snapshot: unknown;
  created_at: string;
}

export interface OntologyChange {
  ts: string;
  kind: string;
  detail: string;
}
