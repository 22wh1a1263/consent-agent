"use client";
import { useState } from "react";
import Nav from "@/components/Nav";
import { useSession } from "@/components/useSession";
import { api, setToken, type Answer, type ConsentRequest } from "@/lib/api";

type Msg = { role: "user" | "assistant"; text: string; meta?: string };

const SUGGESTIONS = [
  "How much did I spend on food this month?",
  "Top 3 merchants in September",
  "Show my last 5 transactions",
];

function Login({ onDone }: { onDone: () => void }) {
  const [error, setError] = useState("");
  async function go(username: string) {
    try {
      const res = await api.login(username);
      setToken(res.token);
      onDone();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <div className="card stack">
      <h1>Sign in</h1>
      <p className="sub">Demo accounts with fake expense data. Each one can only see its own rows.</p>
      <div className="row">
        <button className="primary" onClick={() => go("alice")}>Continue as Alice</button>
        <button onClick={() => go("bob")}>Continue as Bob</button>
      </div>
      {error && <p className="err">{error}. Is the API running on port 8000?</p>}
    </div>
  );
}

function ConsentCard({ req, busy, onDecide }: {
  req: ConsentRequest; busy: boolean; onDecide: (approve: boolean, remember: boolean) => void;
}) {
  return (
    <div className="consent stack">
      <strong>Permission needed</strong>
      <div>{req.message}</div>
      <div>
        <div className="muted">Will be shared with the AI</div>
        {req.fields_requested.map((f) => <span key={f} className="chip shared">{f}</span>)}
        <div className="muted" style={{ marginTop: 6 }}>Never shared</div>
        {req.fields_withheld.map((f) => <span key={f} className="chip withheld">{f}</span>)}
      </div>
      <div className="muted">Filters: {JSON.stringify(req.args)}</div>
      <div className="row">
        <button className="primary" disabled={busy} onClick={() => onDecide(true, false)}>Allow once</button>
        <button disabled={busy} onClick={() => onDecide(true, true)}>Always allow this tool</button>
        <button className="danger" disabled={busy} onClick={() => onDecide(false, false)}>Deny</button>
      </div>
    </div>
  );
}

export default function Home() {
  const { ready, username, refresh } = useSession();
  const [messages, setMessages] = useState<Msg[]>([]);
  const [pending, setPending] = useState<ConsentRequest | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function handleAnswer(a: Answer) {
    const t = a.timings_ms;
    setMessages((m) => [...m, {
      role: "assistant", text: a.answer,
      meta: t ? `${a.tool ?? "no tool"} · ${t.total} ms (plan ${t.plan}, tool ${t.tool}, llm ${t.llm})` : undefined,
    }]);
  }

  async function send(text: string) {
    if (!text.trim() || busy || pending) return;
    setBusy(true); setError(""); setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    try {
      const res = await api.chat(text);
      if (res.status === "consent_required") setPending(res);
      else handleAnswer(res);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function decide(approve: boolean, remember: boolean) {
    if (!pending) return;
    setBusy(true); setError("");
    try {
      const res = await api.consent(pending.pending_id, approve, remember);
      setPending(null);
      handleAnswer(res);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!ready) return null;
  if (!username) {
    return (<><Nav /><Login onDone={refresh} /></>);
  }

  return (
    <>
      <Nav username={username} />
      <h1>Ask about your expenses</h1>
      <p className="sub">The AI plans first, then asks before it touches any data.</p>
      <div className="stack">
        {messages.length === 0 && (
          <div className="row">
            {SUGGESTIONS.map((s) => <button key={s} onClick={() => send(s)}>{s}</button>)}
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <span className="bubble">{m.text}</span>
            {m.meta && <div className="muted">{m.meta}</div>}
          </div>
        ))}
        {pending && <ConsentCard req={pending} busy={busy} onDecide={decide} />}
        {error && <p className="err">{error}</p>}
        <form className="row" onSubmit={(e) => { e.preventDefault(); send(input); }}>
          <input type="text" value={input} onChange={(e) => setInput(e.target.value)}
            placeholder={pending ? "Respond to the permission request first" : "Ask something…"}
            disabled={busy || !!pending} aria-label="Message" />
          <button className="primary" disabled={busy || !!pending || !input.trim()}>Send</button>
        </form>
      </div>
    </>
  );
}
