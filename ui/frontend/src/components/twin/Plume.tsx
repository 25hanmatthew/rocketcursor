import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { AdditiveBlending, BufferGeometry, CanvasTexture, Color, Float32BufferAttribute, Points } from "three";

interface PlumeProps {
  /* live telemetry — drives the particle field */
  thrust: number | undefined;
  isp: number | undefined;
  chamberPressure: number | undefined;
  chamberTempK: number | undefined;
  /* nozzle exit radius (world units); particles seed here and travel -Y */
  exitRadius: number;
}

const COUNT = 320;
const G0 = 9.80665;

/* Core/edge colours from chamber temperature: cooler → orange, hotter → blue-white. */
function plumeColors(tempK: number | undefined): { core: Color; edge: Color } {
  if (tempK !== undefined && tempK > 3400) return { core: new Color("#dce8ff"), edge: new Color("#5b7bff") };
  if (tempK !== undefined && tempK > 3000) return { core: new Color("#fff3d6"), edge: new Color("#ff9a3c") };
  return { core: new Color("#fff0d0"), edge: new Color("#ff6a2a") };
}

/* A CPU-integrated Points plume: a tight bright core near the throat that
   expands and cools into a softer exhaust cone. Spawn rate and exhaust speed
   track thrust/Isp; brightness tracks chamber pressure. Additive blending +
   Bloom (in Twin3D) do the glow. This is the "particle plume" upgrade over the
   old flashlight cone; three.quarks can later swap in for richer turbulence. */
export function Plume({ thrust, isp, chamberPressure, chamberTempK, exitRadius }: PlumeProps) {
  const pointsRef = useRef<Points>(null);
  const state = useMemo(
    () => ({
      positions: new Float32Array(COUNT * 3),
      colors: new Float32Array(COUNT * 3),
      vel: new Float32Array(COUNT * 3),
      age: new Float32Array(COUNT).fill(Infinity),
      life: new Float32Array(COUNT).fill(1),
      cursor: 0,
      spawnAcc: 0
    }),
    []
  );

  const sprite = useMemo(() => {
    const size = 64;
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = size;
    const ctx = canvas.getContext("2d")!;
    const grad = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    grad.addColorStop(0, "rgba(255,255,255,1)");
    grad.addColorStop(0.35, "rgba(255,255,255,0.55)");
    grad.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, size, size);
    return new CanvasTexture(canvas);
  }, []);

  const geometry = useMemo(() => {
    const geom = new BufferGeometry();
    geom.setAttribute("position", new Float32BufferAttribute(state.positions, 3));
    geom.setAttribute("color", new Float32BufferAttribute(state.colors, 3));
    return geom;
  }, [state]);

  useFrame((_, rawDelta) => {
    const delta = Math.min(rawDelta, 0.05); // guard against tab-restore jumps
    const t = Math.max(0, thrust ?? 0);
    const drive = Math.min(1, t / 2500);
    // Exhaust speed scales with Isp (real exit velocity ~ Isp * g0), mapped down
    // into a pleasant world-space rate; falls back to thrust if Isp absent.
    const exitSpeed = ((isp ?? 220) * G0) / 900 * (0.6 + 0.4 * drive);
    const lifetime = 0.45 + drive * 0.5;
    const pc = chamberPressure ?? 0;
    const brightness = 0.5 + Math.min(1, pc / 2_000_000) * 1.3;
    const { core, edge } = plumeColors(chamberTempK);

    // Spawn proportional to thrust.
    if (drive > 0) {
      state.spawnAcc += drive * 520 * delta;
      while (state.spawnAcc >= 1) {
        state.spawnAcc -= 1;
        const i = state.cursor;
        state.cursor = (state.cursor + 1) % COUNT;
        const a = Math.random() * Math.PI * 2;
        const r = Math.random() * exitRadius * 0.7;
        state.positions[i * 3] = Math.cos(a) * r;
        state.positions[i * 3 + 1] = 0;
        state.positions[i * 3 + 2] = Math.sin(a) * r;
        // Mostly axial (-Y), small radial spread that widens the cone downstream.
        state.vel[i * 3] = Math.cos(a) * exitSpeed * 0.08;
        state.vel[i * 3 + 1] = -exitSpeed * (0.85 + Math.random() * 0.3);
        state.vel[i * 3 + 2] = Math.sin(a) * exitSpeed * 0.08;
        state.age[i] = 0;
        state.life[i] = lifetime * (0.7 + Math.random() * 0.6);
      }
    }

    for (let i = 0; i < COUNT; i += 1) {
      const age = state.age[i];
      if (!Number.isFinite(age) || age >= state.life[i]) {
        // Dead → invisible (additive: zero colour contributes nothing).
        state.colors[i * 3] = 0;
        state.colors[i * 3 + 1] = 0;
        state.colors[i * 3 + 2] = 0;
        continue;
      }
      const frac = age / state.life[i];
      // Radial outward drift grows over life → expanding exhaust.
      state.vel[i * 3] *= 1 + delta * 1.5;
      state.vel[i * 3 + 2] *= 1 + delta * 1.5;
      state.positions[i * 3] += state.vel[i * 3] * delta;
      state.positions[i * 3 + 1] += state.vel[i * 3 + 1] * delta;
      state.positions[i * 3 + 2] += state.vel[i * 3 + 2] * delta;
      state.age[i] = age + delta;

      // Core → edge colour as it cools, fade alpha (encoded into additive rgb).
      const alpha = (1 - frac) * brightness;
      const rr = core.r + (edge.r - core.r) * frac;
      const gg = core.g + (edge.g - core.g) * frac;
      const bb = core.b + (edge.b - core.b) * frac;
      state.colors[i * 3] = rr * alpha;
      state.colors[i * 3 + 1] = gg * alpha;
      state.colors[i * 3 + 2] = bb * alpha;
    }

    const geom = pointsRef.current?.geometry;
    if (geom) {
      (geom.getAttribute("position") as Float32BufferAttribute).needsUpdate = true;
      (geom.getAttribute("color") as Float32BufferAttribute).needsUpdate = true;
    }
  });

  return (
    <points ref={pointsRef} geometry={geometry}>
      <pointsMaterial
        map={sprite}
        size={exitRadius * 1.1}
        sizeAttenuation
        vertexColors
        transparent
        depthWrite={false}
        blending={AdditiveBlending}
      />
    </points>
  );
}
