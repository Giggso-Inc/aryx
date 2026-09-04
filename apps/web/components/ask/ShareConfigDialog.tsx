"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Check, Loader2, Share2, X } from "lucide-react";
import { api } from "@/lib/api";
import { ConfigForm } from "./share-config-dialog/ConfigForm";

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

            <ConfigForm
              endpointUrl={endpointUrl}
              authHeaderName={authHeaderName}
              authHeaderValue={authHeaderValue}
              showAdvanced={showAdvanced}
              extraHeadersRaw={extraHeadersRaw}
              showPreview={showPreview}
              extraHeaders={extraHeaders}
              configJson={configJson}
              error={error}
              onEndpointUrlChange={setEndpointUrl}
              onAuthHeaderNameChange={setAuthHeaderName}
              onAuthHeaderValueChange={setAuthHeaderValue}
              onToggleAdvanced={() => setShowAdvanced((v) => !v)}
              onExtraHeadersRawChange={setExtraHeadersRaw}
              onTogglePreview={() => setShowPreview((v) => !v)}
            />

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
