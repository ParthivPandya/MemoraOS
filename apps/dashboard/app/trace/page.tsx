import { Badge, Empty, ErrorBox, Header, statusTone } from "@/components/ui";
import { USER_ID, api } from "@/lib/api";

export const dynamic = "force-dynamic";

type Evidence = { memory_id: string; source_id: string | null; excerpt: string; kind: string; verification: string | null; span_start: number | null; span_end: number | null; quote_sha256: string | null; flags: string[] };
type Recall = { recall_id: string; answer: string; status: string; strategy: string; evidence: Evidence[]; flags: string[] };
type Citations = { valid: boolean; verified: number; total: number; results: { memory_id: string; status: string }[] };
type Warning = { memory_id: string; action: string; reason: string | null; recorded_at: string; verified: boolean };
type Lineage = { nodes: { memory_id: string; depth: number; excerpt: string; version: number }[]; edges: { src: string; dst: string; kind: string }[] };
type Replay = {
  baseline_matches_logged: boolean; note: string;
  baseline: { answer: string; status: string };
  runs: { excluded: string[]; answer: string; status: string; answer_changed: boolean; status_changed: boolean }[];
};

/** Recall once, then show everything MemoraOS can say about that answer: citations, outcome warnings, lineage and leave-one-out replay. */
export default async function Trace({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const { q = "" } = await searchParams;
  const rec = q ? await api<Recall>("/v1/recall", { method: "POST", body: { query: q, user_id: USER_ID } }) : null;
  const data = rec?.ok ? rec.data : null;
  const ids = data ? [...new Set(data.evidence.map((e) => e.memory_id))].slice(0, 5) : [];
  const [cites, warns, replay, lineages] = data
    ? await Promise.all([
        api<Citations>("/v1/verify-citations", { method: "POST", body: { user_id: USER_ID, evidence: data.evidence } }),
        api<Warning[]>("/v1/outcome-warnings", { query: { query: q, user_id: USER_ID, limit: "5" } }),
        data.evidence.length > 0 ? api<Replay>("/v1/replay", { method: "POST", body: { user_id: USER_ID, recall_id: data.recall_id, leave_one_out: true } }) : Promise.resolve(null),
        Promise.all(ids.map((id) => api<Lineage>(`/v1/lineage/${encodeURIComponent(id)}`, { query: { user_id: USER_ID, direction: "both", max_depth: "3" } }))),
      ])
    : [null, null, null, []];

  return (
    <>
      <Header title="Answer trace" sub="Why did it say that? Runs one real recall, then checks its citations, lists recorded failed attempts, shows causal lineage and replays the answer with each piece of evidence removed." />
      <form className="row" method="get" aria-label="Trace form">
        <input name="q" defaultValue={q} placeholder="Ask a question about your memories" aria-label="Question" required maxLength={2000} />
        <button>Trace</button>
      </form>
      {!rec ? <Empty>Enter a question.</Empty> : !rec.ok ? <ErrorBox message={rec.error} /> : data && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="k">Answer <Badge tone={statusTone(data.status)}>{data.status}</Badge></div>
            <div style={{ fontSize: 16, margin: "6px 0" }}>{data.answer}</div>
            <div className="mono">strategy {data.strategy} · {data.recall_id}</div>
          </div>

          <h3>Citation check</h3>
          {!cites ? null : !cites.ok ? <ErrorBox message={cites.error} /> : cites.data.total === 0 ? <Empty>No citations to check.</Empty> : (
            <>
              <p>
                <Badge tone={cites.data.valid ? "ok" : cites.data.results.every((r) => r.status === "verified" || r.status === "unlocated") ? "warn" : "bad"}>
                  {cites.data.valid ? "all citations verified" : cites.data.results.every((r) => r.status === "verified" || r.status === "unlocated") ? "not all verbatim" : "citation check failed"}
                </Badge>{" "}
                {cites.data.verified} of {cites.data.total} quotes re-found in their stored source. This proves a quote exists in the source, not that the answer is correct. &quot;unlocated&quot; means the excerpt was never a verbatim span (for example a stored fact), so there is nothing to re-find.
              </p>
              <table><thead><tr><th>Memory</th><th>Status</th><th>Span</th></tr></thead><tbody>
                {cites.data.results.map((r, i) => (
                  <tr key={r.memory_id + i}>
                    <td className="mono">{r.memory_id}</td>
                    <td><Badge tone={r.status === "verified" ? "ok" : r.status === "unlocated" ? "warn" : "bad"}>{r.status}</Badge></td>
                    <td className="mono">{data.evidence[i]?.span_start != null ? `${data.evidence[i].span_start}–${data.evidence[i].span_end}` : "–"}</td>
                  </tr>
                ))}
              </tbody></table>
            </>
          )}

          <h3>Evidence</h3>
          {data.evidence.length === 0 ? <Empty>No supporting evidence.</Empty> : (
            <table><thead><tr><th>Excerpt</th><th>Verification</th></tr></thead><tbody>
              {data.evidence.map((e) => (
                <tr key={e.memory_id + e.excerpt}>
                  <td>{e.excerpt}<div className="mono">{e.memory_id}</div></td>
                  <td><Badge tone={e.verification === "verified" ? "ok" : e.verification === "disputed" ? "bad" : e.verification === "hypothesis" ? "warn" : undefined}>{e.verification ?? "–"}</Badge></td>
                </tr>
              ))}
            </tbody></table>
          )}

          <h3>Recorded failed attempts related to this question</h3>
          {!warns ? null : !warns.ok ? <ErrorBox message={warns.error} /> : warns.data.length === 0 ? <Empty>None recorded.</Empty> : (
            <table><thead><tr><th>Action</th><th>Reason</th><th>Recorded</th><th>Evidence-backed</th></tr></thead><tbody>
              {warns.data.map((w) => (
                <tr key={w.memory_id}><td>{w.action}</td><td>{w.reason ?? "–"}</td><td className="mono">{w.recorded_at.slice(0, 19)}</td><td>{w.verified ? "yes" : "no"}</td></tr>
              ))}
            </tbody></table>
          )}

          <h3>Causal lineage of the cited memories</h3>
          {lineages.length === 0 ? <Empty>Nothing to trace.</Empty> : lineages.every((l) => l.ok && l.data.edges.length === 0) ? (
            <Empty>No causal links recorded for these memories. Links are added manually (memoraos link, POST /v1/links); none are inferred.</Empty>
          ) : (
            <table><thead><tr><th>Memory</th><th>Depth</th><th>Excerpt</th></tr></thead><tbody>
              {lineages.flatMap((l, i) => (l.ok ? l.data.nodes.map((n) => (
                <tr key={ids[i] + n.memory_id}><td className="mono">{n.memory_id}</td><td>{n.depth}</td><td>{n.excerpt}</td></tr>
              )) : []))}
            </tbody></table>
          )}
          {lineages.some((l) => l.ok && l.data.edges.length > 0) && (
            <p className="mono">{[...new Set(lineages.flatMap((l) => (l.ok ? l.data.edges.map((e) => `${e.src} -${e.kind}-> ${e.dst}`) : [])))].join("   ")}</p>
          )}

          <h3>Leave-one-out replay</h3>
          {!replay ? <Empty>No evidence to replay.</Empty> : !replay.ok ? <ErrorBox message={replay.error} /> : (
            <>
              <p className="sub">
                {replay.data.baseline_matches_logged ? "Re-running the query on the current store reproduces the logged answer." : "The store has changed since this recall, so the baseline differs from the logged answer."}{" "}
                {replay.data.note}
              </p>
              <table><thead><tr><th>Removed evidence</th><th>Answer without it</th><th>Changed?</th></tr></thead><tbody>
                {replay.data.runs.map((r, i) => (
                  <tr key={i}>
                    <td className="mono">{r.excluded.join(", ")}</td>
                    <td>{r.answer} <Badge tone={statusTone(r.status)}>{r.status}</Badge></td>
                    <td>{r.answer_changed || r.status_changed ? <Badge tone="warn">yes</Badge> : "no"}</td>
                  </tr>
                ))}
              </tbody></table>
            </>
          )}
        </>
      )}
    </>
  );
}
