import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Consent-Gated Personal Agent",
  description: "An AI assistant that only touches your data after you approve each request.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body><main>{children}</main></body>
    </html>
  );
}
