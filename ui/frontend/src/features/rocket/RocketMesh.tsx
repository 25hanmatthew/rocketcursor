// Procedural full-rocket geometry built from vehicle_model.geometry.render hints.
// No glTF: an ogive/conical nose (lathe), painted body (cylinder), a flared engine
// nozzle bell, tapered fins, and — in cutaway mode — the propulsion package shown
// translucent inside. Local frame: +Y is the long axis, origin at the nozzle exit
// (y=0), nose tip at y = total_length. Shared by Vehicle Studio and Flight Twin.

import { useMemo } from "react";
import * as THREE from "three";

export interface RenderHints {
  nose: { kind: string; length_m: number; base_diameter_m: number; z_base_m: number };
  body: { diameter_m: number; length_m: number; z_bottom_m: number };
  fins: {
    count: number;
    root_chord_m: number;
    tip_chord_m: number;
    span_m: number;
    sweep_length_m: number;
    position_z_m: number;
    thickness_m: number;
  };
  package: Array<{ id: string; type: string; diameter_m: number | null; length_m: number | null; z_center_m: number }>;
}

const PACKAGE_COLORS: Record<string, string> = {
  propellant_tank: "#3b82f6",
  pressurant_bottle: "#cbd5e1",
  engine: "#f97316",
  feed_line: "#fbbf24",
  valve: "#ef4444",
  regulator: "#a855f7",
};

// Lathe profile (in the radius/height plane) for the nose, base at h=0 -> tip at h=L.
function noseProfile(kind: string, R: number, L: number): THREE.Vector2[] {
  const n = 28;
  const pts: THREE.Vector2[] = [];
  const conical = kind === "conical";
  const rho = (R * R + L * L) / (2 * R); // tangent-ogive radius
  for (let i = 0; i <= n; i++) {
    const h = (i / n) * L;
    let r: number;
    if (conical) {
      r = R * (1 - h / L);
    } else {
      // tangent ogive (also a good stand-in for von kármán / lvhaack at this fidelity)
      r = Math.sqrt(Math.max(rho * rho - h * h, 0)) - (rho - R);
    }
    pts.push(new THREE.Vector2(Math.max(r, 0.0009), h));
  }
  return pts;
}

// Flared engine nozzle bell, from the throat up to the exit plane at y=0.
function bellProfile(exitR: number, length: number): THREE.Vector2[] {
  const n = 16;
  const throatR = exitR * 0.42;
  const pts: THREE.Vector2[] = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n; // 0 at throat (top), 1 at exit (bottom)
    const r = throatR + (exitR - throatR) * Math.pow(t, 1.7); // bell flare
    pts.push(new THREE.Vector2(Math.max(r, 0.004), (1 - t) * length));
  }
  return pts;
}

function finShape(root: number, tip: number, span: number, sweep: number): THREE.Shape {
  const s = new THREE.Shape();
  s.moveTo(0, 0);
  s.lineTo(0, root);
  s.lineTo(span, sweep + tip);
  s.lineTo(span, sweep);
  s.lineTo(0, 0);
  return s;
}

