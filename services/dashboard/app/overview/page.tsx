import { AppShell } from "@/components/app-shell";
import { CaseStatusBadge } from "@/components/case-status";
import { cases } from "@/lib/api/cases";
import { ArrowRight, BriefcaseBusiness, CircleCheck, Clock3, FileSearch, ShieldAlert, TrendingUp } from "lucide-react";
import Link from "next/link";
import { OverviewCharts } from "@/features/overview/overview-charts";
import { RuntimeGraph } from "@/features/overview/runtime-graph";
import { LiveOverview } from "@/features/overview/live-overview";

const reviewCases = cases.filter((item) => item.status === "review");

export default function OverviewPage() {
  if (process.env.DASHBOARD_DATA_MODE !== "demo") return <AppShell><LiveOverview/></AppShell>;
  return <AppShell><div className="overview-page"><div className="page-head"><div><div className="breadcrumb">Operations / 2026 年 9 月 12 日</div><h1>營運總覽</h1><p>優先處理需要人工判斷的案件，其餘調查流程持續在背景執行。</p></div><div className="overview-health"><span/><div><strong>防禦系統正常</strong><small>12 個服務在線</small></div></div></div>
    <section className="metric-row" aria-label="今日摘要">
      <div className="metric-card"><BriefcaseBusiness/><span>今日案件</span><strong>128</strong><small><b>+12%</b> 相較昨日</small></div>
      <div className="metric-card attention"><FileSearch/><span>待人工審核</span><strong>{reviewCases.length}</strong><small>最久等待 18 分鐘</small></div>
      <div className="metric-card"><ShieldAlert/><span>已確認詐欺</span><strong>24</strong><small>占今日案件 18.8%</small></div>
      <div className="metric-card"><CircleCheck/><span>正常／誤判</span><strong>67</strong><small>誤判率 4.2%</small></div>
    </section>
    <RuntimeGraph/>
    <OverviewCharts/>
    <div className="overview-grid"><section className="panel review-panel"><div className="section-title"><div><span>REVIEW QUEUE</span><h2>待人工審核</h2><p>依風險與等待時間排序，點擊案件查看完整證據。</p></div><Link href="/cases">查看所有案件 <ArrowRight size={15}/></Link></div><div className="review-list">{reviewCases.map((item) => <Link href={`/cases/${item.id}`} className="review-row" key={item.id}><div className="review-risk"><strong>{item.fraudScore?.toFixed(2)}</strong><span>Fraud Score</span></div><div className="review-main"><div><code>{item.id}</code><CaseStatusBadge value={item.verdict}/></div><strong>{item.subject}</strong><p>{item.summary}</p><div className="trigger-list">{item.triggers.map((trigger) => <span key={trigger}>{trigger}</span>)}</div></div><div className="review-meta"><Clock3 size={14}/><span>{item.updatedAt}</span><small>{item.evidenceCount} 項證據</small><ArrowRight size={17}/></div></Link>)}</div></section>
      <aside className="overview-side"><section className="panel ops-panel"><div className="section-title"><div><span>INVESTIGATION</span><h2>調查作業量</h2></div></div><div className="ops-number"><strong>9</strong><span>進行中</span></div><div className="ops-bars"><div><span>Agent 呼叫</span><b>38 / 72</b></div><i><span style={{width:"53%"}}/></i><div><span>今日成本</span><b>$18.42 / $40</b></div><i><span style={{width:"46%"}}/></i></div></section><section className="panel signal-panel"><div className="section-title"><div><span>EMERGING SIGNAL</span><h2>需注意的變化</h2></div><TrendingUp size={18}/></div><strong>外部付款連結話術增加</strong><p>過去 6 小時在 14 個帳號中重複出現，較七日基準高出 2.4 倍。</p><span>Evolution 正在分析</span></section></aside>
    </div>
  </div></AppShell>;
}
