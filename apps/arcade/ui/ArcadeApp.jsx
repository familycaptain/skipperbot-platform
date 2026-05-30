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
import { Gamepad2, Castle, Globe2, Rocket, Trophy, Loader2, ArrowLeft } from "lucide-react";

const API = "/api/apps/arcade";

const Wardenfall = lazy(() => import("./games/Wardenfall"));
const Aeldrift = lazy(() => import("./games/Aeldrift"));
const Spinhazard = lazy(() => import("./games/Spinhazard"));

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
    accent: "from-sky-500/20 to-indigo-500/10 border-sky-700/40",
    iconColor: "text-sky-400",
    Comp: Aeldrift,
  },
  {
    id: "spinhazard",
    name: "Spinhazard",
    tagline: "Old-school vector shooter",
    blurb: "One ship, a field of tumbling rocks, wrap-around space. Shoot, thrust, survive. Vector arcade the old way.",
    icon: Rocket,
    accent: "from-emerald-500/20 to-teal-500/10 border-emerald-700/40",
    iconColor: "text-emerald-400",
    Comp: Spinhazard,
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
    <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-4">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-amber-300 mb-3">
        <Trophy size={15} /> Top runs
      </h3>
      {scores === null ? (
        <div className="text-slate-500 text-sm flex items-center gap-2"><Loader2 size={13} className="animate-spin" /> loading…</div>
      ) : scores.length === 0 ? (
        <div className="text-slate-500 text-sm">No scores yet — be the first.</div>
      ) : (
        <ol className="space-y-1.5">
          {scores.map((s, i) => (
            <li key={s.id} className="flex items-center justify-between text-sm">
              <span className="text-slate-400"><span className="text-slate-600 mr-2">{i + 1}.</span>{s.player || "anonymous"}</span>
              <span className="text-slate-300 font-mono">{s.score}<span className="text-slate-600 text-xs ml-1.5">{s.game}</span></span>
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
      <div className="flex flex-col h-full w-full bg-slate-950">
        <div className="flex items-center gap-2 h-9 px-3 border-b border-slate-800 shrink-0">
          <button onClick={() => setActive(null)} className="flex items-center gap-1 text-xs text-slate-400 hover:text-white">
            <ArrowLeft size={13} /> Arcade
          </button>
          <span className="text-xs text-slate-600">/</span>
          <span className="text-xs text-slate-300">{game.name}</span>
        </div>
        <div className="flex-1 min-h-0 relative">
          <Suspense fallback={<div className="absolute inset-0 grid place-items-center text-slate-500"><Loader2 className="animate-spin" /></div>}>
            <G userId={userId} onGameOver={(s) => submitScore(game.id, s)} onExit={() => setActive(null)} />
          </Suspense>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full w-full overflow-y-auto bg-slate-950 p-6">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center gap-2.5 mb-1">
          <Gamepad2 className="text-indigo-400" size={22} />
          <h1 className="text-xl font-bold text-slate-100">Arcade</h1>
        </div>
        <p className="text-sm text-slate-500 mb-6">Three original games, one leaderboard. Pick your poison.</p>

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
                <div className="text-slate-100 font-semibold">{g.name}</div>
                <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-2">{g.tagline}</div>
                <div className="text-xs text-slate-400 leading-relaxed">{g.blurb}</div>
              </button>
            );
          })}
        </div>

        <Leaderboard refreshKey={refreshKey} />
      </div>
    </div>
  );
}
