import { useMemo } from "react";

interface TestStandProps {
  /* bounding radius of the centred model, from sceneModel */
  extent: number;
}

/* A faint structural frame — base platform + corner struts + cross rings — so
   the propulsion stack reads as mounted on a test stand instead of floating in
   space. Deliberately dark/low-contrast: it frames, it doesn't compete with the
   live components. */
export function TestStand({ extent }: TestStandProps) {
  const frame = useMemo(() => {
    const half = extent * 0.78;
    const top = extent * 0.95;
    const bottom = -extent * 1.05;
    const height = top - bottom;
    const midY = (top + bottom) / 2;
    const corners: [number, number][] = [
      [half, half],
      [half, -half],
      [-half, half],
      [-half, -half]
    ];
    return { half, top, bottom, height, midY, corners };
  }, [extent]);

  return (
    <group>
      {/* Base platform under the engine. */}
      <mesh position={[0, frame.bottom, 0]} rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[frame.half * 1.25, frame.half * 1.25, 0.06, 6]} />
        <meshStandardMaterial color="#161d2a" metalness={0.6} roughness={0.7} />
      </mesh>

      {/* Corner struts. */}
      {frame.corners.map(([x, z], i) => (
        <mesh key={i} position={[x, frame.midY, z]}>
          <boxGeometry args={[0.06, frame.height, 0.06]} />
          <meshStandardMaterial color="#28344a" metalness={0.7} roughness={0.5} />
        </mesh>
      ))}

      {/* Cross rings top and bottom to tie the struts together. */}
      {[frame.top, frame.bottom + frame.height * 0.5].map((y, i) => (
        <mesh key={i} position={[0, y, 0]} rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[frame.half * 1.12, 0.02, 8, 4]} />
          <meshStandardMaterial color="#28344a" metalness={0.7} roughness={0.5} />
        </mesh>
      ))}
    </group>
  );
}
