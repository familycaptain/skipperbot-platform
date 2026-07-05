// =============================================================================
// Todo app — UI registrations
// =============================================================================
// The platform's Vite build discovers each apps/<id>/ui/index.js via
// import.meta.glob and merges the exported registrations into the runtime
// launcher.

import { lazy } from "react";
import { ListTodo } from "lucide-react";

export default [
  {
    id: "todo",
    name: "To-Do",
    icon: ListTodo,
    component: lazy(() => import("./TodoApp")),
    singleton: true,
    blurb: "Your to-do board — capture what needs doing and move it from backlog to done. Add a card to get started.",
  },
];
