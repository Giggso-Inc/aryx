"use client";
import { Database, Loader2 } from "lucide-react";

const DIALECTS = ["postgresql", "mysql", "mariadb", "oracle", "sqlite"] as const;
const inp = "focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] focus:border-steel-500";

interface Props {
  useUrl: boolean; setUseUrl: (v: boolean) => void;
  fullUrl: string; setFullUrl: (v: string) => void;
  dialect: string; setDialect: (v: string) => void;
  host: string; setHost: (v: string) => void;
  port: string; setPort: (v: string) => void;
  database: string; setDatabase: (v: string) => void;
  user: string; setUser: (v: string) => void;
  password: string; setPassword: (v: string) => void;
  connecting: boolean; onConnect: () => void;
}

export function DbConnectForm(p: Props) {
  const disabled = p.connecting || (!p.useUrl && !p.host && !p.database) || (p.useUrl && !p.fullUrl);
  return (
    <>
      <label className="mb-3 flex cursor-pointer items-center gap-2 text-[12px] text-navy-600">
        <input type="checkbox" checked={p.useUrl} onChange={(e) => p.setUseUrl(e.target.checked)} className="accent-steel-500" />
        Use connection URL instead
      </label>
      {p.useUrl ? (
        <div className="mb-4">
          <label className="mb-1 block text-[11px] font-medium text-navy-600">Connection URL</label>
          <input value={p.fullUrl} onChange={(e) => p.setFullUrl(e.target.value)}
            placeholder="postgresql://user:pass@host:5432/dbname" className={inp} />
        </div>
      ) : (
        <>
          <div className="mb-3 grid grid-cols-3 gap-3">
            <div>
              <label className="mb-1 block text-[11px] font-medium text-navy-600">RDBMS</label>
              <select value={p.dialect} onChange={(e) => p.setDialect(e.target.value)} className={inp}>
                {DIALECTS.map((d) => <option key={d}>{d}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-navy-600">Host</label>
              <input value={p.host} onChange={(e) => p.setHost(e.target.value)} placeholder="db.example.com" className={inp} />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-navy-600">Port</label>
              <input value={p.port} onChange={(e) => p.setPort(e.target.value)} placeholder="5432" className={inp} />
            </div>
          </div>
          <div className="mb-3">
            <label className="mb-1 block text-[11px] font-medium text-navy-600">Database</label>
            <input value={p.database} onChange={(e) => p.setDatabase(e.target.value)} placeholder="sales" className={inp} />
          </div>
          <div className="mb-4 grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-[11px] font-medium text-navy-600">User</label>
              <input value={p.user} onChange={(e) => p.setUser(e.target.value)} className={inp} />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-navy-600">Password</label>
              <input type="password" value={p.password} onChange={(e) => p.setPassword(e.target.value)} className={inp} />
            </div>
          </div>
        </>
      )}
      <button type="button" onClick={p.onConnect} disabled={disabled}
        className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-4 py-2 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50">
        {p.connecting
          ? <><Loader2 size={13} className="animate-spin" /> Connecting…</>
          : <><Database size={13} /> Connect &amp; introspect</>}
      </button>
    </>
  );
}
