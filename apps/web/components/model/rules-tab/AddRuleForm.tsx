import { Loader2, Plus } from "lucide-react";

const OPS = [">", ">=", "<", "<=", "==", "!=", "contains"];
const ACTIONS = ["set_label", "add_relationship"];

export function AddRuleForm({
  name,
  whenType,
  whenAttr,
  whenOp,
  whenVal,
  action,
  labelOrRel,
  targetType,
  saving,
  onNameChange,
  onWhenTypeChange,
  onWhenAttrChange,
  onWhenOpChange,
  onWhenValChange,
  onActionChange,
  onLabelOrRelChange,
  onTargetTypeChange,
  onSave,
}: {
  name: string;
  whenType: string;
  whenAttr: string;
  whenOp: string;
  whenVal: string;
  action: string;
  labelOrRel: string;
  targetType: string;
  saving: boolean;
  onNameChange: (value: string) => void;
  onWhenTypeChange: (value: string) => void;
  onWhenAttrChange: (value: string) => void;
  onWhenOpChange: (value: string) => void;
  onWhenValChange: (value: string) => void;
  onActionChange: (value: string) => void;
  onLabelOrRelChange: (value: string) => void;
  onTargetTypeChange: (value: string) => void;
  onSave: () => void;
}) {
  return (
    <section className="rounded-xl border border-navy-100 bg-white p-5 shadow-soft">
      <h3 className="mb-4 text-[13px] font-bold text-navy-900">Add or update a rule</h3>
      <div className="space-y-3">
        <input
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          placeholder="Rule name (e.g. platinum_customer)"
          className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500"
        />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div>
            <label className="mb-1 block text-[10px] font-semibold text-navy-600">When type</label>
            <input value={whenType} onChange={(e) => onWhenTypeChange(e.target.value)}
              placeholder="Customer"
              className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[12px] focus:border-steel-500" />
          </div>
          <div>
            <label className="mb-1 block text-[10px] font-semibold text-navy-600">Attribute</label>
            <input value={whenAttr} onChange={(e) => onWhenAttrChange(e.target.value)}
              placeholder="revenue"
              className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[12px] focus:border-steel-500" />
          </div>
          <div>
            <label className="mb-1 block text-[10px] font-semibold text-navy-600">Operator</label>
            <select value={whenOp} onChange={(e) => onWhenOpChange(e.target.value)}
              className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[12px]">
              {OPS.map((op) => <option key={op}>{op}</option>)}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-[10px] font-semibold text-navy-600">Value</label>
            <input value={whenVal} onChange={(e) => onWhenValChange(e.target.value)}
              placeholder="1000000"
              className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[12px] focus:border-steel-500" />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <div>
            <label className="mb-1 block text-[10px] font-semibold text-navy-600">Action</label>
            <select value={action} onChange={(e) => onActionChange(e.target.value)}
              className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[12px]">
              {ACTIONS.map((a) => <option key={a}>{a}</option>)}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-[10px] font-semibold text-navy-600">
              {action === "set_label" ? "Set label" : "Relationship name"}
            </label>
            <input value={labelOrRel} onChange={(e) => onLabelOrRelChange(e.target.value)}
              placeholder={action === "set_label" ? "Platinum" : "BELONGS_TO"}
              className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[12px] focus:border-steel-500" />
          </div>
          {action === "add_relationship" && (
            <div>
              <label className="mb-1 block text-[10px] font-semibold text-navy-600">Target type</label>
              <input value={targetType} onChange={(e) => onTargetTypeChange(e.target.value)}
                placeholder="Tier"
                className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[12px] focus:border-steel-500" />
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={onSave}
          disabled={!name.trim() || !whenType.trim() || !whenAttr.trim() || saving}
          className="focus-ring inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-navy-800 py-2.5 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
        >
          {saving ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
          Save rule
        </button>
      </div>
    </section>
  );
}
