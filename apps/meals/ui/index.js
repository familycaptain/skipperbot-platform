// UI manifest for the meals app. Auto-discovered by
// web/src/apps/registry.js via import.meta.glob at build time.
import { lazy } from "react";
import { ChefHat } from "lucide-react";

export default [
  { id: "meals", name: "Meals", icon: ChefHat, component: lazy(() => import("./MealsApp")), singleton: true, heroes: { browse: "Collect meal ideas from meals you've had before, so there's always something to come back to. Add your first meal idea." } },
];
