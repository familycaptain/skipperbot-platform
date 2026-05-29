// =============================================================================
// Behaviors app — UI registrations
// =============================================================================
// The platform's Vite build discovers each apps/<id>/ui/index.js via
// import.meta.glob and merges the exported registrations into the runtime
// launcher.

import { lazy } from "react";
import { Zap } from "lucide-react";

export default [
  {
    id: "behaviors",
    name: "Behaviors",
    icon: Zap,
    component: lazy(() => import("./BehaviorsApp")),
    singleton: true,
    page: 2,
  },
];
