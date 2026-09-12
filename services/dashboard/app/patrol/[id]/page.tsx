import { AppShell } from "@/components/app-shell";
import { PatrolRunDetail } from "@/features/patrol/patrol-run-detail";
import { patrolRuns } from "@/lib/api/patrol";
import { notFound } from "next/navigation";

export function generateStaticParams() { return patrolRuns.map((run) => ({ id: run.id })); }

export default async function PatrolRunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const run = patrolRuns.find((item) => item.id === id);
  if (!run) notFound();
  return <AppShell><PatrolRunDetail run={run}/></AppShell>;
}
