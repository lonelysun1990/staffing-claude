import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const allowedHost = process.env.ALLOWED_HOST;
  const allowedHosts = allowedHost ? [allowedHost] : [];
  return {
    plugins: [react()],
    server: {
      host: "0.0.0.0",
      port: 5173,
    },
    preview: {
      host: "0.0.0.0",
      port: parseInt(process.env.PORT || "4173"),
      allowedHosts,
    },
  };
});

