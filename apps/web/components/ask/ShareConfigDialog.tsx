"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, ChevronRight, Check, Globe, Loader2, Share2, X } from "lucide-react";
import { api } from "@/lib/api";

const inp = "focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] focus:border-steel-500";
const inpBg = "focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] focus:border-steel-500";

interface Props {
  open: boolean;
  workspaceId: number;
  conversationId: string;
  configJson: Record<string, unknown>;
  onClose: () => void;
}

/** Modal for the CPQ Share button — the destination endpoint + auth are
 * supplied by the sales rep per share (same trust model as the REST API
 * ingest form), not server-configured. Preview shows the exact outgoing
 * request before anything is sent. */
export function ShareConfigDialog({ open, workspaceId, conversationId, configJson, onClose }: Props) {
  const [endpointUrl, setEndpointUrl] = useState("");
  const [authHeaderName, setAuthHeaderName] = useState("Authorization");
  const [authHeaderValue, setAuthHeaderValue] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [extraHeadersRaw, setExtraHeadersRaw] = useState("");
  const [showPreview, setShowPreview] = useState(false);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setEndpointUrl(""); setAuthHeaderName("Authorization"); setAuthHeaderValue("");
      setShowAdvanced(false); setExtraHeadersRaw(""); setShowPreview(false);
      setSending(false); setSent(false); setError(null);
    }
  }, [open]);

  const parseExtraHeaders = (): Record<string, string> | null => {
    if (!extraHeadersRaw.trim()) return {};
    try {
      const parsed = JSON.parse(extraHeadersRaw);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
    } catch {
      /* fall through to null */
    }
    return null;
  };

  const send = async () => {
    const extraHeaders = parseExtraHeaders();
    if (extraHeaders === null) {
      setError("Additional headers must be valid JSON (e.g. {\"x-tenant\": \"acme\"})");
      return;
    }
    setSending(true);
    setError(null);
    try {
      await api.shareConfig({
        workspaceId, conversationId, configJson,
        endpointUrl: endpointUrl.trim(),
        authHeaderName: authHeaderName.trim() || "Authorization",
        authHeaderValue,
        extraHeaders,
      });
      setSent(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Share failed");
    } finally {
      setSending(false);
    }
  };

  const extraHeaders = parseExtraHeaders();

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-30 flex items-center justify-center bg-navy-950/30 backdrop-blur-sm"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, y: 8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            onClick={(e) => e.stopPropagation()}
            className="w-[480px] overflow-hidden rounded-2xl border border-navy-100 bg-white shadow-soft"
          >
            <header className="flex items-center justify-between border-b border-navy-100 px-5 py-3">
              <h3 className="font-display text-[1.05rem] text-navy-900">Share configuration</h3>
              <button onClick={onClose} className="focus-ring rounded-lg p-1 text-subtle hover:bg-navy-50" aria-label="Close">
                <X size={15} />
              </button>
            </header>

            <div className="px-5 py-4">
              <h4 className="mb-4 font-semibold text-navy-900">Endpoint Configuration</h4>

              <div className="mb-3">
                <label className="mb-1 block text-[11px] font-medium text-navy-600">Endpoint URL *</label>
                <input value={endpointUrl} onChange={(e) => setEndpointUrl(e.target.value)}
                  placeholder="https://api.example.com/v1/customers" className={inp} />
              </div>

              <div className="mb-3 grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-[11px] font-medium text-navy-600">Auth header name</label>
                  <input value={authHeaderName} onChange={(e) => setAuthHeaderName(e.target.value)}
                    placeholder="Authorization" className={inp} />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] font-medium text-navy-600">Auth header value</label>
                  <input value={authHeaderValue} onChange={(e) => setAuthHeaderValue(e.target.value)}
                    type="password" placeholder="Bearer token123…" className={inp} />
                </div>
              </div>

              <button type="button" onClick={() => setShowAdvanced((v) => !v)}
                className="focus-ring mb-3 flex items-center gap-1 text-[12px] text-navy-600 hover:text-navy-900">
                {showAdvanced ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                Advanced options
              </button>

              {showAdvanced && (
                <div className="mb-3 rounded-lg border border-navy-100 bg-navy-50/40 p-3">
                  <label className="mb-1 block text-[11px] font-medium text-navy-600">Additional headers (JSON)</label>
                  <input value={extraHeadersRaw} onChange={(e) => setExtraHeadersRaw(e.target.value)}
                    placeholder='{"x-tenant": "acme"}' className={inpBg} />
                  <p className="mt-0.5 text-[10px] text-subtle">Merged with the auth header above.</p>
                </div>
              )}

              <button type="button" onClick={() => setShowPreview((v) => !v)} disabled={!endpointUrl.trim()}
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

            <footer className="flex items-center justify-end gap-2 border-t border-navy-100 bg-navy-50/40 px-5 py-3">
              <button onClick={onClose} className="focus-ring rounded-lg px-3 py-1.5 text-[12px] font-medium text-navy-700 hover:bg-white">
                Cancel
              </button>
              <button onClick={send} disabled={!endpointUrl.trim() || sending || sent}
                className="focus-ring inline-flex items-center gap-2 rounded-lg bg-navy-800 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50">
                {sending ? <Loader2 size={13} className="animate-spin" /> : sent ? <Check size={13} /> : <Share2 size={13} />}
                {sending ? "Sharing…" : sent ? "Shared" : "Share"}
              </button>
            </footer>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
