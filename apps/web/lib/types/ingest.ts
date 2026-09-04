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
  /** Tabular (CSV/JSON) files the read step identified. */
  files: Array<{ filename: string; ontology_type: string }>;
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
