// UI manifest for the Weather app. Auto-discovered by
// web/src/apps/registry.js via import.meta.glob at build time.
import { lazy } from "react";
import { CloudSun } from "lucide-react";

export default [
  {
    id: "weather",
    name: "Weather",
    icon: CloudSun,
    component: lazy(() => import("./WeatherApp")),
    singleton: true,
    page: 1,
    // Tabs reported to open_app so the agent can deep-link (e.g. "show me the radar").
    tabs: ["current", "forecast", "radar"],
  },
];
