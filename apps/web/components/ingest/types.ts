export type DbPhase = "idle" | "connecting" | "connected" | "discovering" | "review" | "ingesting" | "done" | "error";
export type DocPhase = "idle" | "reading" | "summary" | "confirming" | "done" | "error";
export type RestPhase = "idle" | "previewing" | "preview" | "ingesting" | "done" | "error";

export interface DiscoveredTable {
  table: string;
  ontology_type: string;
  match_keys: string[];
  included: boolean;
}
