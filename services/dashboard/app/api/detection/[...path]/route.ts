import { NextRequest, NextResponse } from "next/server";

const baseUrl = () => (process.env.DASHBOARD_DETECTION_URL ?? process.env.DETECTION_URL ?? "http://127.0.0.1:10001").replace(/\/$/, "");

const allowed = new Set([
  "GET health",
  "GET ready",
  "GET policies/detection",
  "POST detect",
  "POST policies/detection/validate",
  "POST policies/detection/drafts",
  "POST policies/detection/test",
  "POST policies/detection/publish",
]);

function isAllowed(method: string, path: string) {
  return allowed.has(`${method} ${path}`) || (method === "POST" && /^policies\/detection\/rollback\/[A-Za-z0-9][A-Za-z0-9._-]*$/.test(path));
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const path = (await context.params).path.join("/");
  if (!isAllowed(request.method, path)) return NextResponse.json({ error: { code: "not_found", message: "Unknown Detection endpoint." } }, { status: 404 });

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 6_000);
  try {
    const search = request.nextUrl.search;
    const body = request.method === "GET" ? undefined : await request.text();
    const upstream = await fetch(`${baseUrl()}/${path}${search}`, {
      method: request.method,
      body,
      cache: "no-store",
      signal: controller.signal,
      headers: {
        ...(body ? { "content-type": request.headers.get("content-type") ?? "application/json" } : {}),
        ...(request.headers.get("x-request-id") ? { "x-request-id": request.headers.get("x-request-id")! } : {}),
      },
    });
    const responseBody = await upstream.text();
    return new NextResponse(responseBody, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
        ...(upstream.headers.get("x-request-id") ? { "x-request-id": upstream.headers.get("x-request-id")! } : {}),
        ...(upstream.headers.get("x-detection-policy-version") ? { "x-detection-policy-version": upstream.headers.get("x-detection-policy-version")! } : {}),
      },
    });
  } catch (error) {
    const message = error instanceof Error && error.name === "AbortError" ? "Detection service timed out." : "Detection service is unavailable.";
    return NextResponse.json({ error: { code: "detection_unavailable", message } }, { status: 503 });
  } finally {
    clearTimeout(timeout);
  }
}

export const GET = proxy;
export const POST = proxy;
