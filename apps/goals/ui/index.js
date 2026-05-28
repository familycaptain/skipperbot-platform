// =============================================================================
// Goals app — UI registrations
// =============================================================================
// The platform's Vite build discovers each apps/<id>/ui/index.js via
// import.meta.glob and merges the exported registrations into the runtime
// launcher.
//
// Sub-chunk 3a: scaffold only. Real JSX lands in sub-chunk 3f when
// GoalsApp.jsx + TasksApp.jsx move here from web/src/apps/.

import { lazy } from "react";
import { Target, CheckSquare } from "lucide-react";

export default [
  {
    id: "goals",
    name: "Goals",
    icon: Target,
    component: lazy(() => import("./GoalsApp")),
    singleton: true,
  },
  {
    id: "tasks",
    name: "Tasks",
    icon: CheckSquare,
    component: lazy(() => import("./TasksApp")),
    singleton: true,
  },
];
