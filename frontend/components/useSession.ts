"use client";
import { useCallback, useEffect, useState } from "react";
import { getToken } from "@/lib/api";

// Reads the JWT from localStorage and extracts the username (display only; the server re-checks the token).
export function useSession() {
  const [state, setState] = useState<{ ready: boolean; username: string | null }>({ ready: false, username: null });
  const refresh = useCallback(() => {
    const token = getToken();
    let username: string | null = null;
    try {
      if (token) username = JSON.parse(atob(token.split(".")[1])).username ?? null;
    } catch {
      username = null;
    }
    setState({ ready: true, username });
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  return { ...state, refresh };
}
