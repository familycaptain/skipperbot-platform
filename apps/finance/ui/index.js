// UI manifest for the Finance Calculator app. Auto-discovered by
// web/src/apps/registry.js via import.meta.glob at build time.
import { lazy } from "react";
import { Calculator } from "lucide-react";

export default [
  {
    id: "finance",
    name: "Finance Calculator",
    icon: Calculator,
    component: lazy(() => import("./FinanceCalcApp")),
    singleton: true,
    page: 2,
  },
];
