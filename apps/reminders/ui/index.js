// =============================================================================
// Reminders app — UI registrations
// =============================================================================
// The platform's Vite build discovers each apps/<id>/ui/index.js via
// import.meta.glob and merges the exported registrations into the runtime
// launcher.

import { lazy } from "react";
import { Bell } from "lucide-react";

export default [
  {
    id: "reminders",
    name: "Reminders",
    icon: Bell,
    component: lazy(() => import("./RemindersApp")),
    singleton: true,
  },
];
