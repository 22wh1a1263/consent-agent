"use client";
import { useEffect, useState } from "react";
import Nav from "@/components/Nav";
import { useSession } from "@/components/useSession";
import { api, type Stats } from "@/lib/api";

export default function StatsPage() {
  const { ready, username } = useSession();
  const [s, setS] = useState<Stats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (username) api.stats().then(setS).catch((e) => setError((e as Error).message));
  }, [username]);

  if (!ready) return null;
  if (!username) return (<><Nav /><p>Please sign in on the Chat page first.</p></>);

  const total = s?.avg_total_ms ?? 0;
  const part = (v?: number) => (total > 0 && v !== undefined ? Math.max(2, (v / total) * 100) : 0);

  return (
    <>
      <Nav username={username} />
      <h1>Latency &amp; quality</h1>
      <p className="sub">Measured on your own requests, so we don&apos;t fool ourselves.</p>
      {error && <p className="err">{error}</p>}
      {s && s.requests === 0 && <p className="muted">No requests yet. Ask something on the Chat page.</p>}
      {s && s.requests > 0 && (
        <div className="stack">
          <div className="grid">
            <div className="card stat"><span className="muted">Requests</span><b>{s.requests}</b></div>
            <div className="card stat"><span className="muted">Average</span><b>{s.avg_total_ms} ms</b></div>
            <div className="card stat"><span className="muted">p95</span><b>{s.p95_total_ms} ms</b></div>
            <div className="card stat">
              <span className="muted">Within {s.budget_ms} ms budget</span><b>{s.within_budget_pct}%</b>
            </div>
          </div>
          <div className="card stack">
            <strong>Where the time goes (average)</strong>
            {([["Planning", s.avg_plan_ms], ["Tool / database", s.avg_tool_ms], ["Answer writing", s.avg_llm_ms]] as const).map(
              ([label, v]) => (
                <div key={label}>
                  <div className="row"><span>{label}</span><span className="muted">{v} ms</span></div>
                  <div className="bar"><span style={{ width: `${part(v)}%` }} /></div>
                </div>
              ),
            )}
          </div>
          <div className="card">
            <strong>Tool usage</strong>
            <table><tbody>
              {Object.entries(s.by_tool ?? {}).map(([k, v]) => (<tr key={k}><td><code>{k}</code></td><td>{v}</td></tr>))}
            </tbody></table>
          </div>
        </div>
      )}
    </>
  );
}
