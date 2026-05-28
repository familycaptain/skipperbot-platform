// =============================================================================
// Notifications app — UI registrations
// =============================================================================
// The platform's Vite build discovers each apps/<id>/ui/index.js via
// import.meta.glob and merges the exported registrations into the runtime
// launcher.

import { lazy } from "react";
import { Mail } from "lucide-react";

export default [
  {
    id: "notifications",
    name: "Notifications",
    icon: Mail,
    component: lazy(() => import("./NotificationsApp")),
    singleton: true,
    page: 3,
  },
];
