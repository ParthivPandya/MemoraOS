import { USER_ID, api } from "@/lib/api";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const body = (await req.json().catch(() => null)) as { query?: string; as_of?: string; strategy?: string } | null;
  if (!body?.query || typeof body.query !== "string" || body.query.length > 2000) return NextResponse.json({ detail: "query required (<= 2000 chars)" }, { status: 422 });
  const r = await api("/v1/recall", { method: "POST", body: { query: body.query, user_id: USER_ID, as_of: body.as_of || undefined, strategy: body.strategy || undefined } });
  return r.ok ? NextResponse.json(r.data) : NextResponse.json({ detail: r.error }, { status: 502 });
}
