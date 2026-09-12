import { NextRequest, NextResponse } from "next/server";

const baseUrl = () => (process.env.DASHBOARD_SYSTEM_URL ?? process.env.SYSTEM_URL ?? "http://127.0.0.1:10005").replace(/\/$/, "");

function isAllowed(method: string, path: string) {
  if (method === "GET" && ["health", "ready", "control/triggers", "control/schedules", "jobs"].includes(path)) return true;
  if (method === "GET" && /^jobs\/job-[a-f0-9]{24}$/.test(path)) return true;
  if (method === "POST" && path === "jobs") return true;
  if (method === "PUT" && /^control\/(triggers|schedules)\/[A-Za-z0-9][A-Za-z0-9._-]*$/.test(path)) return true;
  return false;
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const path = (await context.params).path.join("/");
  if (!isAllowed(request.method, path)) {
    return NextResponse.json({ error: { code: "not_found", message: "Unknown System endpoint." } }, { status: 404 });
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8_000);
  try {
    const body = request.method === "GET" ? undefined : await request.text();
    const upstream = await fetch(`${baseUrl()}/${path}${request.nextUrl.search}`, {
      method: request.method,
      body,
      cache: "no-store",
      signal: controller.signal,
      headers: body ? { "content-type": request.headers.get("content-type") ?? "application/json" } : undefined,
    });
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
    });
  } catch (error) {
    const timedOut = error instanceof Error && error.name === "AbortError";
    return NextResponse.json({
      error: { code: "system_unavailable", message: timedOut ? "System service timed out." : "System service is unavailable." },
    }, { status: 503 });
  } finally {
    clearTimeout(timeout);
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
