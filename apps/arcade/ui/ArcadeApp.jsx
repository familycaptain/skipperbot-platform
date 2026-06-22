// =============================================================================
// Arcade — game hub
// =============================================================================
// A menu that launches one of three original, self-contained games and a
// shared high-score board. Each game is a lazy-loaded component with the
// interface:
//     export default function Game({ userId, onGameOver, onExit })
//   - onGameOver(score:number)  — report a final score (persisted)
//   - onExit()                  — return to the menu
//
import { useState, useEffect, useCallback, Suspense, lazy } from "react";
import { Gamepad2, Castle, Globe2, Rocket, Spade, Trophy, Loader2, ArrowLeft, Volume2, VolumeX } from "lucide-react";
import { isMuted, toggleMuted, onMuteChange } from "./sfx";

// Shared mute toggle — reflects + flips the arcade-wide (localStorage-backed)
// sound preference, kept in sync across games via onMuteChange.
function MuteButton({ className = "" }) {
  const [muted, setMutedState] = useState(isMuted());
  useEffect(() => onMuteChange(setMutedState), []);
  return (
    <button
      onClick={() => setMutedState(toggleMuted())}
      title={muted ? "Sound off — click to unmute" : "Sound on — click to mute"}
      className={`text-muted hover:text-[var(--ds-text)] transition-colors ${className}`}
    >
      {muted ? <VolumeX size={15} /> : <Volume2 size={15} />}
    </button>
  );
}

const API = "/api/apps/arcade";

const Wardenfall = lazy(() => import("./games/Wardenfall"));
const Aeldrift = lazy(() => import("./games/Aeldrift"));
const Spinhazard = lazy(() => import("./games/Spinhazard"));
const Solitaire = lazy(() => import("./games/Solitaire"));

const GAMES = [
  {
    id: "wardenfall",
    name: "Wardenfall",
    tagline: "Top-down tower defense",
    blurb: "Hold the mountain pass. Place wardens, channel mana, and break the endless tide before it reaches the keep.",
    icon: Castle,
    accent: "from-amber-500/20 to-rose-500/10 border-amber-700/40",
    iconColor: "text-amber-400",
    Comp: Wardenfall,
  },
  {
    id: "aeldrift",
    name: "Aeldrift",
    tagline: "3D world exploration",
    blurb: "Drift across a low-poly archipelago and gather the scattered light-shards. Pure WebGL, no enemies — just wander.",
    icon: Globe2,
    accent: "from-[var(--ds-accent)] to-indigo-500/10 border-subtle",
    iconColor: "text-accent",
    Comp: Aeldrift,
  },
  {
    id: "spinhazard",
    name: "Spinhazard",
    tagline: "Old-school vector shooter",
    blurb: "One ship, a field of tumbling rocks, wrap-around space. Shoot, thrust, survive. Vector arcade the old way.",
    icon: Rocket,
    accent: "from-emerald-500/20 to-[var(--ds-accent)] border-emerald-700/40",
    iconColor: "text-emerald-400",
    Comp: Spinhazard,
  },
  {
    id: "solitaire",
    name: "Solitaire",
    tagline: "Klondike patience",
    blurb: "The classic. Draw three, build the foundations ace-to-king, and clear the board. Your game saves automatically — leave and come back any time.",
    icon: Spade,
    accent: "from-[var(--ds-raised)] to-emerald-500/10 border-subtle",
    iconColor: "text-default",
    Comp: Solitaire,
  },
];

function Leaderboard({ refreshKey }) {
  const [scores, setScores] = useState(null);
  useEffect(() => {
    let dead = false;
    (async () => {
      try {
        const res = await fetch(`${API}/scores?limit=10`);
        const data = res.ok ? await res.json() : { scores: [] };
        if (!dead) setScores(data.scores || []);
      } catch { if (!dead) setScores([]); }
    })();
    return () => { dead = true; };
  }, [refreshKey]);

  return (
    <div className="rounded-xl border border-subtle surface-panel p-4">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-amber-300 mb-3">
        <Trophy size={15} /> Top runs
      </h3>
      {scores === null ? (
        <div className="text-faint text-sm flex items-center gap-2"><Loader2 size={13} className="animate-spin" /> loading…</div>
      ) : scores.length === 0 ? (
        <div className="text-faint text-sm">No scores yet — be the first.</div>
      ) : (
        <ol className="space-y-1.5">
          {scores.map((s, i) => (
            <li key={s.id} className="flex items-center justify-between text-sm">
              <span className="text-muted"><span className="text-faint mr-2">{i + 1}.</span>{s.player || "anonymous"}</span>
              <span className="text-default font-mono">{s.score}<span className="text-faint text-xs ml-1.5">{s.game}</span></span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export default function ArcadeApp({ userId }) {
  const [active, setActive] = useState(null); // game id or null (menu)
  const [refreshKey, setRefreshKey] = useState(0);

  const submitScore = useCallback(async (game, score) => {
    try {
      await fetch(`${API}/scores`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ game, player: userId || "", score: Math.round(score) || 0 }),
      });
    } catch { /* ignore — playing offline still works */ }
    setRefreshKey((k) => k + 1);
  }, [userId]);

  const game = GAMES.find((g) => g.id === active);

  if (game) {
    const G = game.Comp;
    return (
      <div className="flex flex-col h-full w-full surface-page">
        <div className="flex items-center gap-2 h-9 px-3 border-b border-subtle shrink-0">
          <button onClick={() => setActive(null)} className="flex items-center gap-1 text-xs text-muted hover:text-[var(--ds-text)]">
            <ArrowLeft size={13} /> Arcade
          </button>
          <span className="text-xs text-faint">/</span>
          <span className="text-xs text-default">{game.name}</span>
          <MuteButton className="ml-auto" />
        </div>
        <div className="flex-1 min-h-0 relative">
          <Suspense fallback={<div className="absolute inset-0 grid place-items-center text-faint"><Loader2 className="animate-spin" /></div>}>
            <G userId={userId} onGameOver={(s) => submitScore(game.id, s)} onExit={() => setActive(null)} />
          </Suspense>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full w-full overflow-y-auto surface-page p-6">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center gap-2.5 mb-1">
          <Gamepad2 className="text-indigo-400" size={22} />
          <h1 className="text-xl font-bold text-default">Arcade</h1>
          <MuteButton className="ml-auto" />
        </div>
        <p className="text-sm text-faint mb-6">Four games, one leaderboard. Pick your poison.</p>

        <div className="grid md:grid-cols-3 gap-3 mb-6">
          {GAMES.map((g) => {
            const Icon = g.icon;
            return (
              <button
                key={g.id}
                onClick={() => setActive(g.id)}
                className={`text-left rounded-xl border bg-gradient-to-br ${g.accent} p-4 hover:scale-[1.02] transition-transform`}
              >
                <Icon className={`${g.iconColor} mb-2`} size={26} />
                <div className="text-default font-semibold">{g.name}</div>
                <div className="text-[11px] uppercase tracking-wide text-faint mb-2">{g.tagline}</div>
                <div className="text-xs text-muted leading-relaxed">{g.blurb}</div>
              </button>
            );
          })}
        </div>

        <Leaderboard refreshKey={refreshKey} />
      </div>
    </div>
  );
}
