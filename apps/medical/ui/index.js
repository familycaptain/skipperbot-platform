// UI manifest for the medical app. Auto-discovered by
// web/src/apps/registry.js via import.meta.glob at build time.
import { lazy } from "react";
import { HeartPulse } from "lucide-react";

export default [
  { id: "medical", name: "Medical", icon: HeartPulse, component: lazy(() => import("./MedicalApp")), singleton: true, heroes: { medications: "Your household's private medical record — medications, treatments, events, lab results, and equipment, all in one place. Start by adding a medication." } },
];
