// UI manifest for the bounties app. Auto-discovered by
// web/src/apps/registry.js via import.meta.glob at build time.
import { lazy } from "react";
import { Coins } from "lucide-react";

export default [
  { id: "bounties", name: "Bounties", icon: Coins, component: lazy(() => import("./BountiesApp")), singleton: true, blurb: "Set rewards for things you want done around the house. Create a bounty to motivate the crew." },
];
