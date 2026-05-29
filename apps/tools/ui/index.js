// =============================================================================
// Tools app — UI registrations
// =============================================================================
// The platform's Vite build discovers each apps/<id>/ui/index.js via
// import.meta.glob and merges the exported registrations into the runtime
// launcher.

import { lazy } from "react";
import { Wrench } from "lucide-react";

export default [
  {
    id: "tools",
    name: "Tools",
    icon: Wrench,
    component: lazy(() => import("./ToolsApp")),
    singleton: true,
    page: 3,
  },
];
