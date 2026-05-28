import React from "react";
import { Construction } from "lucide-react";

const APP_INFO = {
  home: {
    name: "Home",
    description: "Home automation — control lights, thermostats, cameras, and more.",
    color: "amber",
  },
  recipes: {
    name: "Recipes",
    description: "Your recipe collection — save, organize, and discover meals.",
    color: "rose",
  },
  finder: {
    name: "Finder",
    description: "Home inventory — track where everything is. \"The masking tape is in the office, left shelf drawer.\"",
    color: "sky",
  },
  shopping: {
    name: "Shopping",
    description: "Where we buy things — track preferred stores and suppliers. \"Marinara sauce from Aldi.\"",
    color: "emerald",
  },
  builder: {
    name: "Builder",
    description: "Design and build new apps for Skipper Desktop. Collaborate with Skipper on specifications, test cases, and implementation — from idea to shipped feature.",
    color: "cyan",
  },
  tools: {
    name: "Tools",
    description: "Browse all Skipper tools and guides. View tool definitions, edit behavioral guides, and manage the toolchain.",
    color: "violet",
  },
  maintenance: {
    name: "Home Maintenance",
    description: "Track warranties, maintenance schedules, and service records for household items and systems.",
    color: "amber",
  },
  auto: {
    name: "Auto Maintenance",
    description: "Track vehicle maintenance — oil changes, tire rotations, service history, and upcoming work for all your vehicles.",
    color: "sky",
  },
  homeopathy: {
    name: "Homeopathy",
    description: "Track homeopathic remedy inventory — medicines, remedies, bottle sizes, locations, and bottles with fullness tracking.",
    color: "rose",
  },
  medical: {
    name: "Medical",
    description: "Track doctor appointments, medications, refills, procedures, visits, and health notes for the family.",
    color: "red",
  },
  brainstorming: {
    name: "Brainstorming",
    description: "A creative scratch pad for ideas. Brain dump, explore with Skipper, flesh out concepts, and graduate the best ones into real projects.",
    color: "emerald",
  },
  backups: {
    name: "Backups",
    description: "System and database backups for Skipper — view backup history, check status, and verify that everything is safely stored.",
    color: "cyan",
  },
  prioritize: {
    name: "Prioritize",
    description: "See everything you need to do across all apps — reminders, goals, projects, house and auto tasks — in one view. Make sense of it all and decide where to focus.",
    color: "violet",
  },
  lists: {
    name: "Lists",
    description: "General-purpose lists for anything — packing lists, to-dos, wishlists, checklists, you name it. Each list has its own purpose and can optionally sync with Trello.",
    color: "sky",
  },
  email: {
    name: "Email",
    description: "Email rules and inbox automation — connect to Gmail, set up filters, and let Skipper auto-process your inbox.",
    color: "rose",
  },
  calendar: {
    name: "Calendar",
    description: "Everything scheduled across all apps in one view — reminders, home and auto maintenance, medical appointments, and more.",
    color: "violet",
  },
  schedules: {
    name: "Schedules",
    description: "Repeating schedules for anything — chores, home and auto maintenance, school pickups, recurring tasks. Tracks completion, supports time-based and usage-based recurrence, and feeds into the Calendar.",
    color: "cyan",
  },
  timeline: {
    name: "Timeline",
    description: "Family journal and microblog — post updates, share photos, tag events, and scroll back through time. Like Mastodon for the family.",
    color: "violet",
  },
};

const COLORS = {
  amber:   { bg: "bg-amber-500/10",   border: "border-amber-500/30",   text: "text-amber-400",   icon: "text-amber-500"   },
  rose:    { bg: "bg-rose-500/10",     border: "border-rose-500/30",    text: "text-rose-400",    icon: "text-rose-500"    },
  sky:     { bg: "bg-sky-500/10",      border: "border-sky-500/30",     text: "text-sky-400",     icon: "text-sky-500"     },
  violet:  { bg: "bg-violet-500/10",   border: "border-violet-500/30",  text: "text-violet-400",  icon: "text-violet-500"  },
  emerald: { bg: "bg-emerald-500/10",  border: "border-emerald-500/30", text: "text-emerald-400", icon: "text-emerald-500" },
  cyan:    { bg: "bg-cyan-500/10",     border: "border-cyan-500/30",    text: "text-cyan-400",    icon: "text-cyan-500"    },
};

export default function PlaceholderApp({ appId }) {
  const appType = appId?.split("-")[0] || "home";
  const info = APP_INFO[appType] || APP_INFO.home;
  const c = COLORS[info.color] || COLORS.amber;

  return (
    <div className="flex items-center justify-center h-full p-8">
      <div className={`${c.bg} ${c.border} border rounded-2xl p-10 max-w-md text-center space-y-4`}>
        <Construction size={48} className={`${c.icon} mx-auto`} />
        <h2 className={`text-xl font-bold ${c.text}`}>{info.name}</h2>
        <p className="text-sm text-gray-400 leading-relaxed">{info.description}</p>
        <div className="pt-2">
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-gray-700/50 text-gray-400 border border-gray-600/50">
            <Construction size={12} />
            Coming Soon
          </span>
        </div>
      </div>
    </div>
  );
}
