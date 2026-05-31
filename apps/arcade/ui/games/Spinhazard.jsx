// =============================================================================
// Spinhazard — an old-school vector arcade shooter
// =============================================================================
// Original code. White vector lines on black, screen wrap-around, one ship,
// a field of tumbling rocks. Genre is generic; no trademarked names or assets.
//
// Host interface:
//   export default function Spinhazard({ userId, onGameOver, onExit })
//     - onGameOver(score:number) — called once when lives reach 0
//     - onExit()                 — optional; host shows a back button
//
import { useRef, useEffect, useState, useCallback } from "react";
import { ArrowLeft } from "lucide-react";

// ---- tunables ---------------------------------------------------------------
const SHIP_R = 14;              // ship radius (nose distance)
const TURN_RATE = 4.2;          // radians/sec
const THRUST = 240;             // px/sec^2
const DRAG = 0.6;               // velocity damping per sec (fraction)
const MAX_SPEED = 520;
const BULLET_SPEED = 560;
const BULLET_LIFE = 0.85;       // seconds
const FIRE_COOLDOWN = 0.18;     // seconds between shots
const MAX_BULLETS = 5;
const INVULN_TIME = 2.4;        // seconds of respawn invulnerability
const ROCK_SIZES = {
  large: { r: 46, score: 20, next: "medium" },
  medium: { r: 26, score: 50, next: "small" },
  small: { r: 14, score: 100, next: null },
};
const HAZARD_R = 9;
const HAZARD_SCORE = 150;
const HAZARD_SPEED = 300;
const TAU = Math.PI * 2;

// ---- small helpers ----------------------------------------------------------
const rand = (a, b) => a + Math.random() * (b - a);
const wrap = (v, max) => ((v % max) + max) % max;

// Build a jagged polygon (unit offsets) for a rock so each rock looks unique.
function makeRockShape(verts) {
  const pts = [];
  for (let i = 0; i < verts; i++) {
    const ang = (i / verts) * TAU;
    const jag = rand(0.72, 1.12);
    pts.push([Math.cos(ang) * jag, Math.sin(ang) * jag]);
  }
  return pts;
}

function makeRock(size, x, y, speedScale) {
  const def = ROCK_SIZES[size];
  const ang = rand(0, TAU);
  const spd = rand(28, 64) * speedScale;
  return {
    size,
    r: def.r,
    x,
    y,
    vx: Math.cos(ang) * spd,
    vy: Math.sin(ang) * spd,
    rot: rand(0, TAU),
    spin: rand(-1.1, 1.1),
    shape: makeRockShape(Math.floor(rand(8, 12))),
  };
}

