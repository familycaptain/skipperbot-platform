// UI manifest for the medical app. Auto-discovered by
// web/src/apps/registry.js via import.meta.glob at build time.
import { lazy } from "react";
import { HeartPulse } from "lucide-react";

export default [
  { id: "medical", name: "Medical", icon: HeartPulse, component: lazy(() => import("./MedicalApp")), singleton: true },
];
