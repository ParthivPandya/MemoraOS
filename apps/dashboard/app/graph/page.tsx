import GraphView, { type GEdge, type GNode } from "@/components/GraphView";
import { Empty, ErrorBox, Header } from "@/components/ui";
import { USER_ID, api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Graph() {
  const r = await api<{ nodes: GNode[]; edges: GEdge[] }>("/v1/graph", { query: { user_id: USER_ID } });
  return (
    <>
      <Header title="Knowledge graph" sub="Relational memory built from stored facts and entity co-mentions." />
      {!r.ok ? <ErrorBox message={r.error} /> : r.data.nodes.length === 0 ? <Empty>The graph is empty.</Empty> : <GraphView nodes={r.data.nodes.slice(0, 120)} edges={r.data.edges} />}
    </>
  );
}
