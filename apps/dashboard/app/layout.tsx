import Link from "next/link";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata = { title: "MemoraOS", description: "Developer dashboard for the MemoraOS memory engine" };

const LINKS: [string, string][] = [
  ["/", "Overview"],
  ["/memories", "Memory explorer"],
  ["/playground", "Search playground"],
  ["/trace", "Answer trace"],
  ["/graph", "Knowledge graph"],
  ["/history", "Temporal history"],
  ["/contradictions", "Contradictions"],
  ["/consolidation", "Consolidation"],
  ["/strategies", "Retrieval strategies"],
  ["/benchmarks", "Benchmarks"],
  ["/analytics", "Tokens & cost"],
];

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <nav aria-label="Primary">
            <h1>MemoraOS</h1>
            {LINKS.map(([href, label]) => (
              <Link key={href} href={href}>{label}</Link>
            ))}
          </nav>
          <main>{children}</main>
        </div>
      </body>
    </html>
  );
}
