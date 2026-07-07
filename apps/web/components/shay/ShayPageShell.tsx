"use client";

import type { ReactNode } from "react";
import { Header } from "@/components/brand/Header";

interface ShayPageShellProps {
  eyebrow?: string;
  title: string;
  description: string;
  actions?: ReactNode;
  children: ReactNode;
  showHero?: boolean;
}

export function ShayPageShell({
  eyebrow = "Aryx workspace",
  title,
  description,
  actions,
  children,
  showHero = true,
}: ShayPageShellProps) {
  return (
    <div className="min-h-screen bg-canvas">
      <Header />
      <main className="app-shell-offset w-full pb-6 pt-6">
        <div className="workspace-section-shell flex flex-col gap-5">
          <section className="overflow-hidden rounded-[0.75rem] border border-navy-100 bg-white shadow-soft">
            {showHero ? (
              <div className="bg-[radial-gradient(circle_at_top_left,_rgba(64,104,168,0.18),_transparent_48%),linear-gradient(135deg,_rgba(10,21,48,0.96),_rgba(15,31,61,0.93))] px-8 py-10 text-white">
                <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
                  <div className="max-w-3xl">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-white/70">
                      {eyebrow}
                    </p>
                    <h1 className="mt-3 font-display text-[2.75rem] leading-tight md:text-[3.5rem]">
                      {title}
                    </h1>
                    <p className="mt-4 max-w-2xl text-sm text-white/78 md:text-base">
                      {description}
                    </p>
                  </div>
                  {actions ? <div className="shrink-0">{actions}</div> : null}
                </div>
              </div>
            ) : null}
            <div className="px-5 py-5">{children}</div>
          </section>
        </div>
      </main>
    </div>
  );
}
