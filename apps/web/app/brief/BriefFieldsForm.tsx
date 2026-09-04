import { Loader2 } from "lucide-react";
import { FieldGroup, Readiness } from "./shared";

export function BriefFieldsForm({
  loading,
  domain,
  aim,
  objectives,
  scope,
  roles,
  saving,
  filledCount,
  onDomainChange,
  onAimChange,
  onObjectivesChange,
  onScopeChange,
  onRolesChange,
  onSave,
}: {
  loading: boolean;
  domain: string;
  aim: string;
  objectives: string;
  scope: string;
  roles: string;
  saving: boolean;
  filledCount: number;
  onDomainChange: (value: string) => void;
  onAimChange: (value: string) => void;
  onObjectivesChange: (value: string) => void;
  onScopeChange: (value: string) => void;
  onRolesChange: (value: string) => void;
  onSave: () => void;
}) {
  return (
    <div className="space-y-5 rounded-xl border border-navy-100 bg-white p-5 shadow-soft">
      <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-navy-500">
        Review and edit
      </div>
      {loading ? (
        <div className="flex items-center justify-center py-8 text-[13px] text-subtle">
          <Loader2 size={14} className="mr-2 animate-spin" /> Loading brief…
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <FieldGroup
              label="1 · Domain of interest"
              name="domain"
              value={domain}
              onChange={onDomainChange}
            />
            <FieldGroup
              label="2 · Aim — purpose of the knowledge model"
              name="aim"
              value={aim}
              onChange={onAimChange}
              rows={3}
            />
            <FieldGroup
              label="3 · Objectives (one per line)"
              name="objectives"
              value={objectives}
              onChange={onObjectivesChange}
              rows={4}
            />
            <FieldGroup
              label="5 · Participant roles (one per line)"
              name="roles"
              value={roles}
              onChange={onRolesChange}
              rows={4}
            />
          </div>
          <FieldGroup
            label="4 · Scope — what's IN, what's OUT"
            name="scope"
            value={scope}
            onChange={onScopeChange}
            rows={2}
          />

          <Readiness filled={filledCount} />

          <button
            type="button"
            onClick={onSave}
            disabled={saving}
            className="focus-ring inline-flex w-full items-center justify-center gap-2 rounded-lg bg-navy-800 py-2.5 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
          >
            {saving ? (
              <><Loader2 size={13} className="animate-spin" /> Saving…</>
            ) : (
              "Save Brief"
            )}
          </button>
        </>
      )}
    </div>
  );
}
