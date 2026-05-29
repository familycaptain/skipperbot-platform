// =============================================================================
// System app — UI registrations
// =============================================================================
// The platform's Vite build discovers each apps/<id>/ui/index.js via
// import.meta.glob and merges the exported registrations into the runtime
// launcher.

import { lazy } from "react";
import { Server } from "lucide-react";

export default [
  {
    id: "system",
    name: "System",
    icon: Server,
    component: lazy(() => import("./SystemApp")),
    singleton: true,
    page: 3,
  },
];
