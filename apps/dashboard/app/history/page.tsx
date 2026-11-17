import { Badge, Empty, ErrorBox, Header } from "@/components/ui";
import { USER_ID, api } from "@/lib/api";

export const dynamic = "force-dynamic";

type Entry = { value: string; valid_from: string | null; valid_until: string | null; recorded_at: string; status: string; source_reliability: number; inferred_start: boolean; memory_ids: string[]; note: string | null };
type Hist = { timeline: Entry[]; contradictions: { kind: string; resolved: boolean; justification: string; values: string[] }[] };

export default async function History({ searchParams }: { searchParams: Promise<{ subject?: string; predicate?: string }> }) {
  const { subject = "", predicate = "" } = await searchParams;
  const r = subject && predicate ? await api<Hist>("/v1/history", { query: { subject, predicate, user_id: USER_ID } }) : null;
  return (
    <>
      <Header title="Temporal history" sub="Every value a fact has had, with valid time (when true) and recorded time (when learned)." />
      <form className="row" method="get">
        <input name="subject" defaultValue={subject}         placeholder="subject, e.g. Python 3.14" aria-label="Subject" />
                <input name="predicate" defaultValue={predicate} placeholder="predicate, e.g. latest version" aria-label="Predicate" />
        <button>Show</button>
      </form>
      {!r ? <Empty>Enter a subject and predicate.</Empty> : !r.ok ? <ErrorBox message={r.error} /> : r.data.timeline.length === 0 ? <Empty>No facts recorded for that subject and predicate.</Empty> : (
        <>
          <table><thead><tr><th>Value</th><th>Status</th><th>Valid from</th><th>Valid until</th><th>Recorded</th><th>Reliability</th><th>Memories</th></tr></thead><tbody>
            {r.data.timeline.map((t, i) => (
              <tr key={i}>
                <td>{t.value}{t.note && <div className="sub">{t.note}</div>}</td>
                <td><Badge tone={t.status === "current" ? "ok" : t.status === "conflicted" ? "warn" : undefined}>{t.status}</Badge></td>
                <td>{t.valid_from?.slice(0, 10) ?? (t.inferred_start ? "unknown" : "–")}</td>
                <td>{t.valid_until?.slice(0, 10) ?? "–"}</td>
                <td className="mono">{t.recorded_at.slice(0, 19)}</td>
                <td>{t.source_reliability.toFixed(2)}</td>
                <td className="mono">{t.memory_ids.join(", ")}</td>
              </tr>
            ))}
          </tbody></table>
          {r.data.contradictions.length > 0 && <table><tbody>{r.data.contradictions.map((c, i) => <tr key={i}><td>{c.values.join(" vs ")}</td><td>{c.kind}{c.resolved ? " (resolved)" : " (open)"}</td><td>{c.justification}</td></tr>)}</tbody></table>}
        </>
      )}
    </>
  );
}
