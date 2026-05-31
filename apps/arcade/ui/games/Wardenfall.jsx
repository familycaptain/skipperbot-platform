import { useEffect, useRef, useState, useCallback } from "react";
import { Play, RotateCcw, LogOut, Shield, Zap, Flame } from "lucide-react";
import { sfx, resume as resumeAudio } from "../sfx";

/**
 * Wardenfall — a top-down tower-defense game.
 *
 * Entirely self-contained: all rendering via canvas primitives, no assets,
 * no network. Game state lives in refs; React state only drives HUD/overlays.
 *
 * Contract:
 *   onGameOver(score) — called exactly once when lives reach 0.
 *   onExit()          — optional; wired to an in-game "Give up" button.
 */

// ---- Tunables -------------------------------------------------------------
const TILE = 48; // logical grid cell size in world units
const COLS = 16;
const ROWS = 11;
const WORLD_W = COLS * TILE;
const WORLD_H = ROWS * TILE;
const START_GOLD = 120;
const START_LIVES = 12;
const BREAK_MS = 4000; // auto-advance delay between waves

// Winding path expressed as grid waypoints (col,row). Drawn as a track.
const PATH_CELLS = [
  [-1, 1],
  [2, 1],
  [2, 4],
  [6, 4],
  [6, 1],
  [9, 1],
  [9, 7],
  [4, 7],
  [4, 9],
  [12, 9],
  [12, 3],
  [14, 3],
  [14, 6],
  [16, 6], // keep edge (off-grid right)
];

// Convert grid waypoints to pixel waypoints (cell centers).
const PATH = PATH_CELLS.map(([c, r]) => ({
  x: c * TILE + TILE / 2,
  y: r * TILE + TILE / 2,
}));

// Tower archetypes.
const TOWERS = {
  arrow: {
    key: "arrow",
    name: "Archer",
    cost: 50,
    range: 130,
    dmg: 14,
    cooldown: 0.45, // seconds between shots
    splash: 0,
    color: "#fbbf24", // amber
    proj: "#fde68a",
    icon: Zap,
  },
  bomb: {
    key: "bomb",
    name: "Bombard",
    cost: 110,
    range: 110,
    dmg: 30,
    cooldown: 1.25,
    splash: 48, // splash radius
    color: "#fb7185", // rose
    proj: "#fda4af",
    icon: Flame,
  },
};

// Build a set of path-occupied cells (so towers can't be placed on the road).
function buildPathCellSet() {
  const set = new Set();
  for (let i = 0; i < PATH_CELLS.length - 1; i++) {
    let [c0, r0] = PATH_CELLS[i];
    let [c1, r1] = PATH_CELLS[i + 1];
    // Clamp to grid for blocking purposes.
    const sc = Math.max(0, Math.min(COLS - 1, c0));
    const ec = Math.max(0, Math.min(COLS - 1, c1));
    const sr = Math.max(0, Math.min(ROWS - 1, r0));
    const er = Math.max(0, Math.min(ROWS - 1, r1));
    const stepC = Math.sign(ec - sc);
    const stepR = Math.sign(er - sr);
    let cc = sc;
    let rr = sr;
    set.add(cc + "," + rr);
    while (cc !== ec || rr !== er) {
      if (cc !== ec) cc += stepC;
      else if (rr !== er) rr += stepR;
      set.add(cc + "," + rr);
    }
  }
  return set;
}

const PATH_CELL_SET = buildPathCellSet();

// Total path length (for nothing critical, kept for potential tuning).
function lerp(a, b, t) {
  return a + (b - a) * t;
}

