"use client";

import { useDashboardMode } from "@/lib/dashboard-mode";

export function AssociationPageContent({ demo, live }: { demo: React.ReactNode; live: React.ReactNode }) {
  const mode = useDashboardMode();
  return <><div className="page-head"><div><div className="breadcrumb">Intelligence / Entity Graph</div><h1>關聯分析</h1><p>{mode === "demo" ? "檢視展示用的實體、證據與案件關聯。" : "Association service 回傳的實際 jobs、實體與證據。"}</p></div></div>{mode === "demo" ? demo : live}</>;
}
