import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Live and Demo can run concurrently without sharing development artifacts.
  distDir: process.env.DASHBOARD_DATA_MODE === "demo" ? ".next-demo" : ".next",
};

export default nextConfig;
