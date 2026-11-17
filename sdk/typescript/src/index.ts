export type Strategy = "exact" | "bm25" | "vector" | "hybrid" | "graph" | "temporal" | "episodic" | "procedural" | "latent" | "multistage";

export interface Evidence {
  memory_id: string;
  source_id: string | null;
  excerpt: string;
  kind: "fact" | "passage" | "path";
  score: number;
  source_type: string | null;
  source_reliability: number | null;
  verification: string | null;
  effective_at: string | null;
  recorded_at: string | null;
  flags: string[];
}

export interface Confidence {
  extraction_confidence: number | null;
  source_reliability: number | null;
  temporal_validity: "current" | "historical" | "conflicted" | "undated" | "not_applicable";
  retrieval_relevance: number;
  evidence_coverage: number;
  route_confidence: number;
}

export interface Contradiction {
  subject: string;
  slot: string;
  values: string[];
  kind: "conflict" | "update" | "possible_version_change" | "resolved_by_reliability";
  resolved: boolean;
  justification: string;
  memory_ids: string[];
  since: string | null;
}

export interface RecallResult {
  recall_id: string;
  query: string;
  answer: string;
  status: "answered" | "conflict" | "insufficient_evidence";
  supported: boolean;
  strategy: string;
  strategies_tried: string[];
  fallback_used: boolean;
  evidence: Evidence[];
  contradictions: Contradiction[];
  confidence: Confidence;
  flags: string[];
  latency_ms: number;
  context_tokens: number;
  as_of: string | null;
  cached: boolean;
  [key: string]: unknown;
}

export interface RememberResult {
  memory_ids: string[];
  source_id: string;
  duplicate_of: string | null;
  facts_recorded: number;
  conflicts: Contradiction[];
  redactions: number;
}

export class MemoraError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(`HTTP ${status}: ${JSON.stringify(detail)}`);
  }
}

export interface ClientOptions {
  baseUrl?: string;
  apiKey?: string;
  userId: string;
  fetch?: typeof fetch;
}

export class MemoraClient {
  private base: string;
  private f: typeof fetch;

  constructor(private opts: ClientOptions) {
    this.base = (opts.baseUrl ?? "http://127.0.0.1:8000").replace(/\/$/, "");
    this.f = opts.fetch ?? fetch;
  }

  private async req<T>(method: string, path: string, body?: unknown, query?: Record<string, string>): Promise<T> {
    const url = new URL(this.base + path);
    for (const [k, v] of Object.entries(query ?? {})) url.searchParams.set(k, v);
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (this.opts.apiKey) headers["Authorization"] = `Bearer ${this.opts.apiKey}`;
    const res = await this.f(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new MemoraError(res.status, (data as { detail?: unknown } | null)?.detail ?? data);
    return data as T;
  }

  remember(text: string, extra: Record<string, unknown> = {}): Promise<RememberResult> {
    return this.req("POST", "/v1/memories", { text, user_id: this.opts.userId, ...extra });
  }

  recall(query: string, extra: { top_k?: number; as_of?: string; strategy?: Strategy } = {}): Promise<RecallResult> {
    return this.req("POST", "/v1/recall", { query, user_id: this.opts.userId, ...extra });
  }

  correct(memoryId: string, newContent: string, reason?: string): Promise<Record<string, unknown>> {
    return this.req("PATCH", `/v1/memories/${encodeURIComponent(memoryId)}`, { user_id: this.opts.userId, new_content: newContent, reason });
  }

  forget(memoryId: string): Promise<{ deleted: number }> {
    return this.req("DELETE", `/v1/memories/${encodeURIComponent(memoryId)}`, undefined, { user_id: this.opts.userId });
  }

  history(subject: string, predicate: string): Promise<Record<string, unknown>> {
    return this.req("GET", "/v1/history", undefined, { subject, predicate, user_id: this.opts.userId });
  }

  explain(recallId: string): Promise<Record<string, unknown>> {
    return this.req("GET", `/v1/explain/${encodeURIComponent(recallId)}`, undefined, { user_id: this.opts.userId });
  }

  consolidate(mode: "manual" | "incremental" | "dry_run" = "manual"): Promise<Record<string, unknown>> {
    return this.req("POST", "/v1/consolidate", { user_id: this.opts.userId, mode });
  }

  feedback(recallId: string, correct?: boolean, relevance?: number): Promise<{ ok: boolean }> {
    return this.req("POST", "/v1/feedback", { recall_id: recallId, correct, relevance });
  }

  export(): Promise<Record<string, unknown>> {
    return this.req("GET", "/v1/export", undefined, { user_id: this.opts.userId });
  }

  stats(): Promise<Record<string, unknown>> {
    return this.req("GET", "/v1/stats");
  }
}
