// UI manifest for the Calculators app. Auto-discovered by
// web/src/apps/registry.js via import.meta.glob at build time.
import { lazy } from "react";
import { Calculator } from "lucide-react";

export default [
  {
    id: "calculators",
    name: "Calculators",
    icon: Calculator,
    component: lazy(() => import("./CalculatorsApp")),
    singleton: true,
    page: 2,
  },
];
