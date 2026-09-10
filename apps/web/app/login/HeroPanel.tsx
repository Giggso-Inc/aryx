import { Shield } from "lucide-react";

export function HeroPanel() {
  return (
    <section className="rounded-[2rem] bg-[radial-gradient(circle_at_top_left,_rgba(64,104,168,0.18),_transparent_42%),linear-gradient(140deg,_rgba(10,21,48,0.98),_rgba(15,31,61,0.94))] px-8 py-10 text-white shadow-soft">
      <div className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] text-white/75">
        <Shield size={13} />
        Aryx knowledge graph
      </div>
      <h1 className="mt-5 font-display text-5xl leading-tight">
        Login once, move across the Aryx stack.
      </h1>
      <p className="mt-5 max-w-2xl text-base text-white/78">
        Aryx keeps identity, workspaces, ingest, graph retrieval, and Ask in one place.
        Sign in once to manage your workspace and explore the knowledge graph.
      </p>
      <div className="mt-8 grid gap-4 md:grid-cols-3">
        <Feature title="Secure sign-in" body="Email, password, Google, or Microsoft authentication" />
        <Feature title="Shared workspace" body="Company, membership, and source registration in one place" />
        <Feature title="Aryx Ask" body="Questions are answered from the graph with citations" />
      </div>
    </section>
  );
}

function Feature({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-[1.5rem] border border-white/10 bg-white/5 p-4">
      <p className="text-sm font-semibold text-white">{title}</p>
      <p className="mt-2 text-sm text-white/72">{body}</p>
    </div>
  );
}
