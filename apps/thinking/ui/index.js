// UI manifest for the Thinking app.
// Discovered by web/src/apps/registry.js via import.meta.glob at build time.
// Each entry is auto-tagged with `appPackage: true` by the registry.
import { lazy } from "react";
import { Brain } from "lucide-react";

export default [
  {
    id: "thinking",
    name: "Thinking",
    icon: Brain,
    component: lazy(() => import("./ThinkingApp")),
    singleton: true,
    page: 3,
    // Skipper's inner life: the Stream is every message between Skipper and every member,
    // and the domain switches turn areas of background thought on and off. Household adults
    // trust each other, but that does not extend to a kid-role account reading everyone's
    // correspondence — so this tile is admin-only. The server enforces it (403 on
    // /api/apps/thinking/*); this only keeps the tile out of a non-admin's launcher.
    adminOnly: true,
  },
];
