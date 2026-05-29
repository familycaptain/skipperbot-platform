import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { VitePWA } from "vite-plugin-pwa";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const webNodeModules = path.resolve(__dirname, "node_modules");

// Packaged-app UI files live outside web/ (under apps/<id>/ui/) so Vite's
// resolver can't walk up to find web/node_modules. Alias the deps those
// apps import to absolute paths inside web/node_modules so the resolution
// works from any location in the repo.
// Add a new entry here when a packaged-app UI introduces a new npm dep.
const packagedAppDepAliases = {
  "react": path.join(webNodeModules, "react"),
  "react-dom": path.join(webNodeModules, "react-dom"),
  "lucide-react": path.join(webNodeModules, "lucide-react"),
  "react-markdown": path.join(webNodeModules, "react-markdown"),
  "remark-gfm": path.join(webNodeModules, "remark-gfm"),
};

export default defineConfig({
  resolve: {
    alias: packagedAppDepAliases,
    // Make sure a single copy of react is used across web/ and apps/*/ui/.
    dedupe: Object.keys(packagedAppDepAliases),
  },
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["skipper-192.svg", "skipper-512.svg"],
      workbox: {
        skipWaiting: true,
        clientsClaim: true,
        cleanupOutdatedCaches: true,
        navigateFallbackDenylist: [/^\/api\//, /^\/capture/, /^\/meal-menu/, /^\/anime-player/, /^\/info/, /^\/info-shots\//],
      },
      manifest: {
        name: "SkipperBot",
        short_name: "Skipper",
        description: "AI family assistant",
        theme_color: "#0f172a",
        background_color: "#0f172a",
        display: "standalone",
        scope: "/",
        start_url: "/",
        icons: [
          {
            src: "skipper-192.svg",
            sizes: "192x192",
            type: "image/svg+xml",
          },
          {
            src: "skipper-512.svg",
            sizes: "512x512",
            type: "image/svg+xml",
          },
        ],
      },
    }),
  ],
  server: {
    port: 5173,
    allowedHosts: ["skipper.yourdomain.example"],
    fs: {
      // Allow Vite to serve files from /apps (one level above web/) so
      // packaged-app UI manifests at apps/<id>/ui/index.js are reachable
      // via import.meta.glob("../../../apps/*/ui/index.js") in registry.js.
      allow: [".."],
    },
    proxy: {
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
      "/api": {
        target: "http://localhost:8000",
      },
      "/auth": {
        target: "http://localhost:8000",
      },
      "/uploads": {
        target: "http://localhost:8000",
      },
    },
  },
});
