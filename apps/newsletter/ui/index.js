// UI manifest for the newsletter app. Auto-discovered by
// web/src/apps/registry.js via import.meta.glob at build time.
import { lazy } from "react";
import { Rss } from "lucide-react";

export default [
  { id: "newsletter", name: "Newsletter", icon: Rss, component: lazy(() => import("./NewsletterApp")), singleton: true, page: 2 },
];
