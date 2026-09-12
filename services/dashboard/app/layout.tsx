import type { Metadata } from "next";
import "./globals.css";
import "./operations.css";
import "./evidence.css";
import "./flow.css";
import "./investigation.css";
import "@xyflow/react/dist/style.css";
import "./workspace.css";
import "./graph.css";
import "./association.css";
import "./agent-policy.css";
import "./patrol.css";
import "./runtime-graph.css";
import "./data-mode.css";
import "./model-control.css";
import "./evolution-live.css";
import { Providers } from "./providers";
import type { DashboardMode } from "@/lib/dashboard-mode";

export const metadata: Metadata = { title: "Sentinel · Fraud Intelligence", description: "AI-native fraud operations console" };
export const dynamic = "force-dynamic";

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const mode: DashboardMode = process.env.DASHBOARD_DATA_MODE === "demo" ? "demo" : "live";
  return <html lang="zh-Hant" data-dashboard-mode={mode}><body><Providers mode={mode}>{children}</Providers></body></html>;
}
