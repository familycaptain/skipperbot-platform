// =============================================================================
// Finder app — UI registrations
// =============================================================================
// The platform's Vite build discovers each apps/<id>/ui/index.js via
// import.meta.glob and merges the exported registrations into the runtime
// launcher.

import { lazy } from "react";
import { Search } from "lucide-react";

export default [
  {
    id: "finder",
    name: "Finder",
    icon: Search,
    component: lazy(() => import("./FinderApp")),
    singleton: true,
  },
];
