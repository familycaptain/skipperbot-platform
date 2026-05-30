// UI manifest for the automation app. Auto-discovered by
// web/src/apps/registry.js via import.meta.glob at build time.
import { lazy } from "react";
import { Lightbulb } from "lucide-react";

export default [
  { id: "automation", name: "Automation", icon: Lightbulb, component: lazy(() => import("./AutomationApp")), singleton: true },
];
