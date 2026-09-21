import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,

  // The site renders counts and nothing else. No images are served, no user
  // content is embedded, and no third-party script is loaded, so the policy
  // can be this tight.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), interest-cohort=()",
          },
        ],
      },
    ];
  },
};

export default config;
