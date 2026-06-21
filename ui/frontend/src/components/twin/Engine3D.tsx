import { Html } from "@react-three/drei";
import { DoubleSide } from "three";
import type { SceneNode } from "../../lib/sceneModel";
import { Plume } from "./Plume";

interface Engine3DProps {
  node: SceneNode;
  /* live telemetry at scrub time */
  thrust: number | undefined;
  isp: number | undefined;
  chamberPressure: number | undefined;
  chamberTempK: number | undefined;
  selected: boolean;
  showLabel: boolean;
  onSelect: (id: string) => void;
}

/* Hardware-first engine: injector dome + combustion chamber + flared nozzle
   bell, then a telemetry-driven particle Plume out the throat. Reads as a test
   article, not an icon. */
export function Engine3D({
  node,
  thrust,
  isp,
  chamberPressure,
  chamberTempK,
  selected,
  showLabel,
  onSelect
}: Engine3DProps) {
  const firing = (thrust ?? 0) > 1;
  const r = node.radius;
  const metal = selected ? "#5aa6ff" : "#aeb9c8";

  return (
    <group
      position={[node.position.x, node.position.y, node.position.z]}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(`node:${node.name}`);
      }}
    >
      {/* Injector dome on top. */}
      <mesh position={[0, r * 0.95, 0]}>
        <sphereGeometry args={[r * 0.78, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2]} />
        <meshStandardMaterial color={metal} metalness={0.85} roughness={0.3} />
      </mesh>

      {/* Combustion chamber (short barrel). */}
      <mesh position={[0, r * 0.4, 0]}>
        <cylinderGeometry args={[r * 0.78, r * 0.62, r * 1.1, 28]} />
        <meshStandardMaterial color={metal} metalness={0.85} roughness={0.32} />
      </mesh>

      {/* Throat → flared nozzle bell (open, double-sided so the inside reads). */}
      <mesh position={[0, -r * 0.55, 0]}>
        <cylinderGeometry args={[r, r * 0.42, r * 1.0, 32, 1, true]} />
        <meshStandardMaterial
          color={metal}
          metalness={0.9}
          roughness={0.28}
          side={DoubleSide}
          emissive={firing ? "#ff5a1e" : "#000000"}
          emissiveIntensity={firing ? 0.35 : 0}
        />
      </mesh>

      {/* Glowing throat ring when firing — gives Bloom something to grab. */}
      {firing && (
        <mesh position={[0, -r * 1.05, 0]} rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[r * 0.42, 0.03, 12, 32]} />
          <meshStandardMaterial color="#fff1c0" emissive="#ffb060" emissiveIntensity={2.2} />
        </mesh>
      )}

      {/* Particle plume out the bell mouth. */}
      {firing && (
        <group position={[0, -r * 1.05, 0]}>
          <Plume thrust={thrust} isp={isp} chamberPressure={chamberPressure} chamberTempK={chamberTempK} exitRadius={r} />
        </group>
      )}

      {selected && (
        <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, r * 1.1, 0]}>
          <torusGeometry args={[r * 1.1, 0.02, 12, 40]} />
          <meshStandardMaterial color="#3b9dff" emissive="#3b9dff" emissiveIntensity={1.2} />
        </mesh>
      )}

      {showLabel && (
        <Html position={[r + 0.3, r * 0.4, 0]} center distanceFactor={8} pointerEvents="none">
          <div
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11,
              color: "#ffd9c2",
              background: "rgba(8,14,24,0.72)",
              padding: "2px 6px",
              borderRadius: 4,
              whiteSpace: "nowrap",
              border: "1px solid #ff784955"
            }}
          >
            {node.name}
            {thrust !== undefined ? ` · ${thrust.toFixed(0)} N` : ""}
          </div>
        </Html>
      )}
    </group>
  );
}
