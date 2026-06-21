import { useMemo } from "react";
import { Html } from "@react-three/drei";
import { DoubleSide } from "three";
import type { SceneNode } from "../../lib/sceneModel";
import { colorForVisualFluid } from "../../lib/pidViewModel";

interface Tank3DProps {
  node: SceneNode;
  /* live telemetry at scrub time */
  fillLevel: number | undefined;
  temperatureK: number | undefined;
  selected: boolean;
  status?: string;
  showLabel: boolean;
  onSelect: (id: string) => void;
}

const STATUS_EMISSIVE: Record<string, string> = {
  red: "#ef4444",
  yellow: "#f59e0b"
};

/* A cutaway pressure vessel: transparent shell, a liquid column whose height is
   fill_level, a bright surface line at the interface, and a faint gas-tinted
   ullage above it (which fills the whole vessel for a gas bottle, fill≈0). Cryo
   contents frost the shell. Mounting bands make it read as installed hardware,
   not a floating capsule. Pure skin over the solver's fill_level / T. */
export function Tank3D({ node, fillLevel, temperatureK, selected, status, showLabel, onSelect }: Tank3DProps) {
  const fluidColor = colorForVisualFluid(node.fluid);
  const cryo = temperatureK !== undefined && temperatureK < 150;
  const fill = Math.max(0, Math.min(1, fillLevel ?? 0));
  const statusEmissive = status ? STATUS_EMISSIVE[status] : undefined;
  const r = node.radius;
  const h = node.height;

  const liquid = useMemo(() => {
    const height = Math.max(0.0001, h * fill);
    const y = -h / 2 + height / 2;
    const surfaceY = -h / 2 + height; // top of the liquid = interface line
    const ullageHeight = Math.max(0.0001, h - height);
    const ullageY = surfaceY + ullageHeight / 2;
    return { height, y, surfaceY, ullageHeight, ullageY };
  }, [h, fill]);

  return (
    <group
      position={[node.position.x, node.position.y, node.position.z]}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(`node:${node.name}`);
      }}
    >
      {/* Outer shell — see-through so the cutaway reads. */}
      <mesh>
        <cylinderGeometry args={[r, r, h, 32, 1, true]} />
        <meshStandardMaterial
          color={cryo ? "#cfe8f0" : "#9fb2c8"}
          transparent
          opacity={selected ? 0.22 : 0.12}
          roughness={cryo ? 0.25 : 0.5}
          metalness={0.15}
          side={DoubleSide}
          emissive={statusEmissive ?? "#000000"}
          emissiveIntensity={statusEmissive ? 0.6 : 0}
        />
      </mesh>

      {/* Domed caps. */}
      <mesh position={[0, h / 2, 0]}>
        <sphereGeometry args={[r, 28, 14, 0, Math.PI * 2, 0, Math.PI / 2]} />
        <meshStandardMaterial color="#9fb2c8" transparent opacity={0.16} metalness={0.25} roughness={0.4} side={DoubleSide} />
      </mesh>
      <mesh position={[0, -h / 2, 0]} rotation={[Math.PI, 0, 0]}>
        <sphereGeometry args={[r, 28, 14, 0, Math.PI * 2, 0, Math.PI / 2]} />
        <meshStandardMaterial color="#9fb2c8" transparent opacity={0.16} metalness={0.25} roughness={0.4} side={DoubleSide} />
      </mesh>

      {/* Ullage gas: faint fluid-tinted haze above the liquid. */}
      {liquid.ullageHeight > 0.01 && (
        <mesh position={[0, liquid.ullageY, 0]}>
          <cylinderGeometry args={[r * 0.9, r * 0.9, liquid.ullageHeight, 24]} />
          <meshStandardMaterial color={fluidColor} transparent opacity={0.06} depthWrite={false} />
        </mesh>
      )}

      {/* Liquid column — height = fill_level. */}
      {fill > 0.001 && (
        <mesh position={[0, liquid.y, 0]}>
          <cylinderGeometry args={[r * 0.92, r * 0.92, liquid.height, 32]} />
          <meshStandardMaterial
            color={fluidColor}
            emissive={fluidColor}
            emissiveIntensity={selected ? 0.45 : 0.26}
            roughness={0.25}
            metalness={0.0}
            transparent
            opacity={0.9}
          />
        </mesh>
      )}

      {/* Bright liquid surface line at the interface. */}
      {fill > 0.001 && fill < 0.999 && (
        <mesh position={[0, liquid.surfaceY, 0]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[r * 0.93, r * 0.93, 0.012, 32, 1, true]} />
          <meshStandardMaterial color="#ffffff" emissive={fluidColor} emissiveIntensity={1.4} side={DoubleSide} />
        </mesh>
      )}

      {/* Mounting bands → installed hardware, not floating. */}
      {[h * 0.28, -h * 0.28].map((bandY, i) => (
        <mesh key={i} position={[0, bandY, 0]} rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[r * 1.02, 0.022, 10, 36]} />
          <meshStandardMaterial color="#76849a" metalness={0.8} roughness={0.4} />
        </mesh>
      ))}

      {/* Selection ring. */}
      {selected && (
        <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, -h / 2 - 0.05, 0]}>
          <torusGeometry args={[r * 1.2, 0.02, 12, 40]} />
          <meshStandardMaterial color="#3b9dff" emissive="#3b9dff" emissiveIntensity={1.2} />
        </mesh>
      )}

      {showLabel && (
        <Html position={[0, h / 2 + 0.3, 0]} center distanceFactor={8} pointerEvents="none">
          <div
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11,
              color: "#dce6f5",
              background: "rgba(8,14,24,0.72)",
              padding: "2px 6px",
              borderRadius: 4,
              whiteSpace: "nowrap",
              border: `1px solid ${fluidColor}55`
            }}
          >
            {node.name}
          </div>
        </Html>
      )}
    </group>
  );
}
