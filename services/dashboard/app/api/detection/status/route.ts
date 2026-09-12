import { NextResponse } from "next/server";

const baseUrl = () => (process.env.DASHBOARD_DETECTION_URL ?? process.env.DETECTION_URL ?? "http://127.0.0.1:10001").replace(/\/$/, "");

async function probe(path: string) {
  const response = await fetch(`${baseUrl()}/${path}`, { cache: "no-store", signal: AbortSignal.timeout(4_000) });
  const data = await response.json().catch(() => ({}));
  return { ok: response.ok, data };
}

export async function GET() {
  const started = performance.now();
  try {
    const [health, readiness] = await Promise.all([probe("health"), probe("ready")]);
    const reachable = health.ok;
    const ready = reachable && readiness.ok;
    return NextResponse.json({
      service: health.data.service ?? "fraud-detection",
      reachable,
      ready,
      status: ready ? "ready" : "degraded",
      dependencies: readiness.data.dependencies ?? {},
      latencyMs: Math.round(performance.now() - started),
      checkedAt: new Date().toISOString(),
      ...(!readiness.ok && readiness.data.error?.message ? { error: readiness.data.error.message } : {}),
    });
  } catch (error) {
    const timedOut = error instanceof Error && error.name === "TimeoutError";
    return NextResponse.json({
      service: "fraud-detection",
      reachable: false,
      ready: false,
      status: "unavailable",
      dependencies: {},
      latencyMs: Math.round(performance.now() - started),
      checkedAt: new Date().toISOString(),
      error: timedOut ? "Detection service timed out." : "Detection service is unavailable.",
    });
  }
}
