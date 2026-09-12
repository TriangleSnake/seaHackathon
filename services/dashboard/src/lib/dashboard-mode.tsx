"use client";

import { createContext, useContext } from "react";

export type DashboardMode = "demo" | "live";

const DashboardModeContext = createContext<DashboardMode>("live");

export function DashboardModeProvider({ mode, children }: { mode: DashboardMode; children: React.ReactNode }) {
  return <DashboardModeContext.Provider value={mode}>{children}</DashboardModeContext.Provider>;
}

export function useDashboardMode() {
  return useContext(DashboardModeContext);
}
