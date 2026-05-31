import React, { useRef, useEffect, useState, useCallback } from "react";
import * as THREE from "three";
import { ArrowLeft, Flag, RotateCcw, Sparkles } from "lucide-react";
import { sfx, resume as resumeAudio } from "../sfx";

/**
 * Aeldrift — a small 3D world-exploration game.
 *
 * The player drives a glowing orb-craft across a low-poly island world,
 * collecting bobbing light-shards. Collect them all (or hit "Finish run")
 * to end the run. Score = number of shards collected.
 *
 * Self-contained: builds the entire world from three.js primitives. No assets.
 */

const SHARD_COUNT = 16;
const WORLD_RADIUS = 60; // shards/scenery scatter radius
const COLLECT_DIST = 3.2; // distance at which a shard is picked up

export default function Aeldrift({ userId, onGameOver, onExit }) {
  const mountRef = useRef(null);
  const rootRef = useRef(null);

  // Refs to the live three.js objects so the animation loop can read them
  // without re-creating the scene on every React render.
  const threeRef = useRef(null);
  const keysRef = useRef({});
  const startedRef = useRef(false);
  const gameOverFiredRef = useRef(false);

  const [phase, setPhase] = useState("start"); // "start" | "playing" | "cleared"
  const [collected, setCollected] = useState(0);

  // Mirror `phase` into a ref so the (mount-once) animation loop can read the
  // current phase without being re-created. Declared before the setup effect.
  const phaseRef = useRef(phase);
  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  // Stable callback the loop can read the current value through a ref.
  const collectedRef = useRef(0);
  useEffect(() => {
    collectedRef.current = collected;
  }, [collected]);

  // Fire onGameOver exactly once.
  const fireGameOver = useCallback(
    (score) => {
      if (gameOverFiredRef.current) return;
      gameOverFiredRef.current = true;
      if (typeof onGameOver === "function") onGameOver(score | 0);
    },
    [onGameOver]
  );

  const startPlaying = useCallback(() => {
    resumeAudio();
    sfx.start();
    startedRef.current = true;
    setPhase("playing");
    // The start button had focus; hand it back to the game element.
    rootRef.current?.focus();
  }, []);

  const resetRun = useCallback(() => {
    const t = threeRef.current;
    if (!t) return;
    // Restore all shards and reset avatar.
    t.shards.forEach((s) => {
      s.collected = false;
      s.mesh.visible = true;
      s.mesh.scale.setScalar(1);
    });
    t.avatar.position.set(0, 1.2, 0);
    t.avatarVel.set(0, 0, 0);
    t.heading = 0;
    gameOverFiredRef.current = false;
    collectedRef.current = 0;
    setCollected(0);
    resumeAudio();
    sfx.start();
    startedRef.current = true;
    setPhase("playing");
    rootRef.current?.focus();
  }, []);

  // ---- Scene setup / teardown (runs once for the component's lifetime) ----
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const width = mount.clientWidth || 800;
    const height = mount.clientHeight || 600;

    // Scene + atmosphere
    const scene = new THREE.Scene();
    const skyColor = new THREE.Color(0x9fd0e6);
    scene.background = skyColor;
    scene.fog = new THREE.Fog(0x9fd0e6, 55, 150);

    const camera = new THREE.PerspectiveCamera(60, width / height, 0.1, 500);
    camera.position.set(0, 8, 14);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(width, height);
    mount.appendChild(renderer.domElement);
    renderer.domElement.style.display = "block";

    // Track all geometries/materials we create so we can dispose them.
    const geometries = [];
    const materials = [];
    const track = (geo, mat) => {
      if (geo) geometries.push(geo);
      if (mat) (Array.isArray(mat) ? mat : [mat]).forEach((m) => materials.push(m));
      return { geo, mat };
    };

    // Lighting
    const hemi = new THREE.HemisphereLight(0xbfe3ff, 0x3a5a2a, 0.95);
    scene.add(hemi);
    const sun = new THREE.DirectionalLight(0xfff3d6, 1.1);
    sun.position.set(30, 50, 20);
    scene.add(sun);

    // Ground plane
    {
      const geo = new THREE.CircleGeometry(WORLD_RADIUS + 40, 48);
      const mat = new THREE.MeshStandardMaterial({
        color: 0x4f8b3f,
        roughness: 1,
        metalness: 0,
      });
      track(geo, mat);
      const ground = new THREE.Mesh(geo, mat);
      ground.rotation.x = -Math.PI / 2;
      ground.position.y = 0;
      scene.add(ground);
    }

    // A few "islands" / mounds (flattened spheres) for visual variety
    const moundColors = [0x6aa84f, 0x57913f, 0x7cb35e];
    for (let i = 0; i < 7; i++) {
      const r = 6 + Math.random() * 10;
      const geo = new THREE.SphereGeometry(r, 16, 12);
      const mat = new THREE.MeshStandardMaterial({
        color: moundColors[i % moundColors.length],
        roughness: 1,
        flatShading: true,
      });
      track(geo, mat);
      const mound = new THREE.Mesh(geo, mat);
      const a = Math.random() * Math.PI * 2;
      const d = 18 + Math.random() * (WORLD_RADIUS - 10);
      mound.position.set(Math.cos(a) * d, -r * 0.55, Math.sin(a) * d);
      mound.scale.y = 0.5;
      scene.add(mound);
    }

    // Trees: cone (foliage) on a thin box (trunk)
    const trunkGeo = track(new THREE.CylinderGeometry(0.35, 0.5, 2.4, 6)).geo;
    const trunkMat = track(
      null,
      new THREE.MeshStandardMaterial({ color: 0x6b4a2b, roughness: 1 })
    ).mat;
    const leafGeo = track(new THREE.ConeGeometry(2, 4.5, 7)).geo;
    const leafMat = track(
      null,
      new THREE.MeshStandardMaterial({
        color: 0x2f6d3a,
        roughness: 1,
        flatShading: true,
      })
    ).mat;
    for (let i = 0; i < 24; i++) {
      const a = Math.random() * Math.PI * 2;
      const d = 12 + Math.random() * (WORLD_RADIUS + 10);
      const x = Math.cos(a) * d;
      const z = Math.sin(a) * d;
      const trunk = new THREE.Mesh(trunkGeo, trunkMat);
      trunk.position.set(x, 1.2, z);
      const leaf = new THREE.Mesh(leafGeo, leafMat);
      leaf.position.set(x, 4.0, z);
      const s = 0.7 + Math.random() * 0.8;
      trunk.scale.setScalar(s);
      leaf.scale.setScalar(s);
      scene.add(trunk);
      scene.add(leaf);
    }

    // Some scattered rock blocks
    const rockGeo = track(new THREE.BoxGeometry(2, 2, 2)).geo;
    const rockMat = track(
      null,
      new THREE.MeshStandardMaterial({ color: 0x8a8f99, roughness: 1, flatShading: true })
    ).mat;
    for (let i = 0; i < 12; i++) {
      const a = Math.random() * Math.PI * 2;
      const d = 10 + Math.random() * WORLD_RADIUS;
      const rock = new THREE.Mesh(rockGeo, rockMat);
      rock.position.set(Math.cos(a) * d, 0.6 + Math.random() * 0.6, Math.sin(a) * d);
      rock.rotation.y = Math.random() * Math.PI;
      rock.scale.setScalar(0.6 + Math.random() * 1.1);
      scene.add(rock);
    }

    // Avatar: a glowing orb with a small "fin" to show heading
    const avatar = new THREE.Group();
    const orbGeo = track(new THREE.IcosahedronGeometry(1, 1)).geo;
    const orbMat = track(
      null,
      new THREE.MeshStandardMaterial({
        color: 0x2a3a5a,
        emissive: 0x3aa0ff,
        emissiveIntensity: 0.7,
        roughness: 0.4,
        metalness: 0.2,
      })
    ).mat;
    const orb = new THREE.Mesh(orbGeo, orbMat);
    avatar.add(orb);
    const finGeo = track(new THREE.ConeGeometry(0.6, 1.6, 4)).geo;
    const finMat = track(
      null,
      new THREE.MeshStandardMaterial({ color: 0x9fd8ff, emissive: 0x2266aa, emissiveIntensity: 0.5 })
    ).mat;
    const fin = new THREE.Mesh(finGeo, finMat);
    fin.rotation.x = Math.PI / 2; // point along -Z (forward)
    fin.position.set(0, 0, -1.0);
    avatar.add(fin);
    // A soft light traveling with the avatar
    const avatarLight = new THREE.PointLight(0x66bbff, 0.8, 18);
    avatarLight.position.set(0, 1.5, 0);
    avatar.add(avatarLight);
    avatar.position.set(0, 1.2, 0);
    scene.add(avatar);

    // Light-shards: glowing octahedrons that bob + spin
    const shardGeo = track(new THREE.OctahedronGeometry(0.9, 0)).geo;
    const shards = [];
    for (let i = 0; i < SHARD_COUNT; i++) {
      const mat = new THREE.MeshStandardMaterial({
        color: 0xfff2a8,
        emissive: 0xffd23a,
        emissiveIntensity: 1.1,
        roughness: 0.3,
        metalness: 0.1,
      });
      materials.push(mat);
      const mesh = new THREE.Mesh(shardGeo, mat);
      const a = Math.random() * Math.PI * 2;
      const d = 8 + Math.random() * WORLD_RADIUS;
      const baseY = 1.6 + Math.random() * 2.5;
      mesh.position.set(Math.cos(a) * d, baseY, Math.sin(a) * d);
      scene.add(mesh);
      shards.push({
        mesh,
        collected: false,
        baseY,
        phase: Math.random() * Math.PI * 2,
      });
    }

    // Movement state
    const avatarVel = new THREE.Vector3();
    const camTarget = new THREE.Vector3();
    const desiredCamPos = new THREE.Vector3();
    const tmp = new THREE.Vector3();
    const clock = new THREE.Clock();

    threeRef.current = {
      scene,
      camera,
      renderer,
      avatar,
      avatarVel,
      heading: 0,
      shards,
    };

    // ---- Input ----
    const gameKeys = new Set([
      "w", "a", "s", "d",
      "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
    ]);
    const onKeyDown = (e) => {
      const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      if (gameKeys.has(k)) {
        e.preventDefault();
        keysRef.current[k] = true;
      }
    };
    const onKeyUp = (e) => {
      const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      if (gameKeys.has(k)) {
        e.preventDefault();
        keysRef.current[k] = false;
      }
    };
    window.addEventListener("keydown", onKeyDown, { passive: false });
    window.addEventListener("keyup", onKeyUp, { passive: false });
    // Also bind to the focusable root and focus it. In the desktop shell,
    // window keydown isn't reliably delivered to the game (focus is elsewhere
    // and arrow keys get consumed for scroll/nav), so a focused element that
    // owns the listener is the reliable path; window stays as a fallback.
    const root = rootRef.current;
    if (root) {
      root.addEventListener("keydown", onKeyDown, { passive: false });
      root.addEventListener("keyup", onKeyUp, { passive: false });
      root.focus();
    }

    // ---- Resize handling ----
    const fit = () => {
      const w = mount.clientWidth || 1;
      const h = mount.clientHeight || 1;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(fit);
    ro.observe(mount);

    // ---- Animation loop ----
    const ref = threeRef.current;
    const ACCEL = 26;
    const MAX_SPEED = 18;
    const TURN_RATE = 2.4;
    const DRAG = 3.0;

    const loop = () => {
      const dt = Math.min(clock.getDelta(), 0.05);
      const keys = keysRef.current;

      if (startedRef.current && phaseAllowsPlay()) {
        // Turning
        let turn = 0;
        if (keys["a"] || keys["ArrowLeft"]) turn += 1;
        if (keys["d"] || keys["ArrowRight"]) turn -= 1;
        ref.heading += turn * TURN_RATE * dt;

        // Forward/back thrust along heading
        let thrust = 0;
        if (keys["w"] || keys["ArrowUp"]) thrust += 1;
        if (keys["s"] || keys["ArrowDown"]) thrust -= 1;

        const fwd = tmp.set(Math.sin(ref.heading), 0, Math.cos(ref.heading));
        // Forward is -Z when heading=0, so invert:
        fwd.multiplyScalar(-1);
        avatarVel.addScaledVector(fwd, thrust * ACCEL * dt);

        // Drag
        avatarVel.multiplyScalar(Math.max(0, 1 - DRAG * dt));
        const speed = avatarVel.length();
        if (speed > MAX_SPEED) avatarVel.multiplyScalar(MAX_SPEED / speed);

        avatar.position.addScaledVector(avatarVel, dt);

        // Keep inside world bounds
        const distFromCenter = Math.hypot(avatar.position.x, avatar.position.z);
        const limit = WORLD_RADIUS + 30;
        if (distFromCenter > limit) {
          const f = limit / distFromCenter;
          avatar.position.x *= f;
          avatar.position.z *= f;
          avatarVel.multiplyScalar(0.4);
        }

        // Orientation: face heading + gentle bob
        avatar.rotation.y = ref.heading;
        avatar.position.y = 1.2 + Math.sin(clock.elapsedTime * 2) * 0.12;

        // Shard collection
        let gained = 0;
        for (const s of shards) {
          if (s.collected) continue;
          const d = avatar.position.distanceTo(s.mesh.position);
          if (d < COLLECT_DIST) {
            s.collected = true;
            s.mesh.visible = false;
            gained++;
          }
        }
        if (gained > 0) {
          const next = collectedRef.current + gained;
          collectedRef.current = next;
          setCollected(next);
          if (next >= SHARD_COUNT) {
            sfx.win();
            setPhase("cleared");
            fireGameOver(next);
          } else {
            sfx.pickup();
          }
        }
      }

      // Shard bob/spin always animates (cheap, looks alive even on start screen)
      const t = clock.elapsedTime;
      for (const s of shards) {
        if (s.collected) continue;
        s.mesh.rotation.y += dt * 1.2;
        s.mesh.rotation.x += dt * 0.6;
        s.mesh.position.y = s.baseY + Math.sin(t * 1.6 + s.phase) * 0.35;
      }

      // Third-person camera: follow behind + above, lerped
      const back = tmp.set(Math.sin(ref.heading), 0, Math.cos(ref.heading));
      // behind = +Z of facing direction (facing is -Z), so place camera along +back
      desiredCamPos.copy(avatar.position).addScaledVector(back, 12);
      desiredCamPos.y = avatar.position.y + 7;
      camera.position.lerp(desiredCamPos, Math.min(1, dt * 3.5));
      camTarget.copy(avatar.position);
      camTarget.y += 1.5;
      camera.lookAt(camTarget);

      renderer.render(scene, camera);
    };

    // We read React phase via a ref-free closure helper to avoid stale state.
    function phaseAllowsPlay() {
      // startedRef gates the heavy logic; "cleared" stops driving.
      return phaseRef.current === "playing";
    }

    renderer.setAnimationLoop(loop);

    // Cleanup
    return () => {
      renderer.setAnimationLoop(null);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      if (root) {
        root.removeEventListener("keydown", onKeyDown);
        root.removeEventListener("keyup", onKeyUp);
      }
      ro.disconnect();

      // Dispose geometries + materials
      geometries.forEach((g) => g && g.dispose && g.dispose());
      materials.forEach((m) => m && m.dispose && m.dispose());

      // Remove canvas + free GL context
      if (renderer.domElement && renderer.domElement.parentNode) {
        renderer.domElement.parentNode.removeChild(renderer.domElement);
      }
      renderer.dispose();

      threeRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fireGameOver]);

  const handleFinish = useCallback(() => {
    sfx.wave();
    fireGameOver(collectedRef.current);
    setPhase("cleared");
  }, [fireGameOver]);

  return (
    <div
      ref={rootRef}
      tabIndex={0}
      onPointerDown={() => rootRef.current?.focus()}
      className="absolute inset-0 overflow-hidden select-none outline-none"
    >
      {/* three.js canvas mount */}
      <div ref={mountRef} className="absolute inset-0" />

      {/* HUD (only while playing) */}
      {phase === "playing" && (
        <>
          <div className="absolute top-3 left-3 flex items-center gap-2 rounded-lg bg-black/45 px-3 py-2 text-white backdrop-blur-sm">
            <Sparkles className="h-4 w-4 text-yellow-300" />
            <span className="font-semibold tabular-nums">
              shards {collected} / {SHARD_COUNT}
            </span>
          </div>

          <button
            onClick={handleFinish}
            className="absolute bottom-3 right-3 flex items-center gap-1.5 rounded-lg bg-rose-600/90 px-3 py-2 text-sm font-semibold text-white shadow-lg transition hover:bg-rose-500"
          >
            <Flag className="h-4 w-4" />
            Finish run
          </button>

          <div className="absolute bottom-3 left-3 rounded-lg bg-black/35 px-3 py-1.5 text-xs text-white/80 backdrop-blur-sm">
            WASD / Arrows to drift
          </div>
        </>
      )}

      {/* Back button (host-provided exit) */}
      {typeof onExit === "function" && (
        <button
          onClick={onExit}
          className="absolute top-3 right-3 flex items-center gap-1.5 rounded-lg bg-black/45 px-3 py-2 text-sm font-medium text-white backdrop-blur-sm transition hover:bg-black/60"
        >
          <ArrowLeft className="h-4 w-4" />
          Exit
        </button>
      )}

      {/* Start overlay */}
      {phase === "start" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-gradient-to-b from-sky-900/70 to-slate-900/80 text-center text-white backdrop-blur-sm">
          <Sparkles className="mb-3 h-10 w-10 text-yellow-300" />
          <h1 className="text-5xl font-black tracking-tight drop-shadow">Aeldrift</h1>
          <p className="mt-3 max-w-md text-sm text-white/80">
            Drift across the isles and gather all {SHARD_COUNT} light-shards.
            Steer with <span className="font-semibold">WASD</span> or the{" "}
            <span className="font-semibold">arrow keys</span>.
          </p>
          <button
            onClick={startPlaying}
            className="mt-6 rounded-xl bg-sky-500 px-8 py-3 text-lg font-bold shadow-lg transition hover:bg-sky-400"
          >
            Drift in
          </button>
        </div>
      )}

      {/* Cleared / finished overlay */}
      {phase === "cleared" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-gradient-to-b from-emerald-900/70 to-slate-900/85 text-center text-white backdrop-blur-sm">
          <Sparkles className="mb-3 h-10 w-10 text-yellow-300" />
          <h2 className="text-4xl font-black">
            {collected >= SHARD_COUNT ? "World cleared!" : "Run finished"}
          </h2>
          <p className="mt-3 text-lg text-white/85">
            You gathered{" "}
            <span className="font-bold text-yellow-300 tabular-nums">{collected}</span>{" "}
            light-shard{collected === 1 ? "" : "s"}.
          </p>
          <div className="mt-6 flex gap-3">
            <button
              onClick={resetRun}
              className="flex items-center gap-2 rounded-xl bg-sky-500 px-6 py-3 font-bold shadow-lg transition hover:bg-sky-400"
            >
              <RotateCcw className="h-5 w-5" />
              Roam again
            </button>
            {typeof onExit === "function" && (
              <button
                onClick={onExit}
                className="rounded-xl bg-white/15 px-6 py-3 font-semibold transition hover:bg-white/25"
              >
                Exit
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
