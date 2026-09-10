/**
 * Per-workspace metrics (members, entities, data sources) loader for
 * WorkspaceIndexPage's cards.
 *
 * Split out of useWorkspaceIndexPage.ts (2026-09; Raven Style
 * Compliance Plan Phase 8b line-count reduction).
 */

import { useEffect, useState } from "react";
import type { WorkspaceCardMetrics } from "../WorkspaceIndexCard";
import { api } from "@/lib/api";
import { shayApi } from "@/lib/shay-api";
import type { ShayWorkspace } from "@/lib/shay-types";
import { resolveWorkspaceDataSourceCount } from "./resolve-source-count";

export function useWorkspaceMetrics(
  workspaces: ShayWorkspace[],
  accessToken: string | undefined,
  companyId: string | undefined,
) {
  const [workspaceMetrics, setWorkspaceMetrics] = useState<Record<string, WorkspaceCardMetrics>>({});

  useEffect(() => {
    if (!accessToken || workspaces.length === 0) {
      setWorkspaceMetrics({});
      return;
    }

    let active = true;

    const loadMetrics = async () => {
      const metricResults = await Promise.allSettled(workspaces.map(async (workspace) => {
        const aryxWorkspaceId = workspace.bridge?.aryx_workspace_id;
        const [membersResult, datasourcesResult, groupedSourcesResult, summaryResult] = await Promise.allSettled([
          shayApi.listWorkspaceMembers(workspace.id, accessToken),
          shayApi.listDatasources(workspace.id, accessToken),
          aryxWorkspaceId
            ? api.listDataSources(aryxWorkspaceId)
            : Promise.resolve(null),
          aryxWorkspaceId
            ? api.dataSummary(aryxWorkspaceId)
            : Promise.resolve(null),
        ]);
        const members = membersResult.status === "fulfilled" ? membersResult.value : null;
        const datasources = datasourcesResult.status === "fulfilled" ? datasourcesResult.value : null;
        const groupedSources = groupedSourcesResult.status === "fulfilled" ? groupedSourcesResult.value : null;
        const summary = summaryResult.status === "fulfilled" ? summaryResult.value : null;

        return [workspace.id, {
          users: members?.total ?? members?.members.length ?? null,
          entities: summary?.total_entities ?? null,
          entityTypes: summary?.type_count ?? null,
          dataSources: resolveWorkspaceDataSourceCount({
            summarySourceCount: summary?.sources.length ?? null,
            catalogSourceCount: groupedSources?.length ?? null,
            datasourceTotal: datasources?.total ?? null,
            datasourceItemsCount: datasources?.items.length ?? null,
          }),
        }] as const;
      }));

      if (!active) {
        return;
      }

      const nextMetrics: Record<string, WorkspaceCardMetrics> = {};
      metricResults.forEach((result) => {
        if (result.status !== "fulfilled") {
          return;
        }
        const [workspaceId, metrics] = result.value;
        nextMetrics[workspaceId] = metrics;
      });
      setWorkspaceMetrics(nextMetrics);
    };

    void loadMetrics();

    return () => {
      active = false;
    };
  }, [accessToken, companyId, workspaces]);

  return workspaceMetrics;
}
