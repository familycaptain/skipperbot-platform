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
    heroes: {
      reminders: "One-off and recurring reminders so nothing slips. Add a reminder and Skipper nudges you at the right time.",
      nags: "Nags are persistent reminders that keep after you until the thing is actually done — for the stuff that's easy to ignore. Set a nag and Skipper won't let it drop.",
    },
  },
];
