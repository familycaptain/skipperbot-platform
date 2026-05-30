// UI manifest for the meals app. Auto-discovered by
// web/src/apps/registry.js via import.meta.glob at build time.
import { lazy } from "react";
import { ChefHat } from "lucide-react";

export default [
  { id: "meals", name: "Meals", icon: ChefHat, component: lazy(() => import("./MealsApp")), singleton: true },
];
