import type { DataTypeCount, SourceActionState } from "./data-sources";

export interface XmlGeneratedAsset {
  asset_key: string;
  filename: string;
  dataset: string;
  ontology_type: string;
  status: string;
  record_count: number;
  preview_rows: Record<string, string>[];
  actions: SourceActionState;
}

export interface SourceEntitySummary {
  total_entities: number;
  type_count: number;
  node_count?: number;
  edge_count?: number;
  types: DataTypeCount[];
}

export interface DataSourceDetail {
  source_key: string;
  name: string;
  display_kind: string;
  kind: string;
  status: string;
  ready: boolean;
  actions: SourceActionState;
  isXmlParent: boolean;
  detail_kind: "grouped_assets" | "preview" | "configured";
  entity_summary: SourceEntitySummary;
  generatedAssetCount: number;
  record_count: number;
  primary: {
    label: string;
    status: string;
    actions: SourceActionState;
  };
  assets: XmlGeneratedAsset[];
}

export type XmlSourceDetail = DataSourceDetail;
