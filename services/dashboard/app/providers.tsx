"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { DashboardModeProvider, type DashboardMode } from "@/lib/dashboard-mode";

export function Providers({ children, mode }: { children: React.ReactNode; mode: DashboardMode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { staleTime: 30_000 } } }));
  return <DashboardModeProvider mode={mode}><QueryClientProvider client={client}>{children}</QueryClientProvider></DashboardModeProvider>;
}
