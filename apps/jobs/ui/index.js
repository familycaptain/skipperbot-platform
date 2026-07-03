// =============================================================================
// Jobs app — UI registrations
// =============================================================================
// The platform's Vite build discovers each apps/<id>/ui/index.js via
// import.meta.glob and merges the exported registrations into the runtime
// launcher.

import { lazy } from "react";
import { Briefcase } from "lucide-react";

export default [
  {
    id: "jobs",
    name: "Jobs",
    icon: Briefcase,
    component: lazy(() => import("./JobsApp")),
    singleton: true,
    page: 3,
    blurb: "Background work Skipper runs for you — research, backups, scheduled tasks, and app jobs. Anything you or your apps kick off shows up here to track, retry, or cancel.",
  },
];
