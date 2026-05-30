// UI manifest for the locator app. Auto-discovered by
// web/src/apps/registry.js via import.meta.glob at build time.
import { lazy } from "react";
import { MapPin } from "lucide-react";

export default [
  { id: "locator", name: "Locator", icon: MapPin, component: lazy(() => import("./LocatorListApp")), singleton: true },
  { id: "locator-item", name: "Item", icon: MapPin, component: lazy(() => import("./LocatorDetailApp")), singleton: false, hidden: true },
];
