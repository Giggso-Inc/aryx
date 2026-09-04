import { ChevronDown, ChevronRight, Globe } from "lucide-react";

const inp = "focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] focus:border-steel-500";
const inpBg = "focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] focus:border-steel-500";

export function ConfigForm({
  endpointUrl,
  authHeaderName,
  authHeaderValue,
  showAdvanced,
  extraHeadersRaw,
  showPreview,
  extraHeaders,
  configJson,
  error,
  onEndpointUrlChange,
  onAuthHeaderNameChange,
  onAuthHeaderValueChange,
  onToggleAdvanced,
  onExtraHeadersRawChange,
  onTogglePreview,
}: {
  endpointUrl: string;
  authHeaderName: string;
  authHeaderValue: string;
  showAdvanced: boolean;
  extraHeadersRaw: string;
  showPreview: boolean;
  extraHeaders: Record<string, string> | null;
  configJson: Record<string, unknown>;
  error: string | null;
  onEndpointUrlChange: (value: string) => void;
  onAuthHeaderNameChange: (value: string) => void;
  onAuthHeaderValueChange: (value: string) => void;
  onToggleAdvanced: () => void;
  onExtraHeadersRawChange: (value: string) => void;
  onTogglePreview: () => void;
}) {
  return (
    <div className="px-5 py-4">
      <h4 className="mb-4 font-semibold text-navy-900">Endpoint Configuration</h4>

      <div className="mb-3">
        <label className="mb-1 block text-[11px] font-medium text-navy-600">Endpoint URL *</label>
        <input value={endpointUrl} onChange={(e) => onEndpointUrlChange(e.target.value)}
          placeholder="https://api.example.com/v1/customers" className={inp} />
      </div>

      <div className="mb-3 grid grid-cols-2 gap-3">
        <div>
          <label className="mb-1 block text-[11px] font-medium text-navy-600">Auth header name</label>
          <input value={authHeaderName} onChange={(e) => onAuthHeaderNameChange(e.target.value)}
            placeholder="Authorization" className={inp} />
        </div>
        <div>
          <label className="mb-1 block text-[11px] font-medium text-navy-600">Auth header value</label>
          <input value={authHeaderValue} onChange={(e) => onAuthHeaderValueChange(e.target.value)}
            type="password" placeholder="Bearer token123…" className={inp} />
        </div>
      </div>

      <button type="button" onClick={onToggleAdvanced}
        className="focus-ring mb-3 flex items-center gap-1 text-[12px] text-navy-600 hover:text-navy-900">
        {showAdvanced ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        Advanced options
      </button>

      {showAdvanced && (
        <div className="mb-3 rounded-lg border border-navy-100 bg-navy-50/40 p-3">
          <label className="mb-1 block text-[11px] font-medium text-navy-600">Additional headers (JSON)</label>
          <input value={extraHeadersRaw} onChange={(e) => onExtraHeadersRawChange(e.target.value)}
            placeholder='{"x-tenant": "acme"}' className={inpBg} />
          <p className="mt-0.5 text-[10px] text-subtle">Merged with the auth header above.</p>
        </div>
      )}

      <button type="button" onClick={onTogglePreview} disabled={!endpointUrl.trim()}
        className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-navy-200 bg-white px-4 py-2 text-[13px] font-medium text-navy-700 hover:bg-navy-50 disabled:opacity-50">
        <Globe size={13} /> Preview
      </button>

      {showPreview && (
        <pre className="mt-3 max-h-48 overflow-auto rounded-lg border border-navy-100 bg-navy-50 p-3 text-[11px]">
{`POST ${endpointUrl.trim()}
${authHeaderValue ? `${authHeaderName || "Authorization"}: ${"•".repeat(8)}\n` : ""}${extraHeaders ? Object.entries(extraHeaders).map(([k, v]) => `${k}: ${v}`).join("\n") : ""}

${JSON.stringify(configJson, null, 2)}`}
        </pre>
      )}

      {error && (
        <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[11px] text-rose-700">
          {error}
        </div>
      )}
    </div>
  );
}
