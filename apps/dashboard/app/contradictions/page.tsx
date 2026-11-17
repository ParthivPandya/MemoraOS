import { Badge, Empty, ErrorBox, Header } from "@/components/ui";
import { USER_ID, api } from "@/lib/api";

export const dynamic = "force-dynamic";

type C = { subject: string; slot: string; values: string[]; kind: string; resolved: boolean; justification: string; memory_ids: string[]; since: string | null };

export default async function Contradictions() {
  const r = await api<C[]>("/v1/contradictions", { query: { user_id: USER_ID } });
  return (
    <>
      <Header title="Contradiction explorer" sub="Open conflicts are never silently resolved. Version changes and reliability decisions are listed with their justification." />
      {!r.ok ? <ErrorBox message={r.error} /> : r.data.length === 0 ? <Empty>No contradictions or version changes detected.</Empty> : (
        <table><thead><tr><th>Subject / slot</th><th>Values</th><th>Kind</th><th>Justification</th><th>Since</th><th>Memories</th></tr></thead><tbody>
          {r.data.map((c, i) => (
            <tr key={i}>
              <td>{c.subject}<div className="mono">{c.slot}</div></td>
              <td>{c.values.join(" → ")}</td>
              <td><Badge tone={c.resolved ? "ok" : "warn"}>{c.kind}{c.resolved ? "" : " · open"}</Badge></td>
              <td>{c.justification}</td>
              <td className="mono">{c.since?.slice(0, 19) ?? "–"}</td>
              <td className="mono">{c.memory_ids.join(", ")}</td>
            </tr>
          ))}
        </tbody></table>
      )}
    </>
  );
}
