import { cloudflare } from "@cloudflare/vite-plugin";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

declare const process: { env: Record<string, string | undefined> };

export default defineConfig(({ mode }) => {
  if (mode === "production") {
    // The domain is the primary game surface. The Discord Activity SDK is
    // opt-in only for old installations during migration.
    process.env.VITE_ENABLE_DISCORD_SDK ??= "false";
    process.env.VITE_ENABLE_LIVE_ENVIRONMENT ??= "true";
    process.env.VITE_DEFAULT_ENVIRONMENT ??= "live";
    process.env.VITE_ENABLE_LIVE_CHAT ??= "false";
  }
  return {
    plugins: [react(), cloudflare()],
    server: {
      host: "127.0.0.1",
      port: 5173,
    },
  };
});
