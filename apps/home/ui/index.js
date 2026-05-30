// UI manifest for the home app. Auto-discovered by
// web/src/apps/registry.js via import.meta.glob at build time.
import { lazy } from "react";
import { Home, MapPin } from "lucide-react";

export default [
  { id: "home", name: "Home", icon: Home, component: lazy(() => import("./HomeApp")), singleton: true },
  { id: "locator-item", name: "Item", icon: MapPin, component: lazy(() => import("./LocatorDetailApp")), singleton: false, hidden: true },
];
