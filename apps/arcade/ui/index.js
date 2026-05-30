// UI manifest for the Arcade app. Auto-discovered by
// web/src/apps/registry.js via import.meta.glob at build time.
import { lazy } from "react";
import { Gamepad2 } from "lucide-react";

export default [
  {
    id: "arcade",
    name: "Arcade",
    icon: Gamepad2,
    component: lazy(() => import("./ArcadeApp")),
    singleton: true,
    page: 2,
  },
];
