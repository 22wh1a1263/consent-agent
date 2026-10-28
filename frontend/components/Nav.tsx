"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { setToken } from "@/lib/api";

export default function Nav({ username }: { username?: string | null }) {
  const path = usePathname();
  const link = (href: string, label: string) => (
    <Link href={href} className={path === href ? "active" : ""}>{label}</Link>
  );
  return (
    <nav>
      <strong>Consent Agent</strong>
      {link("/", "Chat")}
      {link("/receipts", "Receipts")}
      {link("/stats", "Stats")}
      <span className="spacer" />
      {username && <span className="muted">{username}</span>}
      {username && (
        <button onClick={() => { setToken(null); window.location.href = "/"; }}>Sign out</button>
      )}
    </nav>
  );
}
