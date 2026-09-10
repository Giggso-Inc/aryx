import type { ReactNode } from "react";
import { Building2, CreditCard, ShieldCheck, Sparkles, Users2 } from "lucide-react";
import type { ShayCompany } from "@/lib/shay-types";

export function SubscriptionSection({ company }: { company: ShayCompany | null }) {
  const plan = company?.subscription_plan || "Free";
  const maxUsers = company?.max_users || "0";
  const maxWorkspaces = company?.max_workspaces || "0";
  const maxStorage = company?.max_storage_gb || "0";

  return (
    <div className="space-y-6">
      <section className="rounded-[1.75rem] border border-navy-100 bg-[linear-gradient(135deg,_rgba(10,21,48,0.96),_rgba(20,34,69,0.92))] p-6 text-white shadow-soft">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs font-semibold text-white/85">
              <Sparkles size={13} />
              Current Plan
            </div>
            <h2 className="mt-4 text-3xl font-semibold tracking-tight">
              {formatLabel(plan)}
            </h2>
            <p className="mt-3 max-w-2xl text-sm text-white/75">
              Keep track of your company limits and enabled capabilities from the admin hub.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <FeatureBadge label="AI Enabled" value={company?.ai_enabled ? "Yes" : "No"} />
            <FeatureBadge label="AI Provider" value={formatLabel(company?.ai_provider || "None")} />
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <PlanStatCard
          icon={<Users2 size={18} />}
          title="Max Users"
          value={maxUsers}
          helper="Seats available on this plan"
        />
        <PlanStatCard
          icon={<Building2 size={18} />}
          title="Max Workspaces"
          value={maxWorkspaces}
          helper="Workspace capacity"
        />
        <PlanStatCard
          icon={<CreditCard size={18} />}
          title="Max Storage"
          value={`${maxStorage} GB`}
          helper="Total storage allowance"
        />
        <PlanStatCard
          icon={<ShieldCheck size={18} />}
          title="Status"
          value={company?.is_active ? "Active" : "Inactive"}
          helper="Company account state"
        />
      </section>
    </div>
  );
}

function PlanStatCard({
  icon,
  title,
  value,
  helper,
}: {
  icon: ReactNode;
  title: string;
  value: string;
  helper: string;
}) {
  return (
    <div className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-navy-700">{title}</p>
          <p className="mt-2 text-3xl font-semibold tracking-tight text-navy-900">{value}</p>
          <p className="mt-2 text-sm text-subtle">{helper}</p>
        </div>
        <div className="flex size-11 items-center justify-center rounded-2xl bg-blue-50 text-blue-700">
          {icon}
        </div>
      </div>
    </div>
  );
}

function FeatureBadge({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/10 px-4 py-3">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-white/60">{label}</p>
      <p className="mt-1 text-sm font-medium text-white">{value}</p>
    </div>
  );
}

function formatLabel(value: string) {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}