export default function Spinhazard({ userId, onGameOver, onExit }) {
  const containerRef = useRef(null);
  const canvasRef = useRef(null);
  const rafRef = useRef(0);
  const lastTsRef = useRef(0);
  const gameOverFiredRef = useRef(false);

  // Logical canvas size in CSS pixels (kept in a ref for the loop).
  const sizeRef = useRef({ w: 800, h: 600 });

  // Input state.
  const keysRef = useRef({ left: false, right: false, thrust: false, fire: false });

  // Mutable game world (never triggers React renders).
  const worldRef = useRef(null);

  // Phase drives overlays only: "start" | "playing" | "over".
  const [phase, setPhase] = useState("start");
  const [hud, setHud] = useState({ score: 0, lives: 3, wave: 1 });

  // Initialise / reset the whole world.
  const resetWorld = useCallback(() => {
    const { w, h } = sizeRef.current;
    worldRef.current = {
      ship: {
        x: w / 2,
        y: h / 2,
        vx: 0,
        vy: 0,
        angle: -Math.PI / 2, // pointing up
        invuln: INVULN_TIME,
        alive: true,
      },
      bullets: [],
      rocks: [],
      hazard: null,
      hazardTimer: rand(8, 16),
      score: 0,
      lives: 3,
      wave: 0,
      fireCd: 0,
      shake: 0,
      thrustFlicker: 0,
    };
    gameOverFiredRef.current = false;
    spawnWave(worldRef.current, 1);
  }, []);

  // Populate a wave. More & faster rocks each time.
  const spawnWave = (world, waveNum) => {
    const { w, h } = sizeRef.current;
    world.wave = waveNum;
    const count = 3 + waveNum; // 4, 5, 6, ...
    const speedScale = 1 + (waveNum - 1) * 0.16;
    for (let i = 0; i < count; i++) {
      // Spawn away from the ship so the player isn't instantly hit.
      let x, y, tries = 0;
      do {
        x = rand(0, w);
        y = rand(0, h);
        tries++;
      } while (
        tries < 30 &&
        Math.hypot(x - world.ship.x, y - world.ship.y) < 160
      );
      world.rocks.push(makeRock("large", x, y, speedScale));
    }
  };

  // ---- canvas sizing (DPR-aware) --------------------------------------------
  const fitCanvas = useCallback(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, container.clientWidth);
    const h = Math.max(1, container.clientHeight);
    sizeRef.current = { w, h };
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }, []);

  // ---- main effect: loop + listeners + observer -----------------------------
  useEffect(() => {
    fitCanvas();

    const ro = new ResizeObserver(() => fitCanvas());
    if (containerRef.current) ro.observe(containerRef.current);

    const onKeyDown = (e) => {
      switch (e.code) {
        case "ArrowLeft":
        case "KeyA":
          keysRef.current.left = true;
          e.preventDefault();
          break;
        case "ArrowRight":
        case "KeyD":
          keysRef.current.right = true;
          e.preventDefault();
          break;
        case "ArrowUp":
        case "KeyW":
          keysRef.current.thrust = true;
          e.preventDefault();
          break;
        case "Space":
          keysRef.current.fire = true;
          e.preventDefault();
          break;
        default:
          break;
      }
    };
    const onKeyUp = (e) => {
      switch (e.code) {
        case "ArrowLeft":
        case "KeyA":
          keysRef.current.left = false;
          break;
        case "ArrowRight":
        case "KeyD":
          keysRef.current.right = false;
          break;
        case "ArrowUp":
        case "KeyW":
          keysRef.current.thrust = false;
          break;
        case "Space":
          keysRef.current.fire = false;
          break;
        default:
          break;
      }
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    // Also bind to the focusable container and focus it. In the desktop shell,
    // window keydown isn't always delivered to the game (focus is elsewhere and
    // arrow keys get consumed for scroll/nav), so a focused element that owns
    // the listener is the reliable path; window stays as a fallback.
    const container = containerRef.current;
    if (container) {
      container.addEventListener("keydown", onKeyDown);
      container.addEventListener("keyup", onKeyUp);
      container.focus();
    }

    const step = (ts) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!lastTsRef.current) lastTsRef.current = ts;
      let dt = (ts - lastTsRef.current) / 1000;
      lastTsRef.current = ts;
      if (dt > 0.05) dt = 0.05; // clamp big frame gaps (tab switch)

      const world = worldRef.current;
      if (world && phaseRef.current === "playing") {
        update(world, dt);
      }
      render(ctx, world);

      rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);

    return () => {
      cancelAnimationFrame(rafRef.current);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      if (container) {
        container.removeEventListener("keydown", onKeyDown);
        container.removeEventListener("keyup", onKeyUp);
      }
      ro.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitCanvas]);

  // Keep a ref mirror of phase so the rAF closure reads the latest value
  // without re-subscribing the whole loop on every phase change.
  const phaseRef = useRef(phase);
  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  // ---- simulation -----------------------------------------------------------
  const update = (world, dt) => {
    const { w, h } = sizeRef.current;
    const keys = keysRef.current;
    const ship = world.ship;

    // Timers.
    world.fireCd = Math.max(0, world.fireCd - dt);
    world.shake = Math.max(0, world.shake - dt * 60);
    if (ship.invuln > 0) ship.invuln = Math.max(0, ship.invuln - dt);

    // Ship controls.
    if (ship.alive) {
      if (keys.left) ship.angle -= TURN_RATE * dt;
      if (keys.right) ship.angle += TURN_RATE * dt;
      if (keys.thrust) {
        ship.vx += Math.cos(ship.angle) * THRUST * dt;
        ship.vy += Math.sin(ship.angle) * THRUST * dt;
        world.thrustFlicker = Math.random();
      }
      // Drag + speed clamp.
      const damp = Math.max(0, 1 - DRAG * dt);
      ship.vx *= damp;
      ship.vy *= damp;
      const sp = Math.hypot(ship.vx, ship.vy);
      if (sp > MAX_SPEED) {
        ship.vx = (ship.vx / sp) * MAX_SPEED;
        ship.vy = (ship.vy / sp) * MAX_SPEED;
      }
      ship.x = wrap(ship.x + ship.vx * dt, w);
      ship.y = wrap(ship.y + ship.vy * dt, h);

      // Fire.
      if (keys.fire && world.fireCd <= 0 && world.bullets.length < MAX_BULLETS) {
        world.fireCd = FIRE_COOLDOWN;
        const nx = Math.cos(ship.angle);
        const ny = Math.sin(ship.angle);
        world.bullets.push({
          x: ship.x + nx * SHIP_R,
          y: ship.y + ny * SHIP_R,
          vx: ship.vx + nx * BULLET_SPEED,
          vy: ship.vy + ny * BULLET_SPEED,
          life: BULLET_LIFE,
        });
      }
    }

    // Bullets.
    for (let i = world.bullets.length - 1; i >= 0; i--) {
      const b = world.bullets[i];
      b.life -= dt;
      b.x = wrap(b.x + b.vx * dt, w);
      b.y = wrap(b.y + b.vy * dt, h);
      if (b.life <= 0) world.bullets.splice(i, 1);
    }

    // Rocks move + spin.
    for (const r of world.rocks) {
      r.x = wrap(r.x + r.vx * dt, w);
      r.y = wrap(r.y + r.vy * dt, h);
      r.rot += r.spin * dt;
    }

    // Hazard (occasional small fast crosser).
    world.hazardTimer -= dt;
    if (!world.hazard && world.hazardTimer <= 0) {
      const fromLeft = Math.random() < 0.5;
      const y = rand(h * 0.1, h * 0.9);
      world.hazard = {
        x: fromLeft ? -HAZARD_R : w + HAZARD_R,
        y,
        vx: (fromLeft ? 1 : -1) * HAZARD_SPEED,
        vy: rand(-60, 60),
      };
    }
    if (world.hazard) {
      const hz = world.hazard;
      hz.x += hz.vx * dt;
      hz.y = wrap(hz.y + hz.vy * dt, h);
      if (hz.x < -40 || hz.x > w + 40) {
        world.hazard = null;
        world.hazardTimer = rand(10, 20);
      }
    }

    // Bullet vs rock collisions (split logic).
    for (let bi = world.bullets.length - 1; bi >= 0; bi--) {
      const b = world.bullets[bi];
      let hit = false;
      for (let ri = world.rocks.length - 1; ri >= 0; ri--) {
        const r = world.rocks[ri];
        if (Math.hypot(b.x - r.x, b.y - r.y) <= r.r) {
          // Score + split.
          const def = ROCK_SIZES[r.size];
          world.score += def.score;
          world.rocks.splice(ri, 1);
          if (def.next) {
            const speedScale = 1 + (world.wave - 1) * 0.16 + 0.3;
            const a = makeRock(def.next, r.x, r.y, speedScale);
            const bb = makeRock(def.next, r.x, r.y, speedScale);
            world.rocks.push(a, bb);
          }
          hit = true;
          break;
        }
      }
      if (hit) world.bullets.splice(bi, 1);
    }

    // Bullet vs hazard.
    if (world.hazard) {
      for (let bi = world.bullets.length - 1; bi >= 0; bi--) {
        const b = world.bullets[bi];
        if (Math.hypot(b.x - world.hazard.x, b.y - world.hazard.y) <= HAZARD_R + 2) {
          world.score += HAZARD_SCORE;
          world.bullets.splice(bi, 1);
          world.hazard = null;
          world.hazardTimer = rand(10, 20);
          break;
        }
      }
    }

    // Ship vs rocks / hazard (only when vulnerable).
    if (ship.alive && ship.invuln <= 0) {
      let died = false;
      for (const r of world.rocks) {
        if (Math.hypot(ship.x - r.x, ship.y - r.y) <= r.r + SHIP_R * 0.7) {
          died = true;
          break;
        }
      }
      if (!died && world.hazard) {
        if (
          Math.hypot(ship.x - world.hazard.x, ship.y - world.hazard.y) <=
          HAZARD_R + SHIP_R * 0.7
        ) {
          died = true;
        }
      }
      if (died) killShip(world);
    }

    // Wave cleared?
    if (world.rocks.length === 0) {
      spawnWave(world, world.wave + 1);
    }

    // Sync HUD (cheap; values rarely change visually per frame anyway).
    setHud((prev) =>
      prev.score === world.score && prev.lives === world.lives && prev.wave === world.wave
        ? prev
        : { score: world.score, lives: world.lives, wave: world.wave }
    );
  };

  const killShip = (world) => {
    world.lives -= 1;
    world.shake = 18;
    if (world.lives <= 0) {
      world.ship.alive = false;
      // Fire game over exactly once.
      if (!gameOverFiredRef.current) {
        gameOverFiredRef.current = true;
        const finalScore = Math.round(world.score);
        setPhase("over");
        if (typeof onGameOver === "function") onGameOver(finalScore);
      }
    } else {
      const { w, h } = sizeRef.current;
      world.ship.x = w / 2;
      world.ship.y = h / 2;
      world.ship.vx = 0;
      world.ship.vy = 0;
      world.ship.angle = -Math.PI / 2;
      world.ship.invuln = INVULN_TIME;
    }
  };

  // ---- rendering ------------------------------------------------------------
  const render = (ctx, world) => {
    const { w, h } = sizeRef.current;

    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, w, h);
    if (!world) return;

    ctx.save();
    if (world.shake > 0) {
      ctx.translate(rand(-world.shake, world.shake) * 0.4, rand(-world.shake, world.shake) * 0.4);
    }

    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.strokeStyle = "#fff";
    ctx.fillStyle = "#fff";

    // Rocks.
    ctx.lineWidth = 1.6;
    for (const r of world.rocks) {
      ctx.save();
      ctx.translate(r.x, r.y);
      ctx.rotate(r.rot);
      ctx.beginPath();
      r.shape.forEach(([px, py], i) => {
        const x = px * r.r;
        const y = py * r.r;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.closePath();
      ctx.stroke();
      ctx.restore();
    }

    // Bullets.
    ctx.lineWidth = 2;
    for (const b of world.bullets) {
      ctx.beginPath();
      ctx.arc(b.x, b.y, 1.6, 0, TAU);
      ctx.fill();
    }

    // Hazard (a little spinning diamond).
    if (world.hazard) {
      const hz = world.hazard;
      ctx.save();
      ctx.translate(hz.x, hz.y);
      ctx.rotate((world.shake + hz.x) * 0.05);
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.moveTo(0, -HAZARD_R);
      ctx.lineTo(HAZARD_R, 0);
      ctx.lineTo(0, HAZARD_R);
      ctx.lineTo(-HAZARD_R, 0);
      ctx.closePath();
      ctx.stroke();
      ctx.restore();
    }

    // Ship (blink while invulnerable).
    const ship = world.ship;
    const blinkOn = ship.invuln <= 0 || Math.floor(ship.invuln * 12) % 2 === 0;
    if (ship.alive && blinkOn) {
      ctx.save();
      ctx.translate(ship.x, ship.y);
      ctx.rotate(ship.angle);
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      ctx.moveTo(SHIP_R, 0);              // nose
      ctx.lineTo(-SHIP_R * 0.8, SHIP_R * 0.7);
      ctx.lineTo(-SHIP_R * 0.45, 0);
      ctx.lineTo(-SHIP_R * 0.8, -SHIP_R * 0.7);
      ctx.closePath();
      ctx.stroke();

      // Thrust flame flicker.
      if (keysRef.current.thrust && world.thrustFlicker > 0.35) {
        ctx.beginPath();
        ctx.moveTo(-SHIP_R * 0.45, 0);
        ctx.lineTo(-SHIP_R * (0.9 + Math.random() * 0.6), 0);
        ctx.stroke();
      }
      ctx.restore();
    }

    ctx.restore(); // matches the shake save() at the top of render
  };

  // ---- UI actions -----------------------------------------------------------
  const launch = useCallback(() => {
    fitCanvas();
    resetWorld();
    lastTsRef.current = 0;
    setHud({ score: 0, lives: 3, wave: 1 });
    setPhase("playing");
    // The start overlay's button had focus; move it back to the game so the
    // container key listener receives input.
    containerRef.current?.focus();
  }, [fitCanvas, resetWorld]);

  // ---------------------------------------------------------------------------
  return (
    <div
      ref={containerRef}
      tabIndex={0}
      onPointerDown={() => containerRef.current?.focus()}
      className="absolute inset-0 bg-black overflow-hidden select-none outline-none"
    >
      <canvas ref={canvasRef} className="block w-full h-full" />

      {/* HUD */}
      {phase === "playing" && (
        <div className="pointer-events-none absolute top-0 left-0 right-0 flex items-start justify-between p-3 font-mono text-sm text-white">
          <div className="tracking-widest">
            SCORE {String(hud.score).padStart(6, "0")}
          </div>
          <div className="tracking-widest">WAVE {hud.wave}</div>
          <div className="flex items-center gap-1 tracking-widest">
            <span className="mr-1">LIVES</span>
            {Array.from({ length: hud.lives }).map((_, i) => (
              <span key={i} aria-hidden>
                &#9650;
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Back button */}
      {typeof onExit === "function" && (
        <button
          onClick={onExit}
          className="absolute bottom-3 left-3 z-10 flex items-center gap-1 rounded border border-white/30 bg-black/60 px-3 py-1.5 font-mono text-xs text-white/80 hover:bg-white/10 hover:text-white transition"
        >
          <ArrowLeft size={14} /> Back
        </button>
      )}

      {/* Start overlay */}
      {phase === "start" && (
        <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-6 bg-black/80 font-mono text-white">
          <h1 className="text-5xl font-bold tracking-[0.3em]">SPINHAZARD</h1>
          <p className="text-sm tracking-wider text-white/70">
            &larr; &rarr; rotate &middot; &uarr; thrust &middot; space fire
          </p>
          <button
            onClick={launch}
            className="rounded border-2 border-white px-8 py-3 text-lg tracking-[0.3em] text-white hover:bg-white hover:text-black transition"
          >
            LAUNCH
          </button>
        </div>
      )}

      {/* Game over overlay */}
      {phase === "over" && (
        <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-6 bg-black/80 font-mono text-white">
          <h2 className="text-4xl font-bold tracking-[0.3em]">GAME OVER</h2>
          <p className="text-xl tracking-widest">
            FINAL SCORE {String(hud.score).padStart(6, "0")}
          </p>
          <button
            onClick={launch}
            className="rounded border-2 border-white px-8 py-3 text-lg tracking-[0.3em] text-white hover:bg-white hover:text-black transition"
          >
            PLAY AGAIN
          </button>
        </div>
      )}
    </div>
  );
}
