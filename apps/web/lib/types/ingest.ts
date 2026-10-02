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

export interface DiscoverySummary {
  types: Array<{ type: string; count: number; examples: string[] }>;
  /**
   * Tabular (CSV/JSON) files the read step identified. `filename` is the
   * internal per-entity-type plan name (e.g. an XML upload is split into
   * one synthetic "<stem>_<Tag>.csv" plan per discovered element type) --
   * `source_filename` is the file the user actually uploaded (e.g.
   * "order.xml") and should be preferred for display when present.
   */
  files: Array<{ filename: string; ontology_type: string; source_filename?: string }>;
}

export interface DiscoveryHistoryItem {
  discovery_id: string;
  status: "pending" | "partial" | "confirming" | "confirmed";
  summary: DiscoverySummary;
  file_count: number;
  created_at: string;
  confirmed_at: string | null;
  /** Number of days since upload. Only set for status="pending"; null otherwise. */
  pending_days: number | null;
}
