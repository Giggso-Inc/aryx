import { useRef } from "react";
import { UploadCloud } from "lucide-react";
import { cn } from "@/lib/cn";

const ACCEPT = ".pdf,.docx,.doc,.pptx,.ppt,.txt,.md,.csv,.json,.png,.jpg,.jpeg";

export function DropZone({
  fileCount,
  totalBytes,
  dragging,
  onDragging,
  onFilesAdded,
}: {
  fileCount: number;
  totalBytes: number;
  dragging: boolean;
  onDragging: (value: boolean) => void;
  onFilesAdded: (files: FileList | File[] | null) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); onDragging(true); }}
      onDragLeave={() => onDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        onDragging(false);
        onFilesAdded(e.dataTransfer.files);
      }}
      onClick={() => inputRef.current?.click()}
      className={cn(
        "mt-7 w-full max-w-2xl cursor-pointer rounded-2xl border-[1.5px] border-dashed px-6 py-10 text-center transition-all",
        dragging
          ? "border-steel-500 bg-navy-50"
          : "border-navy-200 bg-white hover:border-steel-400",
      )}
    >
      <UploadCloud size={28} className="mx-auto text-steel-500" />
      <div className="mt-2 text-[14px] font-medium text-navy-800">
        Drop files here or click to browse
      </div>
      <div className="mt-1 text-[12px] text-subtle">
        {fileCount === 0
          ? "PDF · DOCX · PPTX · CSV · JSON · images"
          : `${fileCount} file${fileCount === 1 ? "" : "s"} ready · ${(totalBytes / 1024 / 1024).toFixed(1)} MB`}
      </div>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => onFilesAdded(e.target.files)}
      />
    </div>
  );
}
