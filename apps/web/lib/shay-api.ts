export { getShayAccessToken } from "./shay-session";
import { authApi } from "./shay-api/auth";
import { companyApi } from "./shay-api/company";
import { companyUsersApi } from "./shay-api/company-users";
import { workspacesApi } from "./shay-api/workspaces";
import { workspaceMembersApi } from "./shay-api/workspace-members";
import { workspaceAppsApi } from "./shay-api/workspace-apps";
import { datasourcesApi } from "./shay-api/datasources";
import { bridgeApi } from "./shay-api/bridge";

export const shayApi = {
  ...authApi,
  ...companyApi,
  ...companyUsersApi,
  ...workspacesApi,
  ...workspaceMembersApi,
  ...workspaceAppsApi,
  ...datasourcesApi,
  ...bridgeApi,
};
