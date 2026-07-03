// =============================================================================
// Empty-state hero registry + predicate (platform.app-ui.empty-state-hero)
// =============================================================================
// The EXPLICIT, exhaustive opt-in/exclude decision for the record-based
// empty-state hero, keyed by PRIMARY (non-subview) registry ENTRY id.
//
// This module is intentionally PURE (no react/lucide imports) so the web
// prebuild guardrail (web/scripts/check-empty-state-hero.mjs) can import it
// directly from Node and assert the registry + predicate. App ui/index.js
// files (which import react/lucide) are static-parsed instead.
//
// Placement descriptor per OPT_IN entry:
//   { mode: "default" }              — one hero on the default view when the
//                                      primary collection is pristine-empty.
//   { mode: "page" }                 — one hero for the whole page under a
//                                      compound condition (todo: no active todo
//                                      AND no active backlog cards).
//   { mode: "per-view", views: [] }  — one hero per named tab/view, fired when
//                                      THAT view's slice is pristine-empty. The
//                                      views[] are the component's REAL tab ids
//                                      (lowercase) and are the single source of
//                                      truth the guardrail derives the required
//                                      heroes-map keys from.
//
// The blurb copy itself lives on each opt-in app's ui/index.js entry (a single
// `blurb` for default/page, or a `heroes` map keyed by view id for per-view) —
// zero registry.js change. See the guardrail for enforcement.

/**
 * True exactly when a slice is PRISTINE-empty: not loading, no records, and no
 * active filter scoping that slice. `records: null` counts as empty. A zero-
 * result search or an out-of-scope date/time view sets filterActive, so it
 * shows the app's normal text — never the onboarding hero.
 *
 * @param {{records: any[]|null|undefined, loading: boolean, filterActive: boolean}} args
 * @returns {boolean}
 */
export function isPristineEmpty({ records, loading, filterActive }) {
  return !loading && (records?.length || 0) === 0 && !filterActive;
}

// Keyed by PRIMARY entry id. Order mirrors the spec (default-view apps first,
// then the per-view / page apps). EXHAUSTIVE + DISJOINT with EXCLUDE over all
// primary (non-subview) entry ids in apps/*/ui/index.js.
export const OPT_IN = {
  auto: { mode: "default" },
  goals: { mode: "default" },
  tasks: { mode: "default" },
  chores: { mode: "default" },
  brainstorming: { mode: "default" },
  documents: { mode: "default" },
  folders: { mode: "default" },
  images: { mode: "default" },
  lists: { mode: "default" },
  locator: { mode: "default" },
  recipes: { mode: "default" },
  timeline: { mode: "default" },
  bounties: { mode: "default" },
  schedules: { mode: "default" },
  jobs: { mode: "default" },
  todo: { mode: "page" },
  reminders: { mode: "per-view", views: ["reminders", "nags"] },
  meals: { mode: "per-view", views: ["browse"] },
  medical: { mode: "per-view", views: ["medications"] },
  home: { mode: "per-view", views: ["maintenance"] },
};

// Keyed by PRIMARY entry id -> reason. Every excluded primary entry (issues,
// chores, prioritize, and every system/tool app) is listed with why it carries
// no hero.
export const EXCLUDE = {
  issues: "operator removed it from scope — no hero (the issues feature may be retired)",
  prioritize: "a focusing tool over OTHER apps' items, not its own record collection",
  behaviors: "LLM behavior config, not user content",
  automation: "Home-Assistant device/alias config, not user records",
  email: "mail client/integration; inbox isn't a created-record collection",
  arcade: "leaderboard/scores ('be the first'), not user records",
  finder: "global search tool",
  calculators: "tool, no records",
  weather: "widget, no records",
  backups: "system snapshots, not user-created",
  notifications: "system-generated, no +New",
  thinking: "reasoning/state log",
  settings: "config",
  system: "system",
  tools: "tool registry",
};
