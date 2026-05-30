// UI manifest for the chores app. Auto-discovered by
// web/src/apps/registry.js via import.meta.glob at build time.
import { lazy } from "react";
import { ListChecks } from "lucide-react";

export default [
  { id: "chores", name: "Chores", icon: ListChecks, component: lazy(() => import("./ChoresApp")), singleton: true },
];