export function RocketMesh({
  render,
  cutaway = false,
  showMarkers = false,
  cgZ,
  cpZ,
}: {
  render: RenderHints;
  cutaway?: boolean;
  showMarkers?: boolean;
  cgZ?: number;
  cpZ?: number;
}) {
  const bodyR = render.body.diameter_m / 2;

  const noseGeom = useMemo(
    () =>
      new THREE.LatheGeometry(
        noseProfile(render.nose.kind, render.nose.base_diameter_m / 2, render.nose.length_m),
        64
      ),
    [render.nose]
  );

  // engine for the nozzle bell (from the cutaway package list)
  const engine = render.package.find((c) => c.type === "engine");
  const exitR = (engine?.diameter_m ?? render.body.diameter_m * 0.5) / 2;
  const bellLen = Math.min(engine?.length_m ?? bodyR, bodyR * 2.2);
  const bellGeom = useMemo(() => new THREE.LatheGeometry(bellProfile(exitR, bellLen), 48), [exitR, bellLen]);

  const finGeom = useMemo(
    () =>
      new THREE.ExtrudeGeometry(
        finShape(render.fins.root_chord_m, render.fins.tip_chord_m, render.fins.span_m, render.fins.sweep_length_m),
        { depth: render.fins.thickness_m, bevelEnabled: false }
      ),
    [render.fins]
  );

  const fins = [];
  for (let i = 0; i < render.fins.count; i++) {
    const angle = (i / render.fins.count) * Math.PI * 2;
    fins.push(
      <group key={i} rotation={[0, angle, 0]}>
        <mesh
          geometry={finGeom}
          position={[bodyR - 0.001, render.fins.position_z_m, -render.fins.thickness_m / 2]}
          castShadow
        >
          <meshStandardMaterial color="#dc2626" metalness={0.35} roughness={0.45} side={THREE.DoubleSide} envMapIntensity={0.9} />
        </mesh>
      </group>
    );
  }

  // a painted accent band near the top of the body
  const bandH = render.body.length_m * 0.16;
  const bandY = render.body.z_bottom_m + render.body.length_m * 0.78;

  return (
    <group>
      {/* body tube */}
      <mesh position={[0, render.body.z_bottom_m + render.body.length_m / 2, 0]} castShadow receiveShadow>
        <cylinderGeometry args={[bodyR, bodyR, render.body.length_m, 64, 1, true]} />
        <meshStandardMaterial
          color="#eef2f7"
          metalness={0.85}
          roughness={0.28}
          envMapIntensity={1.1}
          transparent={cutaway}
          opacity={cutaway ? 0.16 : 1}
          side={cutaway ? THREE.DoubleSide : THREE.FrontSide}
        />
      </mesh>

      {/* accent band */}
      {!cutaway && (
        <mesh position={[0, bandY, 0]}>
          <cylinderGeometry args={[bodyR * 1.002, bodyR * 1.002, bandH, 64, 1, true]} />
          <meshStandardMaterial color="#1d4ed8" metalness={0.5} roughness={0.4} envMapIntensity={0.9} side={THREE.FrontSide} />
        </mesh>
      )}

      {/* nose cone (ogive lathe) */}
      <mesh geometry={noseGeom} position={[0, render.nose.z_base_m, 0]} castShadow>
        <meshStandardMaterial
          color="#f8fafc"
          metalness={0.9}
          roughness={0.2}
          envMapIntensity={1.2}
          transparent={cutaway}
          opacity={cutaway ? 0.16 : 1}
        />
      </mesh>

      {/* engine nozzle bell */}
      <mesh geometry={bellGeom} position={[0, 0, 0]} castShadow>
        <meshStandardMaterial color="#3f2a1d" metalness={1} roughness={0.35} envMapIntensity={1.3} side={THREE.DoubleSide} />
      </mesh>

      {fins}

      {/* cutaway: propulsion package inside */}
      {cutaway &&
        render.package.map((c) => {
          const r = (c.diameter_m ?? 0.04) / 2;
          const h = c.length_m ?? 0.1;
          const col = PACKAGE_COLORS[c.type] ?? "#6b7280";
          return (
            <mesh key={c.id} position={[0, c.z_center_m, 0]} castShadow>
              <cylinderGeometry args={[r, r, h, 32]} />
              <meshStandardMaterial color={col} metalness={0.6} roughness={0.35} emissive={col} emissiveIntensity={0.25} envMapIntensity={0.8} />
            </mesh>
          );
        })}

      {/* CG / CP markers (rings around the axis) */}
      {showMarkers && cgZ != null && (
        <mesh position={[0, cgZ, 0]} rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[bodyR * 1.25, 0.014, 16, 48]} />
          <meshStandardMaterial color="#22c55e" emissive="#22c55e" emissiveIntensity={1.4} toneMapped={false} />
        </mesh>
      )}
      {showMarkers && cpZ != null && (
        <mesh position={[0, cpZ, 0]} rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[bodyR * 1.25, 0.014, 16, 48]} />
          <meshStandardMaterial color="#ef4444" emissive="#ef4444" emissiveIntensity={1.4} toneMapped={false} />
        </mesh>
      )}
    </group>
  );
}
