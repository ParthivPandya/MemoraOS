import { Badge, Empty, ErrorBox, Header, pct, statusTone } from "@/components/ui";
import { USER_ID, api } from "@/lib/api";

export const dynamic = "force-dynamic";

type Rec = { id: string; ts: string; query: string; category: string; strategy: string; strategies_tried: string[]; status: string; latency_ms: number; context_tokens: number; cached: number };
type Stat = { category: string; strategy: string; n: number; accuracy: number; mean_latency_ms: number; mean_context_tokens: number };

export default async function Strategies() {
  const [recent, learned] = await Promise.all([api<Rec[]>("/v1/recalls", { query: { user_id: USER_ID, limit: "50" } }), api<Stat[]>("/v1/strategies")]);
  return (
    <>
      <Header title="Retrieval strategies" sub="Which strategy answered each recent question, and measured outcomes from feedback." />
      {!recent.ok ? <ErrorBox message={recent.error} /> : recent.data.length === 0 ? <Empty>No recalls yet.</Empty> : (
        <table><thead><tr><th>Question</th><th>Category</th><th>Strategy path</th><th>Status</th><th>Latency</th><th>Tokens</th></tr></thead><tbody>
          {recent.data.map((x) => (
            <tr key={x.id}>
              <td>{x.query}<div className="mono">{x.id}{x.cached ? " · cached" : ""}</div></td><td>{x.category}</td>
              <td className="mono">{x.strategies_tried.join(" → ")}</td>
              <td><Badge tone={statusTone(x.status)}>{x.status}</Badge></td><td>{x.latency_ms.toFixed(1)} ms</td><td>{x.context_tokens}</td>
            </tr>
          ))}
        </tbody></table>
      )}
      <h3>Outcomes by category and strategy (from POST /v1/feedback)</h3>
      {!learned.ok ? <ErrorBox message={learned.error} /> : learned.data.length === 0 ? <Empty>No feedback recorded. Adaptive learning is off by default and needs labelled outcomes.</Empty> : (
        <table><thead><tr><th>Category</th><th>Strategy</th><th>Labelled samples</th><th>Accuracy</th><th>Mean latency</th><th>Mean tokens</th></tr></thead><tbody>
          {learned.data.map((s) => <tr key={s.category + s.strategy}><td>{s.category}</td><td>{s.strategy}</td><td>{s.n}</td><td>{pct(s.accuracy)}</td><td>{s.mean_latency_ms} ms</td><td>{s.mean_context_tokens}</td></tr>)}
        </tbody></table>
      )}
    </>
  );
}
