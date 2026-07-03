// UI manifest for the medical app. Auto-discovered by
// web/src/apps/registry.js via import.meta.glob at build time.
import { lazy } from "react";
import { HeartPulse } from "lucide-react";

export default [
  {
    id: "medical", name: "Medical", icon: HeartPulse,
    component: lazy(() => import("./MedicalApp")), singleton: true,
    heroes: {
      medications: "Track your household's medications — names, doses, and schedules. Add a medication to get started.",
      treatments: "Record treatments and procedures for your household. Add a treatment to get started.",
      events: "Log medical events — illnesses, injuries, symptoms. Add an event to get started.",
      labs: "Keep your lab results in one place. Add a lab result to get started.",
      appointments: "Track upcoming and past medical appointments. Add an appointment to get started.",
      equipment: "Track medical equipment and its maintenance. Add a piece of equipment to get started.",
    },
  },
];
