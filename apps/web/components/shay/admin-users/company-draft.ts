import type { ShayCompany } from "@/lib/shay-types";

export interface CompanyProfileDraft {
  name: string;
  website: string;
  emailAddress: string;
  description: string;
}

function readSetting(settings: Record<string, unknown> | null | undefined, ...keys: string[]) {
  if (!settings) return "";
  for (const key of keys) {
    const value = settings[key];
    if (typeof value === "string" && value.trim()) {
      return value;
    }
  }
  return "";
}

export function buildCompanyDraft(company: ShayCompany): CompanyProfileDraft {
  return {
    name: company.name,
    website:
      readSetting(company.settings, "website", "companyWebsite", "company_website") ||
      company.domain ||
      "",
    emailAddress: readSetting(
      company.settings,
      "companyEmailAddress",
      "company_email_address",
      "contactEmail",
      "contact_email",
    ),
    description: company.description ?? readSetting(company.settings, "description"),
  };
}
