import { askApi } from "./api/ask";
import { csvBmlApi } from "./api/csv-bml";
import { dataSourcesApi } from "./api/data-sources";
import { entityGraphApi } from "./api/entity-graph-api";
import { ingestFlowsApi } from "./api/ingest-flows";
import { jobsApi } from "./api/jobs";
import { mcpTokensApi } from "./api/mcp-tokens";
import { ontologyRulesApi } from "./api/ontology-rules";
import { ontologyTypesApi } from "./api/ontology-types";
import { ontologyVersionsInterchangeApi } from "./api/ontology-versions-interchange";
import { wizardApi } from "./api/wizard";
import { workspacesApi } from "./api/workspaces";

export type { DataSourceDeleteResult } from "./api/core";

export const api = {
  ...workspacesApi,
  ...askApi,
  ...dataSourcesApi,
  ...ontologyTypesApi,
  ...ontologyRulesApi,
  ...ontologyVersionsInterchangeApi,
  ...jobsApi,
  ...csvBmlApi,
  ...wizardApi,
  ...entityGraphApi,
  ...ingestFlowsApi,
  ...mcpTokensApi,
};
