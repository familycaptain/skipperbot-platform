// =============================================================================
// Backups app — UI registrations
// =============================================================================
// The platform's Vite build discovers each apps/<id>/ui/index.js via
// import.meta.glob and merges the exported registrations into the runtime
// launcher.

import { lazy } from "react";
import { HardDrive } from "lucide-react";

export default [
  {
    id: "backups",
    name: "Backups",
    icon: HardDrive,
    component: lazy(() => import("./BackupsApp")),
    singleton: true,
    page: 3,
  },
];
