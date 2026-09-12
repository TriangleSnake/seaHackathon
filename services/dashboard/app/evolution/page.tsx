import { AppShell } from "@/components/app-shell";
import { LiveEvolutionWorkspace } from "@/features/evolution/live-evolution-workspace";

export default function EvolutionPage() {
  const mode = process.env.DASHBOARD_DATA_MODE === "demo" ? "demo" : "live";
  return <AppShell><LiveEvolutionWorkspace mode={mode}/></AppShell>;
}
