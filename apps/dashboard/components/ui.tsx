import type { ReactNode } from "react";

export function Header({ title, sub }: { title: string; sub?: string }) {
  return (
    <>
      <h2>{title}</h2>
      {sub && <p className="sub">{sub}</p>}
    </>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return <div className="error" role="alert">{message}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Stat({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="card">
      <div className="k">{k}</div>
      <div className="v">{v}</div>
    </div>
  );
}

export function Badge({ tone, children }: { tone?: "ok" | "warn" | "bad"; children: ReactNode }) {
  return <span className={`badge ${tone ?? ""}`}>{children}</span>;
}

export function pct(x: number | null | undefined): string {
  return x == null ? "–" : `${(100 * x).toFixed(1)}%`;
}

export function statusTone(s: string): "ok" | "warn" | "bad" {
  return s === "answered" ? "ok" : s === "conflict" ? "warn" : "bad";
}
