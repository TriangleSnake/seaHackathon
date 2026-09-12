import { AppShell } from "@/components/app-shell";
import { AssociationGraph } from "@/features/association/association-graph";
import { AssociationLive } from "@/features/association/association-live";
import { AssociationPageContent } from "@/features/association/association-page-content";

export default function AssociationPage(){return <AppShell><AssociationPageContent demo={<AssociationGraph/>} live={<AssociationLive/>}/></AppShell>}
