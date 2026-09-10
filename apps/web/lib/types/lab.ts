export interface GroundingCitation {
  marker: number;
  entity_id: number;
  entity_name: string;
  entity_type: string;
  system: string;
  dataset: string;
  record_id: string;
}

export interface Grounding {
  grounded: boolean;
  entity_count: number;
  cited_count: number;
  source_count: number;
  score: number;
  citations: GroundingCitation[];
  uncited_entities: string[];
}

export interface AbVariant {
  label: string;
  grounded_in_ontology: boolean;
  answer: string;
  grounding: Grounding;
}

export interface AbScorecard {
  grounded: { on: boolean; off: boolean };
  citations: { on: number; off: number };
  source_records: { on: number; off: number };
  evidence_used: { on: number; off: number };
}

export interface AbResult {
  question: string;
  model: string;
  on: AbVariant;
  off: AbVariant;
  scorecard: AbScorecard;
}

export interface ReasonerCheck {
  axioms_checked: number;
  entities_scanned: number;
  violations: number;
  blocked: number;
}
