import type { AskThreadSummary } from "@/lib/types";

function relativeTimeLabel(value?: string): string {
  if (!value) return "";
  const time = new Date(value).getTime();
  if (Number.isNaN(time)) return "";
  const seconds = Math.max(0, Math.floor((Date.now() - time) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} ${minutes === 1 ? "min" : "mins"} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} ${hours === 1 ? "hour" : "hours"} ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} ${days === 1 ? "day" : "days"} ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months} ${months === 1 ? "month" : "months"} ago`;
  const years = Math.floor(months / 12);
  return `${years} ${years === 1 ? "year" : "years"} ago`;
}

export function ThreadList({
  threads,
  selectedThreadId,
  onSelectThread,
}: {
  threads: AskThreadSummary[];
  selectedThreadId: string | null;
  onSelectThread: (threadId: string) => void;
}) {
  return (
    <ul className="space-y-2">
      {threads.map((thread) => (
        <li key={thread.id}>
          <button
            type="button"
            onClick={() => onSelectThread(thread.id)}
            className={`focus-ring w-full rounded-lg border p-3 text-left transition-colors ${
              thread.id === selectedThreadId
                ? "border-steel-300 bg-navy-50"
                : "border-navy-100 bg-white hover:border-steel-300 hover:bg-navy-50"
            }`}
          >
            <span className="line-clamp-2 block text-[12px] font-medium text-navy-800">
              {thread.title}
            </span>
            <span className="mt-2 flex items-center justify-between gap-3 text-[10px] text-subtle">
              <span>{thread.message_count || 0} messages</span>
              <span className="shrink-0">{relativeTimeLabel(thread.updated_at)}</span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
