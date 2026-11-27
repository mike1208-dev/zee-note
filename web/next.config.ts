import type { NextConfig } from "next";

// The browser calls /api on this app, and Next passes it on to the ZeeNote API, so no CORS setup is needed
const API_URL = process.env.ZEENOTE_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // writing a report and checking its AI rules can take a while, more than the 30 seconds Next waits by default
  experimental: { proxyTimeout: 120_000 },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
};

export default nextConfig;
