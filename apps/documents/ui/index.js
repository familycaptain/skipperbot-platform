// =============================================================================
// Documents app — UI registrations
// =============================================================================
// The platform's Vite build discovers each apps/<id>/ui/index.js via
// import.meta.glob and merges the exported registrations into the runtime
// launcher.

import { lazy } from "react";
import { FileText } from "lucide-react";

export default [
  // Main listing app — shown in the launcher.
  {
    id: "documents",
    name: "Documents",
    icon: FileText,
    component: lazy(() => import("./DocListApp")),
    singleton: true,
    page: 3,
  },
  // Singleton editor — hidden from the launcher (LAUNCHER_HIDDEN
  // continues to suppress it), opened from the listing app or by ID.
  {
    id: "document",
    name: "Document",
    icon: FileText,
    component: lazy(() => import("./DocumentEditor")),
    singleton: false,
    subview: true,
  },
];
