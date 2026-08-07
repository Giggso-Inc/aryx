// Wire types — these mirror the FastAPI JSON contract, hand-written for V1.
// Later: regenerate from /openapi.json at build time. They live HERE (in the
// frontend) and never get imported back into Python — backend stays oblivious.

export interface Citation {
  /** Entity id grounding a claim in the answer. */
  entity_id: number;
  /** Display label (entity name). */
  label: string;
  /** Optional entity type (Customer, Ticket, etc.) */
  type?: string;
}

export interface Usage {
  prompt_tokens: number;
  completion_tokens: number;
  latency_ms: number;
  menial_model?: string;
  answer_model?: string;
}

/** Live LLM runtime config (GET /llm/config · POST /admin/llm/config). */
export interface LlmConfig {
  provider: string;
  menial_model: string;
  answer_model: string;
  endpoint: string;
  api_key_set: boolean;
}

export interface LlmConfigUpdate {
  provider?: string;
  menial_model?: string;
  answer_model?: string;
  endpoint?: string;
  api_key?: string;
}

export interface AskResponse {
  answer: string;
  terms: string[];
  tools_called: unknown[];
  usage: Usage;
  grounding?: Grounding | null;
}

// ── Accuracy Lab (v2) ───────────────────────────────────────────────────
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

// ── Data Explorer (v2) ──────────────────────────────────────────────────
export interface DataTypeCount { name: string; count: number }
export interface DataSourceCount { source: string; count: number }

export interface DataSummary {
  total_entities: number;
  type_count: number;
  types: DataTypeCount[];
  sources: DataSourceCount[];
  source_records: number;
  duplicates_merged: number;
}

export interface ProvenanceRef {
  system: string;
  dataset: string;
  record_id: string;
}

export interface DataEntity {
  id: number;
  type: string;
  name: string;
  attributes: Record<string, unknown>;
  sources: ProvenanceRef[];
}

export interface DataEntitiesPage {
  type: string | null;
  total: number;
  offset: number;
  limit: number;
  items: DataEntity[];
}

export interface GraphTypeNode { type: string; count: number }
export interface GraphTypeEdge {
  source: string;
  target: string;
  name: string;
  count: number;
}

export interface GraphView {
  type_nodes: GraphTypeNode[];
  type_edges: GraphTypeEdge[];
  entity_count: number;
  relationship_count: number;
}

export interface GraphEntityNode { id: number; type: string; name: string }
export interface GraphEntityEdge { source: number; target: number; name: string }

export interface EntityGraphView {
  nodes: GraphEntityNode[];
  edges: GraphEntityEdge[];
  entity_count: number;
  relationship_count: number;
}

export interface EntityRelationship {
  direction: "in" | "out";
  name: string;
  other_id: number;
  other_name: string;
  other_type: string;
}

export interface EntityDetail {
  id: number;
  type: string;
  name: string;
  attributes: Record<string, unknown>;
  sources: { system: string; dataset: string; record_id: string }[];
  relationships: EntityRelationship[];
}

// ── Graph explorer (/graph page) — FalkorDB-backed neighbor/path reads ──────
// Same entity-id space as the Postgres EntityStore (project_graph mints
// FalkorDB node ids directly from EntityStore ids), so these compose with
// EntityGraphView/EntityDetail above without any id translation.

export interface GraphNeighbor {
  id: number;
  type: string;
  name: string;
  relationship: string;
  direction: "in" | "out";
}

export interface GraphPathStep {
  id: number;
  type: string;
  name: string;
  relationship: string | null;
}

export interface Workspace {
  id: number;
  name: string;
  description?: string;
  context?: string;
  brief?: Record<string, unknown>;
}

export interface ChatTurn {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  usage?: Usage;
  streaming?: boolean;
}

// ─── Ontology / modelling layer ───────────────────────────────────────────

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

export interface IngestQuestion {
  id: number;
  workspace_id: number;
  job_id?: string;
  kind: string;
  prompt: string;
  options?: string[];
  suggested?: string;
  status: "pending" | "answered" | string;
  answer?: string;
  type_name?: string;
}

export interface Brief {
  domain?: string;
  aim?: string;
  objectives?: string[];
  scope?: string;
  roles?: string[];
}

export interface QuizField {
  name: string;
  label: string;
  required?: boolean;
  secret?: boolean;
  help?: string;
  default?: string;
  options?: string[];
  kind?: string;
}

export interface QuizSpec {
  kind: string;
  label: string;
  fields: QuizField[];
}

export interface Datasource {
  id: number;
  workspace_id: number;
  name: string;
  kind: string;
  config: Record<string, unknown>;
  mask: string;
  ready: boolean;
}

// ─── Ontology interchange (import / export / config) ─────────────────────

export interface OntologyFormat {
  name: string;
  media_type: string;
  extension: string;
}

export interface OntologyConfig {
  enabled: boolean;
  formats: string[];
  base_uri: string;
  include_provenance: boolean;
  available: string[];
}

export interface OntologyImportResult {
  imported: number;
  types: string[];
  format: string;
  message: string;
  hierarchy_edges?: number;
  axioms_persisted?: number;
  entities_imported?: number;
  relationships_imported?: number;
}

// ─── Inference rules (workspace-level, /rules) ────────────────────────────

export interface WorkspaceRule {
  id?: number;
  workspace_id?: number;
  name: string;
  when: Record<string, unknown>;
  then: Record<string, unknown>;
  enabled: boolean;
}

export interface RuleEvaluationResult {
  [key: string]: unknown;
}

// ─── Ontology versions + change log ───────────────────────────────────────

/** Row shape from VersionStore.list_() (GET /ontology-versions). The POST
 *  response (VersionStore.snapshot) only returns {id, version_no, created_at}
 *  — label/created_by aren't echoed back, so re-list to see them. */
export interface OntologyVersion {
  id: number;
  workspace_id?: number;
  version_no: number;
  label?: string;
  created_by?: string;
  created_at: string;
  types_json?: unknown;
  rules_json?: unknown;
}

/** Row shape from VersionStore.changes() (GET /ontology-versions/changes). */
export interface OntologyChange {
  id: number;
  workspace_id: number;
  actor: string;
  op: string;
  target_kind: string;
  target_name: string;
  before?: unknown;
  after?: unknown;
  changed_at: string;
}

// ── Document self-discovery (read → summary → confirm) ──────────────────
export interface SupportedFileTypes {
  file_types: string[];
  max_files: number;
  max_file_mb: number;
  max_total_mb: number;
}

export interface DiscoveryTypeSummary {
  type: string;
  count: number;
  examples: string[];
}

export interface DiscoveryFileSummary {
  filename: string;
  ontology_type: string;
}

/** GET /admin/docs/summary/{discovery_id} — `{}` while the read job is
 *  still running (poll via the discovery id's job status, not this shape). */
export interface DiscoverySummary {
  types?: DiscoveryTypeSummary[];
  files?: DiscoveryFileSummary[];
}
