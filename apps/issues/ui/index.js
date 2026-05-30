// UI manifest for the issues app. Auto-discovered by
// web/src/apps/registry.js via import.meta.glob at build time.
import { lazy } from "react";
import { Bug } from "lucide-react";

export default [
  { id: "issues", name: "Issues", icon: Bug, component: lazy(() => import("./IssuesApp")), singleton: true, page: 3 },
];
