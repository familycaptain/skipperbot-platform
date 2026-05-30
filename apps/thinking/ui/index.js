// UI manifest for the Thinking app.
// Discovered by web/src/apps/registry.js via import.meta.glob at build time.
// Each entry is auto-tagged with `appPackage: true` by the registry.
import { lazy } from "react";
import { Brain } from "lucide-react";

export default [
  {
    id: "thinking",
    name: "Thinking",
    icon: Brain,
    component: lazy(() => import("./ThinkingApp")),
    singleton: true,
    page: 3,
  },
];
