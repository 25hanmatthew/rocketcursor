// Procedural full-rocket geometry built from vehicle_model.geometry.render hints.
// No glTF: nose (cone), body (cylinder), fins (tapered plates), and — in cutaway
// mode — the propulsion package components shown translucent inside the airframe.
// Local frame: +Y is the rocket long axis, origin at the nozzle exit (z=0),
// nose tip at y = total_length. Shared by Vehicle Studio and Flight Twin.

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
  pressurant_bottle: "#9ca3af",
  engine: "#f97316",
  feed_line: "#fbbf24",
  valve: "#ef4444",
  regulator: "#a855f7",
};

function finShape(root: number, tip: number, span: number, sweep: number): THREE.Shape {
  // Trapezoid in the Y(axis)-X(span) plane; extruded along thickness.
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
        {/* shift to body surface, lay the trapezoid along +Y (axis) and +X (span) */}
        <mesh
          geometry={finGeom}
          position={[bodyR - 0.001, render.fins.position_z_m, -render.fins.thickness_m / 2]}
          castShadow
        >
          <meshStandardMaterial color="#d1d5db" metalness={0.3} roughness={0.6} side={THREE.DoubleSide} />
        </mesh>
      </group>
    );
  }

  return (
    <group>
      {/* body tube */}
      <mesh position={[0, render.body.z_bottom_m + render.body.length_m / 2, 0]} castShadow>
        <cylinderGeometry args={[bodyR, bodyR, render.body.length_m, 48, 1, true]} />
        <meshStandardMaterial
          color="#e5e7eb"
          metalness={0.4}
          roughness={0.45}
          transparent={cutaway}
          opacity={cutaway ? 0.18 : 1}
          side={THREE.DoubleSide}
        />
      </mesh>

      {/* nose cone */}
      <mesh position={[0, render.nose.z_base_m + render.nose.length_m / 2, 0]} castShadow>
        <coneGeometry args={[render.nose.base_diameter_m / 2, render.nose.length_m, 48]} />
        <meshStandardMaterial
          color="#f3f4f6"
          metalness={0.4}
          roughness={0.4}
          transparent={cutaway}
          opacity={cutaway ? 0.18 : 1}
        />
      </mesh>

      {fins}

      {/* cutaway: propulsion package inside */}
      {cutaway &&
        render.package.map((c) => {
          const r = (c.diameter_m ?? 0.04) / 2;
          const h = c.length_m ?? 0.1;
          return (
            <mesh key={c.id} position={[0, c.z_center_m, 0]}>
              <cylinderGeometry args={[r, r, h, 24]} />
              <meshStandardMaterial
                color={PACKAGE_COLORS[c.type] ?? "#6b7280"}
                metalness={0.5}
                roughness={0.4}
                emissive={PACKAGE_COLORS[c.type] ?? "#6b7280"}
                emissiveIntensity={0.15}
              />
            </mesh>
          );
        })}

      {/* CG / CP markers (rings around the axis) */}
      {showMarkers && cgZ != null && (
        <mesh position={[0, cgZ, 0]} rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[bodyR * 1.18, 0.012, 12, 40]} />
          <meshStandardMaterial color="#22c55e" emissive="#22c55e" emissiveIntensity={0.6} />
        </mesh>
      )}
      {showMarkers && cpZ != null && (
        <mesh position={[0, cpZ, 0]} rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[bodyR * 1.18, 0.012, 12, 40]} />
          <meshStandardMaterial color="#ef4444" emissive="#ef4444" emissiveIntensity={0.6} />
        </mesh>
      )}
    </group>
  );
}
