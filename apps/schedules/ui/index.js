// =============================================================================
// Schedules app — UI registrations
// =============================================================================
// The platform's Vite build discovers each apps/<id>/ui/index.js via
// import.meta.glob and merges the exported registrations into the runtime
// launcher.

import { lazy } from "react";
import { CalendarClock } from "lucide-react";

export default [
  {
    id: "schedules",
    name: "Schedules",
    icon: CalendarClock,
    component: lazy(() => import("./SchedulesApp")),
    singleton: true,
    page: 2,
  },
];
