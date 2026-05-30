// UI manifest for the email app. Auto-discovered by
// web/src/apps/registry.js via import.meta.glob at build time.
import { lazy } from "react";
import { Mail } from "lucide-react";

export default [
  { id: "email", name: "Email", icon: Mail, component: lazy(() => import("./EmailApp")), singleton: true, page: 2 },
];
