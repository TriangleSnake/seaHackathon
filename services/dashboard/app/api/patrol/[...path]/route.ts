import { NextRequest, NextResponse } from "next/server";

const baseUrl = () => (process.env.DASHBOARD_PATROL_URL ?? process.env.PATROL_URL ?? "http://127.0.0.1:10003").replace(/\/$/, "");

function isAllowed(method: string, path: string) {
  if(method === "GET" && (path === "health" || path === "patrol/jobs" || path === "policies/patrol" || /^patrol\/jobs\/[A-Za-z0-9][A-Za-z0-9._-]*$/.test(path))) return true;
  return method === "POST" && /^policies\/patrol\/(exploit|explore)\/(validate|drafts|publish)$/.test(path);
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const path = (await context.params).path.join("/");
  if (!isAllowed(request.method, path)) return NextResponse.json({ error: { code: "not_found", message: "Unknown Patrol endpoint." } }, { status: 404 });
  try {
    const body=request.method==="GET"?undefined:await request.text();
    const upstream = await fetch(`${baseUrl()}/${path}${request.nextUrl.search}`, { method:request.method,body,headers:body?{"content-type":"application/json"}:undefined,cache: "no-store", signal: AbortSignal.timeout(8_000) });
    return new NextResponse(await upstream.text(), { status: upstream.status, headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" } });
  } catch (error) {
    const timedOut = error instanceof Error && error.name === "TimeoutError";
    return NextResponse.json({ error: { code: "patrol_unavailable", message: timedOut ? "Patrol service timed out." : "Patrol service is unavailable." } }, { status: 503 });
  }
}

export const GET = proxy;
export const POST = proxy;
