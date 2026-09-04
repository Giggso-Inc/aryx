import { useState } from "react";
import { Braces, Share2, Wand2 } from "lucide-react";
import { ShareConfigDialog } from "../ShareConfigDialog";
import type { ChatTurn } from "@/lib/types";

type SharePanel = "json" | "beautify" | null;

/** JSON / Beautify / Share buttons — driven entirely by flags the backend
 * already computed from session state; clicking JSON or Beautify just reveals
 * data already in the response. Share opens a dialog where the destination
 * endpoint + auth are supplied per share (no button here ever triggers
 * another LLM call). */
export function CpqActions({ turn, workspaceId, conversationId }: {
  turn: ChatTurn; workspaceId?: number; conversationId?: string;
}) {
  const [panel, setPanel] = useState<SharePanel>(null);
  const [shareOpen, setShareOpen] = useState(false);

  const canShare = Boolean(turn.apiShareButtonFlag && workspaceId !== undefined && conversationId);
  if (!turn.jsonButtonFlag && !turn.beautifyButtonFlag && !canShare) {
    return null;
  }

  return (
    <div className="mt-2">
      <div className="flex flex-wrap gap-2">
        {turn.jsonButtonFlag && (
          <button
            type="button"
            onClick={() => setPanel((p) => (p === "json" ? null : "json"))}
            className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-navy-100 bg-white px-2.5 py-1 text-[12px] text-navy-600 hover:bg-navy-50"
          >
            <Braces size={12} /> JSON
          </button>
        )}
        {turn.beautifyButtonFlag && (
          <button
            type="button"
            onClick={() => setPanel((p) => (p === "beautify" ? null : "beautify"))}
            className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-navy-100 bg-white px-2.5 py-1 text-[12px] text-navy-600 hover:bg-navy-50"
          >
            <Wand2 size={12} /> Beautify
          </button>
        )}
        {canShare && (
          <button
            type="button"
            onClick={() => setShareOpen(true)}
            className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-navy-100 bg-white px-2.5 py-1 text-[12px] text-navy-600 hover:bg-navy-50"
          >
            <Share2 size={12} /> Share
          </button>
        )}
      </div>
      {panel === "json" && (
        <pre className="mt-2 max-w-prose overflow-x-auto rounded-xl border border-navy-100 bg-navy-50 p-3 text-[12px]">
          {JSON.stringify(turn.jsonResponse ?? {}, null, 2)}
        </pre>
      )}
      {panel === "beautify" && (
        <div className="mt-2 max-w-prose overflow-x-auto rounded-xl border border-navy-100 bg-white p-3">
          {turn.beautifyRows && turn.beautifyRows.length > 0 ? (
            <table className="min-w-full border-collapse text-[13px]">
              <thead>
                <tr>
                  <th className="border border-navy-100 bg-navy-50 px-3 py-1.5 text-left font-semibold text-navy-800">
                    Attribute
                  </th>
                  <th className="border border-navy-100 bg-navy-50 px-3 py-1.5 text-left font-semibold text-navy-800">
                    Value
                  </th>
                </tr>
              </thead>
              <tbody>
                {turn.beautifyRows.map((row, i) => (
                  <tr key={`${row.label}-${i}`}>
                    <td className="border border-navy-100 px-3 py-1.5 font-medium text-navy-800">
                      {row.label}
                    </td>
                    <td className="border border-navy-100 px-3 py-1.5 text-navy-700">
                      {row.value}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <pre className="text-[12px] text-navy-700">{turn.beautify}</pre>
          )}
        </div>
      )}
      {canShare && (
        <ShareConfigDialog
          open={shareOpen}
          workspaceId={workspaceId!}
          conversationId={conversationId!}
          configJson={turn.jsonResponse ?? {}}
          onClose={() => setShareOpen(false)}
        />
      )}
    </div>
  );
}
