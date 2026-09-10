import type { ShayCompany } from "../shay-types";
import { requestJSON } from "./http";
import { SHAY_BASE } from "./constants";

export const companyApi = {
  getMyCompany: (token: string) =>
    requestJSON<ShayCompany>(SHAY_BASE, "/companies/my", undefined, token),

  updateCompany: (
    companyId: string,
    payload: {
      name?: string;
      description?: string;
      settings?: Record<string, unknown>;
    },
    token: string,
  ) =>
    requestJSON<ShayCompany>(
      SHAY_BASE,
      `/companies/${companyId}`,
      {
        method: "PUT",
        body: JSON.stringify(payload),
      },
      token,
    ),
};
