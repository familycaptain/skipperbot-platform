// UI manifest for the auto app. Auto-discovered by
// web/src/apps/registry.js via import.meta.glob at build time.
import { lazy } from "react";
import { Car } from "lucide-react";

export default [
  { id: "auto", name: "Auto", icon: Car, component: lazy(() => import("./AutoListApp")), singleton: true },
  { id: "auto-vehicle", name: "Vehicle", icon: Car, component: lazy(() => import("./AutoDetailApp")), singleton: false, subview: true },
];