export default function Wardenfall({ userId, onGameOver, onExit }) {
  const containerRef = useRef(null);
  const canvasRef = useRef(null);
  const rafRef = useRef(0);
  const lastTsRef = useRef(0);
  const goRef = useRef(false); // guard so onGameOver fires once
  const onGameOverRef = useRef(onGameOver);

  // Keep latest callback without re-subscribing the loop.
  useEffect(() => {
    onGameOverRef.current = onGameOver;
  }, [onGameOver]);

  // ---- Mutable game world (refs) -----------------------------------------
  const G = useRef(null);
  if (G.current === null) {
    G.current = makeFreshState();
  }

  // ---- React state: HUD + screens ----------------------------------------
  const [phase, setPhase] = useState("start"); // start | playing | over
  const [hud, setHud] = useState({
    gold: START_GOLD,
    lives: START_LIVES,
    wave: 0,
    score: 0,
    nextIn: 0,
    building: "arrow",
  });
  const [finalScore, setFinalScore] = useState(0);

  function makeFreshState() {
    return {
      gold: START_GOLD,
      lives: START_LIVES,
      wave: 0,
      kills: 0,
      score: 0,
      enemies: [],
      towers: [],
      projectiles: [],
      effects: [], // transient hit/splash visuals
      spawnQueue: [], // pending enemies to spawn this wave
      spawnTimer: 0,
      betweenWaves: true,
      breakTimer: BREAK_MS / 1000,
      view: { scale: 1, ox: 0, oy: 0 }, // world->screen transform
      mouse: { x: 0, y: 0, inside: false },
      building: "arrow",
      running: false,
    };
  }

  // Score formula: waves fully survived * 100 + kills * 5.
  function computeScore(s) {
    return Math.max(0, Math.floor(s.wave * 100 + s.kills * 5));
  }

  // ---- Wave generation ----------------------------------------------------
  function spawnWave(s) {
    s.wave += 1;
    if (s.wave > 1) sfx.wave(); // wave 1 coincides with the start jingle
    const w = s.wave;
    const count = 6 + Math.floor(w * 1.5);
    const hp = Math.floor(28 * Math.pow(1.18, w - 1));
    const speed = 42 + Math.min(40, w * 2.2); // px/s
    const reward = 8 + Math.floor(w * 0.8);
    const queue = [];
    for (let i = 0; i < count; i++) {
      // Every 5th wave drop a tougher "brute".
      const brute = w >= 3 && i % 5 === 4;
      queue.push({
        hp: brute ? hp * 3 : hp,
        maxHp: brute ? hp * 3 : hp,
        speed: brute ? speed * 0.7 : speed,
        reward: brute ? reward * 3 : reward,
        radius: brute ? 13 : 9,
        brute,
      });
    }
    s.spawnQueue = queue;
    s.spawnTimer = 0;
    s.betweenWaves = false;
  }

  function startNextWaveNow() {
    const s = G.current;
    if (!s.running) return;
    if (!s.betweenWaves) return; // already running a wave
    spawnWave(s);
  }

  // ---- Coordinate helpers -------------------------------------------------
  function screenToWorld(s, sx, sy) {
    return {
      x: (sx - s.view.ox) / s.view.scale,
      y: (sy - s.view.oy) / s.view.scale,
    };
  }

  function cellFromWorld(wx, wy) {
    return { c: Math.floor(wx / TILE), r: Math.floor(wy / TILE) };
  }

  function cellBuildable(s, c, r) {
    if (c < 0 || r < 0 || c >= COLS || r >= ROWS) return false;
    if (PATH_CELL_SET.has(c + "," + r)) return false;
    for (const t of s.towers) {
      if (t.c === c && t.r === r) return false;
    }
    return true;
  }

  // ---- Placement ----------------------------------------------------------
  const tryPlaceTower = useCallback((s, sx, sy) => {
    const wp = screenToWorld(s, sx, sy);
    const { c, r } = cellFromWorld(wp.x, wp.y);
    if (!cellBuildable(s, c, r)) return;
    const spec = TOWERS[s.building];
    if (s.gold < spec.cost) return;
    s.gold -= spec.cost;
    sfx.place();
    s.towers.push({
      c,
      r,
      x: c * TILE + TILE / 2,
      y: r * TILE + TILE / 2,
      key: spec.key,
      cd: 0,
    });
  }, []);

  // ---- Main game step -----------------------------------------------------
  function step(s, dt) {
    if (!s.running) return;

    // Wave pacing.
    if (s.betweenWaves) {
      s.breakTimer -= dt;
      if (s.breakTimer <= 0) {
        spawnWave(s);
        s.breakTimer = BREAK_MS / 1000;
      }
    } else {
      // Spawn from queue.
      if (s.spawnQueue.length > 0) {
        s.spawnTimer -= dt;
        if (s.spawnTimer <= 0) {
          const def = s.spawnQueue.shift();
          s.enemies.push({
            ...def,
            seg: 0, // current path segment index
            t: 0, // 0..1 along segment
            x: PATH[0].x,
            y: PATH[0].y,
            dead: false,
          });
          s.spawnTimer = 0.55; // gap between spawns
        }
      } else if (s.enemies.length === 0) {
        // Wave cleared.
        s.gold += 25 + s.wave * 5; // clear bonus
        s.betweenWaves = true;
        s.breakTimer = BREAK_MS / 1000;
        s.score = computeScore(s);
      }
    }

    // Move enemies along the path.
    for (const e of s.enemies) {
      if (e.dead) continue;
      let remaining = e.speed * dt;
      while (remaining > 0 && e.seg < PATH.length - 1) {
        const a = PATH[e.seg];
        const b = PATH[e.seg + 1];
        const segLen = Math.hypot(b.x - a.x, b.y - a.y);
        const distLeft = segLen * (1 - e.t);
        if (remaining >= distLeft) {
          remaining -= distLeft;
          e.seg += 1;
          e.t = 0;
        } else {
          e.t += remaining / segLen;
          remaining = 0;
        }
      }
      const a = PATH[Math.min(e.seg, PATH.length - 1)];
      const b = PATH[Math.min(e.seg + 1, PATH.length - 1)];
      e.x = lerp(a.x, b.x, e.t);
      e.y = lerp(a.y, b.y, e.t);
      if (e.seg >= PATH.length - 1) {
        // Reached the keep.
        e.dead = true;
        s.lives -= 1;
        sfx.hit();
      }
    }

    // Towers fire.
    for (const t of s.towers) {
      t.cd -= dt;
      const spec = TOWERS[t.key];
      if (t.cd > 0) continue;
      // Acquire nearest living enemy in range (furthest-along bias not needed).
      let target = null;
      let best = Infinity;
      for (const e of s.enemies) {
        if (e.dead) continue;
        const d = Math.hypot(e.x - t.x, e.y - t.y);
        if (d <= spec.range && d < best) {
          best = d;
          target = e;
        }
      }
      if (target) {
        t.cd = spec.cooldown;
        sfx.shoot();
        s.projectiles.push({
          x: t.x,
          y: t.y,
          tx: target.x,
          ty: target.y,
          target,
          speed: 420,
          dmg: spec.dmg,
          splash: spec.splash,
          color: spec.proj,
        });
      }
    }

    // Move projectiles, resolve hits.
    for (const p of s.projectiles) {
      if (p.dead) continue;
      // Track a live target; if it died, fly to last known point.
      if (p.target && !p.target.dead) {
        p.tx = p.target.x;
        p.ty = p.target.y;
      }
      const dx = p.tx - p.x;
      const dy = p.ty - p.y;
      const dist = Math.hypot(dx, dy);
      const move = p.speed * dt;
      if (dist <= move || dist === 0) {
        // Impact.
        p.dead = true;
        applyDamage(s, p.tx, p.ty, p.dmg, p.splash, p.color);
      } else {
        p.x += (dx / dist) * move;
        p.y += (dy / dist) * move;
      }
    }

    // Advance effects.
    for (const fx of s.effects) {
      fx.life -= dt;
    }

    // Cull dead things; account for kills + gold.
    const stillAlive = [];
    for (const e of s.enemies) {
      if (e.dead && e.hp <= 0) {
        s.kills += 1;
        s.gold += e.reward;
        sfx.smallExplode();
      }
      if (!e.dead) stillAlive.push(e);
    }
    s.enemies = stillAlive;
    s.projectiles = s.projectiles.filter((p) => !p.dead);
    s.effects = s.effects.filter((fx) => fx.life > 0);

    s.score = computeScore(s);

    // Game over.
    if (s.lives <= 0) {
      s.lives = 0;
      s.running = false;
    }
  }

  function applyDamage(s, x, y, dmg, splash, color) {
    s.effects.push({ x, y, r: splash > 0 ? splash : 8, life: 0.22, max: 0.22, color, splash: splash > 0 });
    if (splash > 0) {
      for (const e of s.enemies) {
        if (e.dead) continue;
        if (Math.hypot(e.x - x, e.y - y) <= splash) {
          e.hp -= dmg;
          if (e.hp <= 0) e.dead = true;
        }
      }
    } else {
      // Single-target: damage nearest enemy at impact.
      let target = null;
      let best = Infinity;
      for (const e of s.enemies) {
        if (e.dead) continue;
        const d = Math.hypot(e.x - x, e.y - y);
        if (d < best) {
          best = d;
          target = e;
        }
      }
      if (target && best <= 22) {
        target.hp -= dmg;
        if (target.hp <= 0) target.dead = true;
      }
    }
  }

  // ---- Rendering ----------------------------------------------------------
  function draw(ctx, s, cw, ch) {
    // Background.
    ctx.fillStyle = "#0f172a"; // slate-900
    ctx.fillRect(0, 0, cw, ch);

    ctx.save();
    ctx.translate(s.view.ox, s.view.oy);
    ctx.scale(s.view.scale, s.view.scale);

    // Buildable field grid.
    ctx.fillStyle = "#1e293b"; // slate-800
    ctx.fillRect(0, 0, WORLD_W, WORLD_H);
    ctx.strokeStyle = "rgba(148,163,184,0.10)";
    ctx.lineWidth = 1;
    for (let c = 0; c <= COLS; c++) {
      ctx.beginPath();
      ctx.moveTo(c * TILE, 0);
      ctx.lineTo(c * TILE, WORLD_H);
      ctx.stroke();
    }
    for (let r = 0; r <= ROWS; r++) {
      ctx.beginPath();
      ctx.moveTo(0, r * TILE);
      ctx.lineTo(WORLD_W, r * TILE);
      ctx.stroke();
    }

    // Path track.
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = "#0b1220";
    ctx.lineWidth = TILE * 0.72;
    drawPathLine(ctx);
    ctx.strokeStyle = "#3b2f1c"; // dark amber dirt
    ctx.lineWidth = TILE * 0.56;
    drawPathLine(ctx);
    ctx.strokeStyle = "rgba(251,191,36,0.18)";
    ctx.lineWidth = 2;
    ctx.setLineDash([8, 10]);
    drawPathLine(ctx);
    ctx.setLineDash([]);

    // Keep (goal) at the final waypoint.
    const keep = PATH[PATH.length - 1];
    const kx = Math.min(keep.x, WORLD_W - 18);
    ctx.fillStyle = "#fbbf24";
    ctx.strokeStyle = "#78350f";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.rect(kx - 18, keep.y - 22, 30, 44);
    ctx.fill();
    ctx.stroke();
    // crenellations
    ctx.fillStyle = "#78350f";
    for (let i = 0; i < 3; i++) {
      ctx.fillRect(kx - 18 + i * 11, keep.y - 26, 6, 6);
    }

    // Build-preview / hover highlight.
    if (s.running && s.mouse.inside) {
      const wp = screenToWorld(s, s.mouse.x, s.mouse.y);
      const { c, r } = cellFromWorld(wp.x, wp.y);
      if (c >= 0 && r >= 0 && c < COLS && r < ROWS) {
        const ok = cellBuildable(s, c, r) && s.gold >= TOWERS[s.building].cost;
        const spec = TOWERS[s.building];
        const cx = c * TILE + TILE / 2;
        const cy = r * TILE + TILE / 2;
        ctx.fillStyle = ok ? "rgba(34,197,94,0.18)" : "rgba(244,63,94,0.20)";
        ctx.fillRect(c * TILE + 2, r * TILE + 2, TILE - 4, TILE - 4);
        // range preview
        ctx.beginPath();
        ctx.arc(cx, cy, spec.range, 0, Math.PI * 2);
        ctx.strokeStyle = ok ? "rgba(251,191,36,0.5)" : "rgba(244,63,94,0.45)";
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.fillStyle = ok ? "rgba(251,191,36,0.06)" : "rgba(244,63,94,0.06)";
        ctx.fill();
      }
    }

    // Towers.
    for (const t of s.towers) {
      const spec = TOWERS[t.key];
      // base
      ctx.fillStyle = "#334155";
      ctx.beginPath();
      ctx.arc(t.x, t.y, 16, 0, Math.PI * 2);
      ctx.fill();
      // turret
      ctx.fillStyle = spec.color;
      ctx.beginPath();
      ctx.arc(t.x, t.y, 10, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "#0f172a";
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    // Enemies.
    for (const e of s.enemies) {
      ctx.fillStyle = e.brute ? "#dc2626" : "#94a3b8";
      ctx.beginPath();
      ctx.arc(e.x, e.y, e.radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "#0f172a";
      ctx.lineWidth = 2;
      ctx.stroke();
      // hp bar
      const w = e.radius * 2;
      const frac = Math.max(0, e.hp / e.maxHp);
      ctx.fillStyle = "rgba(15,23,42,0.8)";
      ctx.fillRect(e.x - w / 2, e.y - e.radius - 8, w, 4);
      ctx.fillStyle = frac > 0.5 ? "#22c55e" : frac > 0.25 ? "#fbbf24" : "#ef4444";
      ctx.fillRect(e.x - w / 2, e.y - e.radius - 8, w * frac, 4);
    }

    // Projectiles.
    for (const p of s.projectiles) {
      ctx.fillStyle = p.color;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.splash > 0 ? 5 : 3.5, 0, Math.PI * 2);
      ctx.fill();
    }

    // Effects (impacts / splashes).
    for (const fx of s.effects) {
      const a = Math.max(0, fx.life / fx.max);
      ctx.strokeStyle = fx.color;
      ctx.globalAlpha = a;
      ctx.lineWidth = fx.splash ? 3 : 2;
      ctx.beginPath();
      ctx.arc(fx.x, fx.y, fx.r * (1 + (1 - a) * 0.6), 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    ctx.restore();
  }

  function drawPathLine(ctx) {
    ctx.beginPath();
    ctx.moveTo(PATH[0].x, PATH[0].y);
    for (let i = 1; i < PATH.length; i++) {
      ctx.lineTo(PATH[i].x, PATH[i].y);
    }
    ctx.stroke();
  }

  // ---- Canvas sizing / view transform ------------------------------------
  const fitCanvas = useCallback(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;
    const cw = container.clientWidth || 1;
    const ch = container.clientHeight || 1;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(cw * dpr));
    canvas.height = Math.max(1, Math.floor(ch * dpr));
    canvas.style.width = cw + "px";
    canvas.style.height = ch + "px";
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); // logical px == css px

    // Fit world into canvas with letterbox centering.
    const s = G.current;
    const scale = Math.min(cw / WORLD_W, ch / WORLD_H);
    s.view.scale = scale;
    s.view.ox = (cw - WORLD_W * scale) / 2;
    s.view.oy = (ch - WORLD_H * scale) / 2;
    s._cw = cw;
    s._ch = ch;
  }, []);

  // ---- Lifecycle: rAF loop, observers, listeners -------------------------
  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    fitCanvas();

    const ro = new ResizeObserver(() => fitCanvas());
    ro.observe(container);

    const onMove = (ev) => {
      const rect = canvas.getBoundingClientRect();
      const s = G.current;
      s.mouse.x = ev.clientX - rect.left;
      s.mouse.y = ev.clientY - rect.top;
      s.mouse.inside = true;
    };
    const onLeave = () => {
      G.current.mouse.inside = false;
    };
    const onClick = (ev) => {
      const s = G.current;
      if (!s.running) return;
      const rect = canvas.getBoundingClientRect();
      tryPlaceTower(s, ev.clientX - rect.left, ev.clientY - rect.top);
    };
    const onKey = (ev) => {
      const k = ev.key.toLowerCase();
      if (k === "1") {
        G.current.building = "arrow";
        ev.preventDefault();
      } else if (k === "2") {
        G.current.building = "bomb";
        ev.preventDefault();
      } else if (k === " " || k === "enter") {
        startNextWaveNow();
        ev.preventDefault();
      } else if (
        ["arrowup", "arrowdown", "arrowleft", "arrowright"].includes(k)
      ) {
        ev.preventDefault();
      }
    };

    canvas.addEventListener("mousemove", onMove);
    canvas.addEventListener("mouseleave", onLeave);
    canvas.addEventListener("click", onClick);
    window.addEventListener("keydown", onKey);

    const loop = (ts) => {
      const s = G.current;
      if (!lastTsRef.current) lastTsRef.current = ts;
      let dt = (ts - lastTsRef.current) / 1000;
      lastTsRef.current = ts;
      if (dt > 0.05) dt = 0.05; // clamp big frame gaps

      step(s, dt);

      const ctx = canvas.getContext("2d");
      draw(ctx, s, s._cw || container.clientWidth, s._ch || container.clientHeight);

      // Sync HUD a few times per second via React state.
      hudAccumRef.current += dt;
      if (hudAccumRef.current >= 0.1) {
        hudAccumRef.current = 0;
        setHud({
          gold: Math.floor(s.gold),
          lives: s.lives,
          wave: s.wave,
          score: s.score,
          nextIn: s.betweenWaves && s.running ? Math.ceil(s.breakTimer) : 0,
          building: s.building,
        });
      }

      // Game-over transition (once).
      if (s.lives <= 0 && !goRef.current) {
        goRef.current = true;
        const finalS = computeScore(s);
        setFinalScore(finalS);
        sfx.gameover();
        setPhase("over");
        if (typeof onGameOverRef.current === "function") {
          onGameOverRef.current(finalS);
        }
      }

      rafRef.current = requestAnimationFrame(loop);
    };
    rafRef.current = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
      canvas.removeEventListener("mousemove", onMove);
      canvas.removeEventListener("mouseleave", onLeave);
      canvas.removeEventListener("click", onClick);
      window.removeEventListener("keydown", onKey);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitCanvas, tryPlaceTower]);

  const hudAccumRef = useRef(0);

  // ---- Control actions ----------------------------------------------------
  const startGame = () => {
    resumeAudio();
    sfx.start();
    const fresh = makeFreshState();
    fresh.running = true;
    G.current = fresh;
    lastTsRef.current = 0;
    goRef.current = false;
    hudAccumRef.current = 0;
    fitCanvas();
    setFinalScore(0);
    setPhase("playing");
    setHud({
      gold: fresh.gold,
      lives: fresh.lives,
      wave: 0,
      score: 0,
      nextIn: Math.ceil(fresh.breakTimer),
      building: fresh.building,
    });
  };

  const selectTower = (key) => {
    G.current.building = key;
    setHud((h) => ({ ...h, building: key }));
  };

  const giveUp = () => {
    const s = G.current;
    if (goRef.current) return;
    goRef.current = true;
    s.running = false;
    const finalS = computeScore(s);
    setFinalScore(finalS);
    setPhase("over");
    if (typeof onGameOverRef.current === "function") {
      onGameOverRef.current(finalS);
    }
  };

  // ---- UI -----------------------------------------------------------------
  return (
    <div
      ref={containerRef}
      className="absolute inset-0 overflow-hidden bg-slate-950 select-none"
    >
      <canvas ref={canvasRef} className="block h-full w-full cursor-crosshair" />

      {/* HUD (only while playing) */}
      {phase === "playing" && (
        <>
          <div className="pointer-events-none absolute left-3 top-3 flex flex-wrap items-center gap-3 text-sm font-semibold">
            <span className="rounded-md bg-slate-900/80 px-3 py-1 text-amber-300 ring-1 ring-amber-500/30">
              Gold {hud.gold}
            </span>
            <span className="rounded-md bg-slate-900/80 px-3 py-1 text-rose-300 ring-1 ring-rose-500/30">
              Lives {hud.lives}
            </span>
            <span className="rounded-md bg-slate-900/80 px-3 py-1 text-slate-200 ring-1 ring-slate-500/30">
              Wave {hud.wave}
            </span>
            <span className="rounded-md bg-slate-900/80 px-3 py-1 text-emerald-300 ring-1 ring-emerald-500/30">
              Score {hud.score}
            </span>
            {hud.nextIn > 0 && (
              <span className="rounded-md bg-slate-900/80 px-3 py-1 text-sky-300 ring-1 ring-sky-500/30">
                Next wave in {hud.nextIn}s
              </span>
            )}
          </div>

          {/* Tower bar + actions */}
          <div className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-2">
            {Object.values(TOWERS).map((spec) => {
              const Icon = spec.icon;
              const active = hud.building === spec.key;
              return (
                <button
                  key={spec.key}
                  onClick={() => selectTower(spec.key)}
                  className={
                    "flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold ring-1 transition " +
                    (active
                      ? "bg-amber-500/20 text-amber-200 ring-amber-400/60"
                      : "bg-slate-900/80 text-slate-300 ring-slate-600/40 hover:bg-slate-800")
                  }
                  style={{ borderLeft: `4px solid ${spec.color}` }}
                >
                  <Icon size={16} />
                  {spec.name}
                  <span className="text-amber-300/80">{spec.cost}g</span>
                </button>
              );
            })}
            <button
              onClick={startNextWaveNow}
              className="rounded-lg bg-emerald-600/80 px-3 py-2 text-sm font-semibold text-white ring-1 ring-emerald-400/50 hover:bg-emerald-600"
            >
              Start wave
            </button>
            <button
              onClick={giveUp}
              className="flex items-center gap-1 rounded-lg bg-slate-900/80 px-3 py-2 text-sm font-semibold text-rose-300 ring-1 ring-rose-500/30 hover:bg-slate-800"
            >
              <LogOut size={15} /> Give up
            </button>
          </div>

          <div className="pointer-events-none absolute right-3 top-3 max-w-[14rem] rounded-md bg-slate-900/70 px-3 py-2 text-xs text-slate-400 ring-1 ring-slate-700/50">
            Click empty ground to build. Keys: 1/2 select tower, Space = start
            wave.
          </div>
        </>
      )}

      {/* Start screen */}
      {phase === "start" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-5 bg-slate-950/85 text-center">
          <div className="flex items-center gap-3 text-amber-400">
            <Shield size={34} />
            <h1 className="text-4xl font-black tracking-tight text-amber-300">
              Wardenfall
            </h1>
          </div>
          <p className="text-lg text-slate-300">Defend the pass.</p>
          <p className="max-w-md text-sm text-slate-400">
            Build wardens on the ground, hold back the waves, keep the keep.
            Click ground to build - 1/2 pick a tower - Space sends the next wave.
          </p>
          <button
            onClick={startGame}
            className="mt-2 flex items-center gap-2 rounded-xl bg-amber-500 px-7 py-3 text-lg font-bold text-slate-950 shadow-lg ring-1 ring-amber-300 transition hover:bg-amber-400"
          >
            <Play size={22} /> Play
          </button>
          {typeof onExit === "function" && (
            <button
              onClick={onExit}
              className="text-sm text-slate-500 underline-offset-2 hover:text-slate-300 hover:underline"
            >
              Back
            </button>
          )}
        </div>
      )}

      {/* Game-over overlay */}
      {phase === "over" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-5 bg-slate-950/88 text-center">
          <h2 className="text-3xl font-black text-rose-400">The keep has fallen</h2>
          <div className="rounded-xl bg-slate-900/80 px-8 py-5 ring-1 ring-slate-700/60">
            <div className="text-sm uppercase tracking-widest text-slate-400">
              Final score
            </div>
            <div className="text-5xl font-black text-amber-300">{finalScore}</div>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={startGame}
              className="flex items-center gap-2 rounded-xl bg-amber-500 px-6 py-3 font-bold text-slate-950 ring-1 ring-amber-300 transition hover:bg-amber-400"
            >
              <RotateCcw size={20} /> Play again
            </button>
            {typeof onExit === "function" && (
              <button
                onClick={onExit}
                className="flex items-center gap-2 rounded-xl bg-slate-800 px-6 py-3 font-bold text-slate-200 ring-1 ring-slate-600 transition hover:bg-slate-700"
              >
                <LogOut size={20} /> Exit
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
