// UI manifest for the home app. Auto-discovered by
// web/src/apps/registry.js via import.meta.glob at build time.
import { lazy } from "react";
import { Home } from "lucide-react";

export default [
  { id: "home", name: "Home", icon: Home, component: lazy(() => import("./HomeApp")), singleton: true, heroes: { maintenance: "Stay on top of home upkeep — recurring and one-off maintenance. Add a task to get started.", appliances: "Track your household appliances — brand, model, serial, purchase and warranty. Add an appliance to get started.", insurance: "Track your insurance policies — provider, coverage, premium and renewal dates. Add a policy to get started." } },
];
