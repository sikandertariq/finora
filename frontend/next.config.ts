import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Django REST Framework endpoints use trailing slashes. Preserve them at
  // Vercel's edge so Next.js and Django do not redirect back and forth.
  skipTrailingSlashRedirect: true,
  async rewrites() {
    const backendOrigin = process.env.BACKEND_ORIGIN?.replace(/\/$/, "");
    if (!backendOrigin) return [];
    return [
      {
        source: "/api/:path*",
        destination: `${backendOrigin}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
