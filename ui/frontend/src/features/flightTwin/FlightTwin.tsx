// Flight Twin — the full rocket flying its true 6DOF trajectory from flight.csv
// against a real sky: atmospheric Sky, fixed ground at launch level, volumetric
// clouds, a glowing trajectory arc, and a thrust-tracking exhaust plume. The
// rocket sits at its real world position (it never goes below the ground); a
// follow camera tracks it so it stays framed while you can still orbit.
// RocketPy world (x downrange, y crossrange, z up) -> three.js (x, z-up, -y).

import { useMemo, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import {
  Environment,
  Lightformer,
  Line,
  OrbitControls,
  Sparkles,
  Stars,
  Sky,
} from "@react-three/drei";
import { Bloom, EffectComposer, SMAA, Vignette } from "@react-three/postprocessing";
import * as THREE from "three";
import { RocketMesh, RenderHints } from "../rocket/RocketMesh";
import { FlightRow, FlightEvents, interpolateFlight } from "../../lib/flightModel";

const UP = new THREE.Vector3(0, 1, 0);

function toWorld(x: number, y: number, z: number, scale: number): THREE.Vector3 {
  return new THREE.Vector3(x * scale, z * scale, -y * scale);
}

function eventLabel(t: number, events: FlightEvents): string {
  const order: Array<[keyof FlightEvents, string]> = [
    ["ignition", "Ignition"],
    ["rail_departure", "Rail clear"],
    ["maximum_dynamic_pressure", "Max-Q"],
    ["burnout", "Burnout"],
    ["apogee", "Apogee"],
    ["parachute_deployment", "Chute"],
    ["landing", "Landing"],
  ];
  let label = "Coast";
  for (const [key, name] of order) {
    const et = events[key];
    if (et != null && t >= et - 0.05) label = name;
  }
  return label;
}

// Soft radial sprite used to build billboard cumulus (renders on any GPU, unlike
// volumetric clouds which can blank a software/headless WebGL context).
function softCloudTexture(): THREE.Texture {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const ctx = c.getContext("2d")!;
  const g = ctx.createRadialGradient(64, 64, 4, 64, 64, 64);
  g.addColorStop(0, "rgba(255,255,255,0.95)");
  g.addColorStop(0.45, "rgba(247,250,255,0.55)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(64, 64, 64, 0, Math.PI * 2);
  ctx.fill();
  return new THREE.CanvasTexture(c);
}

// Cumulus clouds: each cloud is a cluster of overlapping soft puffs, so they read
// as fluffy volumes rather than flat discs.
function CloudField({ skyTop }: { skyTop: number }) {
  const tex = useMemo(softCloudTexture, []);
  const clouds = useMemo(() => {
    const centers: [number, number, number][] = [
      [0.5, 0.22, -0.3],
      [0.9, 0.34, -0.55],
      [-0.8, 0.18, 0.4],
      [0.4, 0.42, 0.7],
      [-0.5, 0.5, -0.6],
      [-1.1, 0.28, -0.2],
    ];
    return centers.map((c) => {
      const n = 9 + Math.floor(Math.random() * 4);
      const puffs: Array<{ pos: [number, number, number]; s: number }> = [];
      for (let i = 0; i < n; i++) {
        const a = Math.random() * Math.PI * 2;
        const rad = Math.random();
        puffs.push({
          pos: [Math.cos(a) * rad * skyTop * 0.18, (Math.random() - 0.35) * skyTop * 0.07, Math.sin(a) * rad * skyTop * 0.18],
          s: skyTop * (0.12 + Math.random() * 0.16) * (1 - rad * 0.35),
        });
      }
      return { center: [c[0] * skyTop, c[1] * skyTop, c[2] * skyTop] as [number, number, number], puffs };
    });
  }, [skyTop]);
  return (
    <group>
      {clouds.map((cloud, ci) => (
        <group key={ci} position={cloud.center}>
          {cloud.puffs.map((p, pi) => (
            <sprite key={pi} position={p.pos} scale={[p.s, p.s * 0.72, 1]}>
              <spriteMaterial map={tex} transparent opacity={0.5} depthWrite={false} />
            </sprite>
          ))}
        </group>
      ))}
    </group>
  );
}

// Follow camera: translate the camera by the same delta the rocket moves, so it
// stays framed at whatever orbit offset the user picked while the rocket flies
// its real arc. Pure framing — no effect on the physics.
function FollowCam({ target }: { target: THREE.Vector3 }) {
  const controls = useRef<any>(null);
  const prev = useRef(target.clone());
  useFrame(({ camera }) => {
    const d = target.clone().sub(prev.current);
    if (d.lengthSq() > 0) camera.position.add(d);
    if (controls.current) {
      controls.current.target.copy(target);
      controls.current.update();
    }
    prev.current.copy(target);
  });
  return <OrbitControls ref={controls} makeDefault enableDamping minDistance={4} maxDistance={140} />;
}

// Flickering exhaust plume + light, sized by thrust (0..1).
function Plume({ intensity }: { intensity: number }) {
  const flame = useRef<THREE.Mesh>(null);
  const light = useRef<THREE.PointLight>(null);
  useFrame((state) => {
    const f = 0.85 + 0.15 * Math.sin(state.clock.elapsedTime * 40);
    if (flame.current) flame.current.scale.set(f, 1, f);
    if (light.current) light.current.intensity = 6 * intensity * f;
  });
  if (intensity <= 0.01) return null;
  const len = 1.6 + 3.6 * intensity;
  return (
    <group position={[0, -len * 0.5, 0]}>
      <mesh ref={flame} rotation={[Math.PI, 0, 0]}>
        <coneGeometry args={[0.32 + 0.25 * intensity, len, 24, 1, true]} />
        <meshBasicMaterial color="#ffd27a" transparent opacity={0.9} blending={THREE.AdditiveBlending} toneMapped={false} side={THREE.DoubleSide} />
      </mesh>
      <mesh rotation={[Math.PI, 0, 0]} scale={[0.55, 0.7, 0.55]}>
        <coneGeometry args={[0.28, len, 20, 1, true]} />
        <meshBasicMaterial color="#7dd3ff" transparent opacity={0.85} blending={THREE.AdditiveBlending} toneMapped={false} side={THREE.DoubleSide} />
      </mesh>
      <Sparkles count={26} scale={[0.6, len, 0.6]} position={[0, -len * 0.4, 0]} size={3} speed={2} color="#ffcf8a" />
      <pointLight ref={light} color="#ffb454" distance={6} />
    </group>
  );
}

export default function FlightTwin({
  rows,
  events,
  render,
  totalLength,
  time,
}: {
  rows: FlightRow[];
  events: FlightEvents;
  render: RenderHints;
  totalLength: number;
  time: number;
}) {
  const apogee = useMemo(() => Math.max(1, ...rows.map((r) => r.altitude - rows[0].altitude)), [rows]);
  const scale = 26 / apogee; // maps real apogee -> 26 world units
  const base = rows.length ? rows[0].altitude : 0;

  const sample = interpolateFlight(rows, time);
  const pos = sample ? toWorld(sample.position_x, sample.position_y, sample.altitude - base, scale) : new THREE.Vector3();

  const quat = useMemo(() => {
    const q = new THREE.Quaternion();
    if (!sample) return q;
    const v = toWorld(sample.velocity_x, sample.velocity_y, sample.velocity_z, 1);
    if (v.lengthSq() < 1e-4) return q;
    q.setFromUnitVectors(UP, v.normalize());
    return q;
  }, [sample]);

  // glowing trajectory arc up to the current time, colored by climb.
  const { trail, trailColors } = useMemo(() => {
    const pts: [number, number, number][] = [];
    const cols: THREE.Color[] = [];
    const cool = new THREE.Color("#38bdf8");
    const hot = new THREE.Color("#f97316");
    for (const r of rows) {
      if (r.time > time) break;
      const p = toWorld(r.position_x, r.position_y, r.altitude - base, scale);
      pts.push([p.x, p.y, p.z]);
      cols.push(cool.clone().lerp(hot, Math.min((r.altitude - base) / apogee, 1)));
    }
    return { trail: pts.length > 1 ? pts : null, trailColors: cols.length > 1 ? cols : undefined };
  }, [rows, time, base, scale, apogee]);

  const visScale = 9 / totalLength; // rocket ~9 world units, prominent in frame
  const thrust01 = sample ? Math.min(Math.max(sample.thrust / 4000, 0), 1) : 0;
  const skyTop = 26;
  const groundExtent = skyTop * 30;

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <Canvas
        shadows
        dpr={[1, 2]}
        gl={{ antialias: true, toneMapping: THREE.ACESFilmicToneMapping }}
        camera={{ position: [8, 2.5, 11], fov: 48 }}
      >
        <Sky distance={450000} sunPosition={[80, 50, -40]} turbidity={5} rayleigh={1.6} mieCoefficient={0.005} mieDirectionalG={0.85} />
        <Stars radius={400} depth={80} count={1800} factor={6} saturation={0} fade speed={0.4} />
        <fog attach="fog" args={["#bcd3ec", 60, 320]} />

        <ambientLight intensity={0.5} />
        <hemisphereLight args={["#dcebff", "#56713f", 0.8]} />
        <directionalLight position={[80, 100, -40]} intensity={2.4} castShadow shadow-mapSize={[2048, 2048]} />
        <Environment resolution={128} frames={1}>
          <Lightformer intensity={2.2} position={[0, 8, -8]} scale={[16, 10, 1]} color="#cfe2ff" />
          <Lightformer intensity={0.9} position={[0, -8, 6]} scale={[16, 8, 1]} color="#6f8c52" />
        </Environment>

        {/* fixed ground at launch level (y=0) — the rocket always flies above it */}
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]} receiveShadow>
          <planeGeometry args={[groundExtent, groundExtent]} />
          <meshStandardMaterial color="#6f8c52" roughness={1} metalness={0} />
        </mesh>
        <gridHelper args={[groundExtent, 120, "#4f6a3c", "#5b774a"]} position={[0, 0.02, 0]} />

        {/* cumulus clouds at mid altitude */}
        <CloudField skyTop={skyTop} />

        {trail && <Line points={trail} vertexColors={trailColors} lineWidth={3} transparent opacity={0.95} />}

        {/* rocket at its true world position (nozzle anchored on the trajectory,
            so it sits on the pad at launch and never clips below the ground) */}
        <group position={pos} quaternion={quat}>
          <group scale={visScale}>
            <RocketMesh render={render} />
            <Plume intensity={thrust01} />
          </group>
        </group>

        <FollowCam target={new THREE.Vector3(pos.x, pos.y + 4, pos.z)} />

        <EffectComposer multisampling={0}>
          <Bloom intensity={0.85} luminanceThreshold={0.65} luminanceSmoothing={0.25} mipmapBlur />
          <SMAA />
          <Vignette eskil={false} offset={0.18} darkness={0.55} />
        </EffectComposer>
      </Canvas>

      {sample && (
        <div className="flight-hud">
          <div className="flight-hud__phase">{eventLabel(time, events)}</div>
          <dl>
            <div><dt>Altitude</dt><dd>{(sample.altitude - base).toFixed(0)} m</dd></div>
            <div><dt>Velocity</dt><dd>{Math.hypot(sample.velocity_x, sample.velocity_y, sample.velocity_z).toFixed(0)} m/s</dd></div>
            <div><dt>Mach</dt><dd>{sample.mach.toFixed(2)}</dd></div>
            <div><dt>Dyn. pressure</dt><dd>{(sample.dynamic_pressure / 1000).toFixed(1)} kPa</dd></div>
            <div><dt>AoA</dt><dd>{sample.angle_of_attack.toFixed(1)}°</dd></div>
            <div><dt>Thrust</dt><dd>{(sample.thrust / 1000).toFixed(2)} kN</dd></div>
            <div><dt>Mass</dt><dd>{sample.mass.toFixed(1)} kg</dd></div>
          </dl>
        </div>
      )}
    </div>
  );
}
