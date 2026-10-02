/** @type {import('next').NextConfig} */
export default {
  reactStrictMode: true,
  // Hostnames `next dev` may serve /_next/* to besides localhost, e.g. a tunnel
  // for the phone. Comma-separated in .env.local: DEV_ORIGINS=edge-monitor.example.com
  allowedDevOrigins: (process.env.DEV_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean),
};
