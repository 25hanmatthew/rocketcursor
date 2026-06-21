import { useMemo } from "react";
import type { SceneConnection } from "../../lib/sceneModel";
import { colorForVisualFluid } from "../../lib/pidViewModel";
import { segmentTransform } from "../../lib/sceneGeometry";

interface Pipe3DProps {
  connection: SceneConnection;
  /* live telemetry at scrub time */
  mdot: number | undefined;
  open: boolean;
  selected: boolean;
  onSelect: (id: string) => void;
}

/* Normalise mass flow into a 0..1 glow. Feed-line mdot sits ~0.01–1 kg/s; a
   log-ish map keeps small flows visible without blowing out big ones. */
function flowGlow(mdot: number): number {
  const m = Math.abs(mdot);
  if (m <= 1e-6) return 0;
  return Math.max(0.12, Math.min(1, Math.log10(m * 1000 + 1) / 3));
}

/* Hardware-first feed line: an always-visible brushed-metal pipe, with a thin
   fluid-coloured inner core that lights up with |mdot|. The pipe reads as a real
   line first and telemetry second — not a neon tube. (Directional in-pipe flow
   will become a UV-scroll on the inner core next, not a particle system.) */
export function Pipe3D({ connection, mdot, open, selected, onSelect }: Pipe3DProps) {
  const { mid, quaternion, length } = useMemo(
    () => segmentTransform(connection.start, connection.end),
    [connection.start, connection.end]
  );
  const color = colorForVisualFluid(connection.fluid);
  const flow = open ? flowGlow(mdot ?? 0) : 0;
  const outerRadius = selected ? 0.05 : 0.042;

  return (
    <group
      position={[mid.x, mid.y, mid.z]}
      quaternion={quaternion}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(`connection:${connection.name}`);
      }}
    >
      {/* Physical pipe — brushed metal, always present. */}
      <mesh>
        <cylinderGeometry args={[outerRadius, outerRadius, length, 16]} />
        <meshStandardMaterial
          color={selected ? "#9fb6d6" : "#7c8aa0"}
          metalness={0.85}
          roughness={0.35}
        />
      </mesh>

      {/* Fluid core — sits just inside the pipe, glows with flow. */}
      <mesh>
        <cylinderGeometry args={[outerRadius * 0.55, outerRadius * 0.55, length * 1.001, 12]} />
        <meshStandardMaterial
          color={open ? color : "#3b4452"}
          emissive={color}
          emissiveIntensity={selected ? Math.max(0.35, flow) : flow * 0.85}
          roughness={0.4}
          metalness={0.2}
        />
      </mesh>
    </group>
  );
}
