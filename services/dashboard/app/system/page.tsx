import { Activity, CheckCircle2, Clock3, Database, Server, Waypoints } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { systemServices } from "@/lib/api/operations";
import { LiveSystemStatus } from "@/features/system/live-system-status";

export default function SystemPage() {
  if (process.env.DASHBOARD_DATA_MODE !== "demo") return <AppShell><div className="page-head"><div><div className="breadcrumb">Infrastructure / Live</div><h1>系統控制台</h1><p>直接探測已部署元件與 Control Plane 狀態。</p></div></div><LiveSystemStatus/></AppShell>;
  return <AppShell>
    <div className="page-head"><div><div className="breadcrumb">Infrastructure / Live</div><h1>系統控制台</h1><p>檢視服務健康度與執行狀態。</p></div><span className="workspace-badge healthy"><i/>系統運作中</span></div>
    <section className="system-metrics"><div><CheckCircle2/><span>可用率</span><strong>99.96%</strong><small>過去 30 日</small></div><div><Clock3/><span>P95 延遲</span><strong>84 ms</strong><small>過去 15 分鐘</small></div><div><Activity/><span>每分鐘請求</span><strong>1,284</strong><small>錯誤率 0.08%</small></div><div><Waypoints/><span>Active Traces</span><strong>42</strong><small>6 個調查流程</small></div></section>
    <section className="panel service-panel"><header><div><span>COMPONENT HEALTH</span><h2>服務元件</h2></div><span>最後更新：剛剛</span></header><div className="service-list">{systemServices.map(([name, endpoint, status, latency, version]) => <article key={name}><div className={`service-icon ${status}`}>{name.includes("DB") ? <Database size={16}/> : <Server size={16}/>}</div><div><strong>{name}</strong><code>{endpoint}</code></div><span className={`service-status ${status}`}><CheckCircle2 size={12}/> {status === "healthy" ? "正常" : "效能降級"}</span><dl><div><dt>Latency</dt><dd>{latency}</dd></div><div><dt>Version</dt><dd>{version}</dd></div></dl></article>)}</div></section>
  </AppShell>;
}
