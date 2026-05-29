// =============================================================================
// Folders app — UI registrations
// =============================================================================
// The platform's Vite build discovers each apps/<id>/ui/index.js via
// import.meta.glob and merges the exported registrations into the runtime
// launcher.

import { lazy } from "react";
import { FolderOpen } from "lucide-react";

export default [
  // Top-level folder tree app — shown in the launcher (page 2 / tools).
  {
    id: "folders",
    name: "Folders",
    icon: FolderOpen,
    component: lazy(() => import("./FoldersApp")),
    singleton: true,
    page: 2,
  },
  // Detail / editor — hidden from the launcher (the platform's
  // LAUNCHER_HIDDEN set already excludes id="folder"), opened from
  // the tree app or by ID.
  {
    id: "folder",
    name: "Folder",
    icon: FolderOpen,
    component: lazy(() => import("./FolderDetailApp")),
    singleton: false,
  },
];
