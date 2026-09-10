import type { OntologyChange, OntologyVersion } from "../types";
import { BASE, fetchJSON } from "./core";
import { createHttpStatusError, fetchWithShayAuth, readErrorDetail } from "../shay-session";

export const ontologyVersionsInterchangeApi = {
  listOntologyVersions: (workspaceId: number) =>
    fetchJSON<OntologyVersion[]>(`/ontology-versions?workspace_id=${workspaceId}`),

  createOntologySnapshot: (workspaceId: number, label = "") =>
    fetchJSON<OntologyVersion>("/ontology-versions", {
      method: "POST",
      body: JSON.stringify({ workspace_id: workspaceId, label }),
    }),

  getOntologyChanges: (workspaceId: number) =>
    fetchJSON<OntologyChange[]>(`/ontology-versions/changes?workspace_id=${workspaceId}`),

  getOntologyConfig: () =>
    fetchJSON<{ enabled: boolean; formats: string[]; base_uri?: string }>(
      "/ontology/config",
    ),

  getOntologyFormats: () =>
    fetchJSON<Array<{ name: string; extension: string }>>(
      "/ontology/formats",
    ),

  setOntologyConfig: (config: { enabled: boolean; formats: string[]; base_uri?: string; include_provenance?: boolean }) =>
    fetchJSON<{ enabled: boolean; formats: string[] }>(
      "/ontology/config",
      { method: "POST", body: JSON.stringify(config) },
    ),

  exportOntology: async (workspaceId: number, format: string): Promise<Blob> => {
    const res = await fetchWithShayAuth(
      `${BASE}/ontology/export?workspace_id=${workspaceId}&format=${encodeURIComponent(format)}`,
      undefined,
    );
    if (!res.ok) {
      const detail = await readErrorDetail(res);
      throw createHttpStatusError(res.status, res.statusText, detail);
    }
    return res.blob();
  },

  importOntology: (workspaceId: number, content: string, format: string, filename: string) =>
    fetchJSON<{ imported: number; types: string[]; message?: string }>(
      "/ontology/import",
      {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspaceId, content, format, filename }),
      },
    ),
};
