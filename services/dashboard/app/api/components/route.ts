import { NextResponse } from "next/server";

const targets = [
  ["System", process.env.DASHBOARD_SYSTEM_URL ?? "http://system:10005"], ["Detection", process.env.DASHBOARD_DETECTION_URL ?? "http://detection:8000"],
  ["Investigation", process.env.DASHBOARD_INVESTIGATION_URL ?? "http://investigation:8000"], ["Patrol", process.env.DASHBOARD_PATROL_URL ?? "http://patrol:10003"],
  ["Association", process.env.DASHBOARD_ASSOCIATION_URL ?? "http://association:10004"], ["Governance", process.env.DASHBOARD_GOVERNANCE_URL ?? "http://governance:8000"],
  ["Evolution", process.env.DASHBOARD_EVOLUTION_URL ?? "http://evolution:8000"],
] as const;

export async function GET(){const checked_at=new Date().toISOString();const components=await Promise.all(targets.map(async([name,base])=>{const started=performance.now();try{const response=await fetch(`${base.replace(/\/$/,"")}/health`,{cache:"no-store",signal:AbortSignal.timeout(3000)});const detail=await response.json().catch(()=>({}));return{name,endpoint:new URL(base).host,status:response.ok?"healthy":"degraded",latency_ms:Math.round(performance.now()-started),detail}}catch(error){return{name,endpoint:new URL(base).host,status:"unavailable",latency_ms:Math.round(performance.now()-started),detail:{error:error instanceof Error?error.message:"unavailable"}}}}));return NextResponse.json({checked_at,components})}
