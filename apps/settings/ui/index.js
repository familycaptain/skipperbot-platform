// =============================================================================
// Settings app — UI registrations
// =============================================================================
// The platform's Vite build discovers each apps/<id>/ui/index.js via
// import.meta.glob and merges the exported registrations into the runtime
// launcher.

import { lazy } from "react";
import { Settings } from "lucide-react";

export default [
  {
    id: "settings",
    name: "Settings",
    icon: Settings,
    component: lazy(() => import("./SettingsApp")),
    singleton: true,
    page: 3,
  },
];
