// =============================================================================
// Timeline app — UI registrations
// =============================================================================
// The platform's Vite build discovers each apps/<id>/ui/index.js via
// import.meta.glob and merges the exported registrations into the runtime
// launcher.

import { lazy } from "react";
import { Newspaper } from "lucide-react";

export default [
  {
    id: "timeline",
    name: "Timeline",
    icon: Newspaper,
    component: lazy(() => import("./TimelineApp")),
    singleton: true,
    blurb: "A shared feed of your household's moments and updates. Post the first one to start the story.",
  },
];
