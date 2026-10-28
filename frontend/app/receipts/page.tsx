"use client";
import { useCallback, useEffect, useState } from "react";
import Nav from "@/components/Nav";
import { useSession } from "@/components/useSession";
import { api, type Grant, type Receipt } from "@/lib/api";

const LABEL: Record<Receipt["decision"], string> = {
  approved_once: "Allowed once",
  approved_standing: "Allowed (standing)",
  denied: "Denied",
};

export default function Receipts() {
  const { ready, username } = useSession();
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [grants, setGrants] = useState<Grant[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [r, g] = await Promise.all([api.receipts(), api.grants()]);
      setReceipts(r); setGrants(g);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => { if (username) load(); }, [username, load]);

  if (!ready) return null;
  if (!username) return (<><Nav /><p>Please sign in on the Chat page first.</p></>);

  return (
    <>
      <Nav username={username} />
      <h1>Receipts</h1>
      <p className="sub">Every time the agent asked to read your data, and exactly what it was allowed to see.</p>
      {error && <p className="err">{error}</p>}

      <div className="card stack">
        <strong>Standing approvals</strong>
        {grants.length === 0 && <div className="muted">None. The agent asks every time.</div>}
        {grants.map((g) => (
          <div key={g.tool} className="row">
            <code>{g.tool}</code>
            <button className="danger" onClick={async () => { await api.revoke(g.tool); load(); }}>Revoke</button>
          </div>
        ))}
      </div>

      <div className="stack" style={{ marginTop: 16 }}>
        {receipts.length === 0 && <p className="muted">No requests yet.</p>}
        {receipts.map((r) => (
          <div key={r.id} className="card stack">
            <div className="row">
              <strong>{r.tool}</strong>
              <span className="chip">{LABEL[r.decision]}</span>
              <span className="muted">{r.ts} · {r.row_count} {r.row_count === 1 ? "row" : "rows"}</span>
            </div>
            <div className="muted">Filters: {JSON.stringify(r.args)}</div>
            <div>
              {r.fields_shared.map((f) => <span key={f} className="chip shared">{f}</span>)}
              {r.fields_withheld.map((f) => <span key={f} className="chip withheld">{f}</span>)}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
