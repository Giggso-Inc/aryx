import type { ReactNode } from "react";
import { Building2, Globe, Mail, Sparkles } from "lucide-react";
import type { ShayCompany } from "@/lib/shay-types";
import type { CompanyProfileDraft } from "./company-draft";

export function CompanyProfileSection({
  company,
  savingCompany,
  companyDraft,
  onCompanyDraftChange,
  onSaveCompanyProfile,
}: {
  company: ShayCompany | null;
  savingCompany: boolean;
  companyDraft: CompanyProfileDraft;
  onCompanyDraftChange: (patch: Partial<CompanyProfileDraft>) => void;
  onSaveCompanyProfile: () => void;
}) {
  if (!company) {
    return (
      <div className="rounded-[1.75rem] border border-navy-100 bg-white p-6 shadow-soft">
        <p className="text-sm text-subtle">Company profile is not available yet.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <section className="rounded-[1.75rem] border border-navy-100 bg-white p-6 shadow-soft">
        <div className="grid gap-5 md:grid-cols-2">
          <ProfileField
            icon={<Building2 size={14} />}
            label="Company Name"
            value={companyDraft.name}
            placeholder="Giggso.Inc"
            onChange={(value) => onCompanyDraftChange({ name: value })}
          />
          <ProfileField
            icon={<Globe size={14} />}
            label="Company Website"
            value={companyDraft.website}
            placeholder="www.giggso.com"
            onChange={(value) => onCompanyDraftChange({ website: value })}
          />
          <ProfileField
            icon={<Mail size={14} />}
            label="Company Email Address"
            value={companyDraft.emailAddress}
            placeholder="sales@company.com"
            onChange={(value) => onCompanyDraftChange({ emailAddress: value })}
          />
          <div className="md:col-span-2">
            <ProfileTextarea
              icon={<Sparkles size={14} />}
              label="Company Description"
              value={companyDraft.description}
              placeholder="Describe your company, its mission, and key services..."
              onChange={(value) => onCompanyDraftChange({ description: value })}
            />
          </div>
        </div>

        <div className="mt-6 flex items-center justify-end">
          <button
            type="button"
            onClick={onSaveCompanyProfile}
            disabled={savingCompany}
            className="focus-ring inline-flex items-center gap-2 rounded-2xl bg-navy-800 px-5 py-3 text-sm font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
          >
            {savingCompany ? "Saving..." : "Save Changes"}
          </button>
        </div>
      </section>
    </div>
  );
}

function ProfileField({
  icon,
  label,
  value,
  placeholder,
  onChange,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="mb-2 flex items-center gap-2 text-[13px] font-semibold text-navy-700">
        <span className="text-subtle">{icon}</span>
        {label}
      </span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="focus-ring w-full rounded-2xl border border-navy-100 bg-white px-4 py-3 text-sm text-navy-900 placeholder:text-subtle"
      />
    </label>
  );
}

function ProfileTextarea({
  icon,
  label,
  value,
  placeholder,
  onChange,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="mb-2 flex items-center gap-2 text-[13px] font-semibold text-navy-700">
        <span className="text-subtle">{icon}</span>
        {label}
      </span>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        rows={5}
        className="focus-ring w-full rounded-2xl border border-navy-100 bg-white px-4 py-3 text-sm text-navy-900 placeholder:text-subtle"
      />
    </label>
  );
}
