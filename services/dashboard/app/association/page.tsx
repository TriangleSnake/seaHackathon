import { AppShell } from "@/components/app-shell";
import { AssociationGraph } from "@/features/association/association-graph";

export default function AssociationPage(){return <AppShell><div className="page-head"><div><div className="breadcrumb">Intelligence / Entity Graph</div><h1>關聯分析</h1><p>檢視實體、證據與案件之間的動態關聯。</p></div></div><AssociationGraph/></AppShell>}
