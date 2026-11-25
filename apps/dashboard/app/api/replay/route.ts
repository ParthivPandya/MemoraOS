import { USER_ID, api } from "@/lib/api";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const body = (await req.json().catch(() => null)) as { recall_id?: unknown; exclude?: unknown } | null;
  const exclude = body?.exclude;
  if (typeof body?.recall_id !== "string" || !Array.isArray(exclude) || exclude.length === 0 || exclude.length > 20 || exclude.some((x) => typeof x !== "string" || x.length > 80)) {
    return NextResponse.json({ detail: "recall_id and 1-20 memory ids in exclude are required" }, { status: 422 });
  }
  const r = await api("/v1/replay", { method: "POST", body: { user_id: USER_ID, recall_id: body.recall_id, exclude } });
  return r.ok ? NextResponse.json(r.data) : NextResponse.json({ detail: r.error }, { status: 502 });
}
