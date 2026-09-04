import type { Rule } from "../types";
import { fetchJSON } from "./core";

export const ontologyRulesApi = {
  getRules: (workspaceId: number) =>
    fetchJSON<Rule[]>(`/rules?workspace_id=${workspaceId}`),

  createRule: (workspaceId: number, rule: Omit<Rule, "enabled">) =>
    fetchJSON<{ status: string }>("/rules", {
      method: "POST",
      body: JSON.stringify({ ...rule, workspace_id: workspaceId }),
    }),

  toggleRule: (name: string, workspaceId: number, enabled: boolean) =>
    fetchJSON<{ status: string }>(`/rules/${encodeURIComponent(name)}/enabled?workspace_id=${workspaceId}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    }),

  deleteRule: (name: string, workspaceId: number) =>
    fetchJSON<{ status: string }>(
      `/rules/${encodeURIComponent(name)}?workspace_id=${workspaceId}`,
      { method: "DELETE" },
    ),

  evaluateRules: (workspaceId: number) =>
    fetchJSON<{ violations: number; applied: number }>(
      `/rules/evaluate?workspace_id=${workspaceId}`,
      { method: "POST", body: "{}" },
    ),
};
