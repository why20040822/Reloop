import type { ReactNode } from "react";
import type { Talent } from "../lib/api";

export function PageHeading({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return <header className="page-heading"><div><h1>{title}</h1>{description && <p>{description}</p>}</div>{action && <div className="page-heading-action">{action}</div>}</header>;
}

export function Avatar({ person, size = "" }: { person: Talent; size?: "" | "large" | "xl" }) { return <span className={`avatar ${size}`}>{person.name.slice(0, 1)}</span>; }
export function KeyValue({ label, value }: { label: string; value?: string | null }) { return <div className="key-value"><span>{label}</span><strong>{value || "—"}</strong></div>; }
export function Notice({ tone, children }: { tone: "error" | "success" | "info"; children: ReactNode }) { return <p className={`notice ${tone}`}>{children}</p>; }
export function Loading() { return <div className="loading">正在加载…</div>; }
export function Empty({ text }: { text: string }) { return <div className="empty">{text}</div>; }
export function number(value?: number | null) { return value == null ? "—" : value.toFixed(2); }
export function errorMessage(error: unknown) { return error instanceof Error ? error.message : "请求未完成，请稍后重试。"; }
