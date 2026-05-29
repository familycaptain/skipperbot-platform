// =============================================================================
// Prioritize app — UI registrations
// =============================================================================
// The platform's Vite build discovers each apps/<id>/ui/index.js via
// import.meta.glob and merges the exported registrations into the runtime
// launcher.

import { lazy } from "react";
import { ListChecks } from "lucide-react";

export default [
  {
    id: "prioritize",
    name: "Prioritize",
    icon: ListChecks,
    component: lazy(() => import("./PrioritizeApp")),
    singleton: true,
  },
];
