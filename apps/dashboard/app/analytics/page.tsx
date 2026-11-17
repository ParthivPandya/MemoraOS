import { Empty, ErrorBox, Header, Stat } from "@/components/ui";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

type Usage = { provider: string; model: string | null; kind: string; calls: number; tokens_in: number; tokens_out: number; cost: number; mean_latency_ms: number };
type Stats = { mean_context_tokens: number; recalls: number; query_cache: { hits: number; misses: number }; provider_usage: { calls: number; tokens_in: number; tokens_out: number; cost: number } };

export default async function Analytics() {
  const [u, s] = await Promise.all([api<Usage[]>("/v1/usage"), api<Stats>("/v1/stats")]);
  return (
    <>
      <Header title="Token and cost analytics" sub="Provider usage recorded by the engine. Default local operation makes no provider calls, so these are zero until you configure one." />
      {s.ok && (
        <div className="grid">
          <Stat k="Mean evidence tokens / recall" v={s.data.mean_context_tokens} />
          <Stat k="Query cache hits / misses" v={`${s.data.query_cache.hits} / ${s.data.query_cache.misses}`} />
          <Stat k="Provider calls" v={s.data.provider_usage.calls} />
          <Stat k="Provider cost" v={s.data.provider_usage.cost.toFixed(4)} />
        </div>
      )}
      {!u.ok ? <ErrorBox message={u.error} /> : u.data.length === 0 ? <Empty>No provider calls recorded (local-only operation).</Empty> : (
        <table><thead><tr><th>Provider</th><th>Model</th><th>Kind</th><th>Calls</th><th>Tokens in</th><th>Tokens out</th><th>Cost</th><th>Mean latency</th></tr></thead><tbody>
          {u.data.map((x, i) => <tr key={i}><td>{x.provider}</td><td>{x.model}</td><td>{x.kind}</td><td>{x.calls}</td><td>{x.tokens_in}</td><td>{x.tokens_out}</td><td>{x.cost.toFixed(4)}</td><td>{x.mean_latency_ms.toFixed(0)} ms</td></tr>)}
        </tbody></table>
      )}
    </>
  );
}
