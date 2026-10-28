const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ConsentRequest = {
  status: "consent_required";
  pending_id: string;
  tool: string;
  args: Record<string, unknown>;
  fields_requested: string[];
  fields_withheld: string[];
  message: string;
};

export type Answer = {
  status: "answered" | "denied";
  answer: string;
  tool: string | null;
  rows: Record<string, unknown>[];
  planner?: string;
  timings_ms?: { plan: number; tool: number; llm: number; total: number };
};

export type ChatResponse = ConsentRequest | Answer;

export type Receipt = {
  id: number;
  tool: string;
  args: Record<string, unknown>;
  decision: "approved_once" | "approved_standing" | "denied";
  fields_shared: string[];
  fields_withheld: string[];
  row_count: number;
  ts: string;
};

export type Stats = {
  requests: number;
  budget_ms: number;
  avg_total_ms?: number;
  p95_total_ms?: number;
  avg_plan_ms?: number;
  avg_tool_ms?: number;
  avg_llm_ms?: number;
  within_budget_pct?: number;
  by_tool?: Record<string, number>;
};

export type Grant = { tool: string; created_at: string };

export function getToken(): string | null {
  try {
    return localStorage.getItem("token");
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem("token", token);
    else localStorage.removeItem("token");
  } catch {
    /* storage unavailable: session just won't persist */
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail ?? `Request failed (${res.status})`);
  }
  return res.json();
}

export const api = {
  login: (username: string) =>
    request<{ token: string; username: string }>("/auth/login", { method: "POST", body: JSON.stringify({ username }) }),
  chat: (message: string) => request<ChatResponse>("/chat", { method: "POST", body: JSON.stringify({ message }) }),
  consent: (id: string, approve: boolean, remember: boolean) =>
    request<Answer>(`/consent/${id}`, { method: "POST", body: JSON.stringify({ approve, remember }) }),
  receipts: () => request<Receipt[]>("/receipts"),
  grants: () => request<Grant[]>("/grants"),
  revoke: (tool: string) => request<{ revoked: string }>(`/grants/${tool}`, { method: "DELETE" }),
  stats: () => request<Stats>("/stats"),
};
