// UI manifest for the Brainstorming app.
// Discovered by web/src/apps/registry.js via import.meta.glob at build time.
// Each entry is auto-tagged with `appPackage: true` by the registry.
import { lazy } from "react";
import { Lightbulb } from "lucide-react";

export default [
  {
    id: "brainstorming",
    name: "Brainstorming",
    icon: Lightbulb,
    component: lazy(() => import("./BrainstormListApp")),
    singleton: true,
    page: 2,
  },
  {
    id: "brainstorm",
    name: "Idea",
    icon: Lightbulb,
    component: lazy(() => import("./BrainstormDetailApp")),
    singleton: false,
    subview: true,
  },
];
