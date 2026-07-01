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
    blurb: "Turn what you want to get done into trackable goals. Add your first goal and Skipper helps you break it down and make progress.",
  },
  {
    id: "tasks",
    name: "Tasks",
    icon: CheckSquare,
    component: lazy(() => import("./TasksApp")),
    singleton: true,
    blurb: "A focused view of the individual tasks across your goals and projects that are assigned to you. Add a task to a goal or project and it shows up here.",
  },
];
