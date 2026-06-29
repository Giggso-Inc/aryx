import Image from "next/image";
import { cn } from "@/lib/cn";

interface LogoProps {
  size?: number;
  withWordmark?: boolean;
  className?: string;
}

/** Aryx mark — wolf shield, optionally with the wordmark below. */
export function Logo({ size = 40, withWordmark = false, className }: LogoProps) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <Image
        src="/aryx-logo.png"
        alt="Aryx"
        width={size}
        height={size}
        priority
        className="select-none"
      />
      {withWordmark && (
        <span className="wordmark text-[1.05rem]">ARYX</span>
      )}
    </div>
  );
}
