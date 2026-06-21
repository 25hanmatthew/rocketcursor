import { useMemo } from "react";
import { segmentTransform } from "../../lib/sceneGeometry";
import type { SceneConnection } from "../../lib/sceneModel";

interface Valve3DProps {
  connection: SceneConnection;
  /* live telemetry at scrub time */
  open: boolean;
  onSelect: (id: string) => void;
}

/* A recognizable control valve / regulator on a valve-like connection
   (Regulator / BangBang / ThrottleValve) — the P&ID "gates" as real 3D hardware:
   a metal body with two pipe flanges along the flow axis and a bonnet + handwheel
   actuator perpendicular to it. The handwheel reads green when the solver's
   per-step `state` is open, red when shut. Matte materials, no bloom — physical,
   not neon. Oriented along the pipe so the flanges meet the line. */
export function Valve3D({ connection, open, onSelect }: Valve3DProps) {
  const { mid, quaternion } = useMemo(
    () => segmentTransform(connection.start, connection.end),
    [connection.start, connection.end]
  );
  const stateColor = open ? "#3fae6a" : "#b0453f";
  const bodyMetal = "#8a96a8";

  return (
    <group
      position={[mid.x, mid.y, mid.z]}
      quaternion={quaternion}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(`connection:${connection.name}`);
      }}
    >
      {/* valve body (flow axis is local +Y) */}
      <mesh>
        <sphereGeometry args={[0.08, 24, 18]} />
        <meshStandardMaterial color={bodyMetal} metalness={0.85} roughness={0.34} />
      </mesh>

      {/* pipe flanges either side, along the flow axis */}
      {[-1, 1].map((s) => (
        <mesh key={s} position={[0, s * 0.085, 0]}>
          <cylinderGeometry args={[0.055, 0.055, 0.03, 20]} />
          <meshStandardMaterial color="#6f7c8e" metalness={0.8} roughness={0.42} />
        </mesh>
      ))}

      {/* bonnet + stem rising perpendicular to the flow (local +X) */}
      <mesh position={[0.085, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
        <cylinderGeometry args={[0.026, 0.032, 0.07, 16]} />
        <meshStandardMaterial color="#9aa6b6" metalness={0.85} roughness={0.34} />
      </mesh>
      <mesh position={[0.155, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
        <cylinderGeometry args={[0.012, 0.012, 0.1, 12]} />
        <meshStandardMaterial color="#c4ccd8" metalness={0.9} roughness={0.3} />
      </mesh>

      {/* handwheel actuator — the open/closed state indicator */}
      <group position={[0.2, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
        <mesh rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[0.055, 0.013, 12, 32]} />
          <meshStandardMaterial color={stateColor} emissive={stateColor} emissiveIntensity={0.22} metalness={0.3} roughness={0.5} />
        </mesh>
        {[0, Math.PI / 2].map((a, i) => (
          <mesh key={i} rotation={[0, a, 0]}>
            <boxGeometry args={[0.108, 0.008, 0.008]} />
            <meshStandardMaterial color={stateColor} metalness={0.3} roughness={0.55} />
          </mesh>
        ))}
      </group>
    </group>
  );
}
