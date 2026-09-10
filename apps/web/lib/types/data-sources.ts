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

export interface SourceActionState {
  view: boolean;
  download: boolean;
  delete: boolean;
}

export interface DataSourceCatalogItem {
  source_key: string;
  name: string;
  display_kind: string;
  kind: string;
  ready: boolean;
  record_count: number;
  isXmlParent: boolean;
  generatedAssetCount: number;
  total_entities: number;
  entity_type_count: number;
  node_count?: number;
  edge_count?: number;
  actions: SourceActionState;
}

export interface DataSourceCatalogPage {
  items: DataSourceCatalogItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface GenericSourcePreview {
  source_key: string;
  name: string;
  rows: Record<string, unknown>[];
}

export interface SourceEntityTypesPage {
  items: DataTypeCount[];
  total: number;
  page: number;
  page_size: number;
}

export interface SourceRecordsPage {
  rows: Record<string, unknown>[];
  total: number;
  page: number;
  page_size: number;
}
