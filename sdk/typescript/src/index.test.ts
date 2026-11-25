import assert from "node:assert/strict";
import { test } from "node:test";
import { MemoraClient, MemoraError } from "./index.js";

function fakeFetch(handler: (url: URL, init: RequestInit) => { status: number; body: unknown }): typeof fetch {
  return (async (input: URL | string, init: RequestInit = {}) => {
    const { status, body } = handler(new URL(String(input)), init);
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
}

test("recall sends scoped body and bearer token", async () => {
  let seen: { url?: URL; init?: RequestInit } = {};
  const c = new MemoraClient({
    userId: "u1",
    apiKey: "k",
    fetch: fakeFetch((url, init) => {
      seen = { url, init };
      return { status: 200, body: { answer: "₹32 LPA", status: "answered" } };
    }),
  });
  const r = await c.recall("What is my salary?", { strategy: "exact" });
  assert.equal(r.answer, "₹32 LPA");
  assert.equal(seen.url?.pathname, "/v1/recall");
  assert.deepEqual(JSON.parse(String(seen.init?.body)), { query: "What is my salary?", user_id: "u1", strategy: "exact" });
  assert.equal((seen.init?.headers as Record<string, string>)["Authorization"], "Bearer k");
});

test("errors surface status and detail", async () => {
  const c = new MemoraClient({ userId: "u", fetch: fakeFetch(() => ({ status: 403, body: { detail: "no" } })) });
  await assert.rejects(() => c.forget("mem_1"), (e: unknown) => e instanceof MemoraError && e.status === 403 && e.detail === "no");
});

test("ids are URL encoded and user is a query param", async () => {
  let url!: URL;
  const c = new MemoraClient({ userId: "u 1", fetch: fakeFetch((u) => ((url = u), { status: 200, body: { deleted: 1 } })) });
  await c.forget("a/b");
  assert.equal(url.pathname, "/v1/memories/a%2Fb");
  assert.equal(url.searchParams.get("user_id"), "u 1");
});

test("lineage, replay and outcome calls use the documented routes and bodies", async () => {
  const seen: { path: string; method?: string; body?: unknown; q: Record<string, string> }[] = [];
  const c = new MemoraClient({
    userId: "u1",
    fetch: fakeFetch((url, init) => {
      seen.push({ path: url.pathname, method: init.method, body: init.body ? JSON.parse(String(init.body)) : undefined, q: Object.fromEntries(url.searchParams) });
      return { status: 200, body: {} };
    }),
  });
  await c.lineage("m/1", { direction: "up", maxDepth: 3 });
  await c.replay("rec_1", { leaveOneOut: true });
  await c.link("a", "b", "solves");
  await c.rememberOutcome("deploy", "failed", { reason: "timeout" });
  await c.outcomeWarnings("deploy now", 2);
  await c.verify("m1", "hypothesis");
  await c.verifyCitations([]);
  assert.deepEqual(seen[0], { path: "/v1/lineage/m%2F1", method: "GET", body: undefined, q: { user_id: "u1", direction: "up", max_depth: "3" } });
  assert.deepEqual(seen[1].body, { user_id: "u1", recall_id: "rec_1", exclude: [], leave_one_out: true });
  assert.deepEqual(seen[2].body, { user_id: "u1", src_id: "a", dst_id: "b", kind: "solves" });
  assert.deepEqual(seen[3].body, { user_id: "u1", action: "deploy", outcome: "failed", reason: "timeout" });
  assert.deepEqual(seen[4].q, { query: "deploy now", user_id: "u1", limit: "2" });
  assert.deepEqual(seen[5].body, { user_id: "u1", status: "hypothesis" });
  assert.equal(seen[6].path, "/v1/verify-citations");
});