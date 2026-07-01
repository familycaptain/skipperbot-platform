// UI manifest for the Recipes app.
// Discovered by web/src/apps/registry.js via import.meta.glob at build time.
// Each entry is auto-tagged with `appPackage: true` by the registry.
import { lazy } from "react";
import { UtensilsCrossed } from "lucide-react";

export default [
  {
    id: "recipes",
    name: "Recipes",
    icon: UtensilsCrossed,
    component: lazy(() => import("./RecipeListApp")),
    singleton: true,
    blurb: "Your personal cookbook — save the recipes you love so they're always at hand. Add your first recipe.",
  },
  {
    id: "recipe",
    name: "Recipe",
    icon: UtensilsCrossed,
    component: lazy(() => import("./RecipeDetailApp")),
    singleton: true,
    subview: true,
  },
];
