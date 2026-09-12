import { NextRequest, NextResponse } from "next/server";

const baseUrl = () => (process.env.DASHBOARD_INVESTIGATION_URL ?? process.env.INVESTIGATION_URL ?? "http://127.0.0.1:10002").replace(/\/$/, "");

export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const path = (await context.params).path.join("/");
  if (!["health", "ready", "policies/investigation", "agents"].includes(path)) return NextResponse.json({ error: { code: "not_found", message: "Unknown Investigation endpoint." } }, { status: 404 });
  try {
    const upstream = await fetch(`${baseUrl()}/${path}`, { cache: "no-store", signal: AbortSignal.timeout(8_000) });
    return new NextResponse(await upstream.text(), { status: upstream.status, headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" } });
  } catch (error) {
    const timedOut = error instanceof Error && error.name === "TimeoutError";
    return NextResponse.json({ error: { code: "investigation_unavailable", message: timedOut ? "Investigation service timed out." : "Investigation service is unavailable." } }, { status: 503 });
  }
}
