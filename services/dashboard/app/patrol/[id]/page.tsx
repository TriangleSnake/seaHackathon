import { AppShell } from "@/components/app-shell";
import { PatrolRunDetail } from "@/features/patrol/patrol-run-detail";

export default async function PatrolRunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AppShell><PatrolRunDetail runId={id}/></AppShell>;
}
