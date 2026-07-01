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
    blurb: "A space to capture ideas and shape them into something you can act on. Jot down your first idea.",
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
