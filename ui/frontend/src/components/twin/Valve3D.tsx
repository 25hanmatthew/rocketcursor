import { useMemo } from "react";
import { Vector3 } from "three";
import type { SceneConnection } from "../../lib/sceneModel";

interface Valve3DProps {
  connection: SceneConnection;
  /* live telemetry at scrub time */
  open: boolean;
  onSelect: (id: string) => void;
}

/* A small marker at the midpoint of a valve-like connection (Regulator /
   BangBang / ThrottleValve). Green emissive when open, dim red when shut —
   driven straight off the solver's per-step `state`. */
export function Valve3D({ connection, open, onSelect }: Valve3DProps) {
  const mid = useMemo(
    () =>
      new Vector3(
        (connection.start.x + connection.end.x) / 2,
        (connection.start.y + connection.end.y) / 2,
        (connection.start.z + connection.end.z) / 2
      ),
    [connection.start, connection.end]
  );
  const color = open ? "#34d399" : "#9b3b44";

  return (
    <mesh
      position={[mid.x, mid.y, mid.z]}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(`connection:${connection.name}`);
      }}
    >
      <boxGeometry args={[0.13, 0.13, 0.13]} />
      <meshStandardMaterial
        color={color}
        emissive={color}
        emissiveIntensity={open ? 0.9 : 0.25}
        roughness={0.35}
        metalness={0.4}
      />
    </mesh>
  );
}
