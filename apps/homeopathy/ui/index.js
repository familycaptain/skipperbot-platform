// UI manifest for the homeopathy app. Auto-discovered by
// web/src/apps/registry.js via import.meta.glob at build time.
import { lazy } from "react";
import { FlaskConical } from "lucide-react";

export default [
  { id: "homeopathy", name: "Homeopathy", icon: FlaskConical, component: lazy(() => import("./HomeopathyApp")), singleton: true },
];
