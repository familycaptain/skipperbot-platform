// =============================================================================
// Evolve app — UI registration (discovered by web/src/apps/registry.js at build).
// =============================================================================
import { lazy } from "react";
import { Workflow } from "lucide-react";

export default [
  {
    id: "evolve",
    name: "Evolve",
    icon: Workflow,
    component: lazy(() => import("./EvolveApp")),
    singleton: true,
  },
];
