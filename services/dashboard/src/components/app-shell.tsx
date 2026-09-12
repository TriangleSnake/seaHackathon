"use client";

import { Activity, Bell, BookOpenCheck, Boxes, ChartNoAxesCombined, ChevronsUp, CircleGauge, DatabaseZap, Menu, Radar, Search, ShieldAlert, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useDashboardMode } from "@/lib/dashboard-mode";
import { DefenseContent } from "@/features/defense/defense-page";

const nav = [
  ["總覽", "/overview", CircleGauge], ["案件", "/cases", ShieldAlert], ["關聯分析", "/association", Boxes], ["自主巡查", "/patrol", Radar],
  ["策略演化與防禦版本", "/evolution", ChevronsUp], ["Agent Policy", "/policies", BookOpenCheck], ["系統狀態", "/system", Activity]
] as const;

export function AppShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const mode = useDashboardMode();
  const hasLiveReadModel = pathname === "/evolution" || pathname === "/system" || pathname === "/overview" || pathname === "/policies" || pathname.startsWith("/policies/detection") || pathname.startsWith("/policies/patrol") || pathname.startsWith("/policies/association") || pathname.startsWith("/policies/investigation") || pathname === "/patrol" || pathname.startsWith("/patrol/") || pathname === "/association" || pathname === "/cases" || pathname.startsWith("/cases/");
  return <div className="shell">
    <a href="#main" className="skip-link">跳至主要內容</a>
    <aside className={open ? "sidebar open" : "sidebar"} aria-label="主要導覽">
      <div className="brand"><div className="brand-mark"><ChartNoAxesCombined size={18}/></div><div><strong>SENTINEL</strong><span>Fraud Intelligence</span></div></div>
      <button className="mobile-close icon-button" onClick={() => setOpen(false)} aria-label="關閉選單"><X size={20}/></button>
      <div className="workspace"><span>作業空間</span><strong>SEA Commerce</strong></div>
      <nav>{nav.map(([label, href, Icon]) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return <Link key={href} href={href} onClick={() => setOpen(false)} className={active ? "active" : ""} aria-current={active ? "page" : undefined}><Icon size={18}/><span>{label}</span>{mode === "demo" && label === "案件" && <small>12</small>}</Link>;
      })}</nav>
      <div className="sidebar-foot"><span className="health-dot"/> {mode === "demo" ? "Demo 服務狀態" : "Live 資料模式"} <span>{mode === "demo" ? "12 / 12" : "API"}</span></div>
    </aside>
    {open && <button className="scrim" onClick={() => setOpen(false)} aria-label="關閉選單"/>}
    <div className="main-column">
      <header className="topbar">
        <button className="mobile-menu icon-button" onClick={() => setOpen(true)} aria-label="開啟選單"><Menu size={20}/></button>
        <div className="search"><Search size={17}/><input aria-label="搜尋案件、帳號或政策" placeholder="搜尋案件、帳號或政策"/><kbd>⌘ K</kbd></div>
        <div className="top-actions"><span className={`environment ${mode}`} title={mode === "demo" ? "固定展示資料，不代表目前系統狀態" : "只顯示已接入後端的即時資料"}><span/>{mode === "demo" ? "DEMO DATA" : "LIVE"}</span><button className="icon-button" aria-label="通知"><Bell size={19}/><i/></button><button className="avatar" aria-label="開啟使用者選單">YL</button></div>
      </header>
      <main id="main">{mode === "live" && !hasLiveReadModel ? <section className="live-source-boundary panel"><DatabaseZap size={28}/><span>LIVE DATA BOUNDARY</span><h1>這個頁面的後端資料源尚未接入</h1><p>Live 版不會以 Demo 資料補值。請切到 3002 查看完整展示內容；此頁會在對應的 read API 完成後開放。</p><code>{pathname}</code></section> : children}{pathname === "/evolution" && <section id="defense-versions" className="evolution-defense-section"><DefenseContent/></section>}</main>
    </div>
  </div>;
}
