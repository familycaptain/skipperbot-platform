// UI manifest for the Images app.
// Discovered by web/src/apps/registry.js via import.meta.glob at build time.
// Each entry is auto-tagged with `appPackage: true` by the registry.
import { lazy } from "react";
import { Image as ImageIcon } from "lucide-react";

export default [
  {
    id: "images",
    name: "Images",
    icon: ImageIcon,
    component: lazy(() => import("./ImagesApp")),
    singleton: true,
    page: 2,
  },
  {
    id: "image",
    name: "Image",
    icon: ImageIcon,
    component: lazy(() => import("./ImageViewer")),
    singleton: false,
    hidden: true,
  },
];
