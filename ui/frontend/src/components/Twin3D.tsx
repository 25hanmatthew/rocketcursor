import { useMemo } from "react";
import { Canvas } from "@react-three/fiber";
import { ContactShadows, Environment, GizmoHelper, GizmoViewport, Grid, Lightformer, OrbitControls } from "@react-three/drei";
import { EffectComposer, SMAA } from "@react-three/postprocessing";
import * as THREE from "three";
import type { DiagramModel, SampleRow } from "../types";
import { interpolateSample, numericValue } from "../lib/telemetry";
import { buildSceneModel } from "../lib/sceneModel";
import { Tank3D } from "./twin/Tank3D";
import { Pipe3D } from "./twin/Pipe3D";
import { Valve3D } from "./twin/Valve3D";
import { Engine3D } from "./twin/Engine3D";
import { TestStand } from "./twin/TestStand";

interface Twin3DProps {
  diagram: DiagramModel | null;
  nodeSamples: Record<string, SampleRow[]>;
  connectionSamples: Record<string, SampleRow[]>;
  selectedId: string | null;
  time: number;
  phase: number;
  showPartLabels?: boolean;
  nodeStatus?: Record<string, string>;
  onSelect: (id: string) => void;
}

/* True unless `state` clearly reads closed — mirrors pidViewModel's booleanish
   handling so a valve shut in 2D is shut in 3D. */
function isOpen(value: SampleRow[string] | undefined): boolean {
  if (typeof value === "number") return value > 0;
  if (typeof value === "string") return !/^(false|0|closed)$/i.test(value.trim());
  return true;
}

export default function Twin3D({
  diagram,
  nodeSamples,
  connectionSamples,
  selectedId,
  time,
  phase,
  showPartLabels = false,
  nodeStatus,
  onSelect
}: Twin3DProps) {
  const scene = useMemo(() => buildSceneModel(diagram), [diagram]);

  if (!scene) {
    return <div className="twin-empty">Run a design loop to populate the 3D twin.</div>;
  }

  const camDist = scene.extent * 2.2;

  return (
    <Canvas
      camera={{ position: [camDist * 0.7, camDist * 0.25, camDist], fov: 42, near: 0.1, far: 200 }}
      dpr={[1, 2]}
      shadows
      gl={{ antialias: true, toneMapping: THREE.ACESFilmicToneMapping }}
      onPointerMissed={() => onSelect("")}
      style={{ width: "100%", height: "100%", background: "#070b12" }}
    >
      {/* Procedural studio lighting (Lightformers, no CDN HDRI) gives the metal
          real PBR highlights so the twin reads as hardware, not neon. */}
      <ambientLight intensity={0.3} />
      <hemisphereLight args={["#9fc0ff", "#0a0f18", 0.4]} />
      <directionalLight position={[6, 12, 8]} intensity={1.1} castShadow shadow-mapSize={[2048, 2048]} />
      <directionalLight position={[-8, 4, -6]} intensity={0.35} color="#7da7ff" />
      <Environment resolution={256} frames={1}>
        <Lightformer intensity={1.8} position={[0, 6, -5]} scale={[12, 6, 1]} color="#cfe0ff" />
        <Lightformer intensity={1.1} position={[6, 2, 3]} scale={[3, 8, 1]} color="#ffffff" />
        <Lightformer intensity={0.7} position={[-6, 1, 2]} scale={[3, 8, 1]} color="#9bb6ff" />
      </Environment>

      <Grid
        position={[0, -scene.extent, 0]}
        args={[40, 40]}
        cellColor="#1b2740"
        sectionColor="#2a3b5e"
        fadeDistance={scene.extent * 6}
        infiniteGrid
      />
      <TestStand extent={scene.extent} />

      {scene.connections.map((connection) => {
        const sample = interpolateSample(connectionSamples[connection.name], time);
        const open = isOpen(sample?.state);
        const mdot = numericValue(sample, "mdot");
        const selected = selectedId === `connection:${connection.name}`;
        return (
          <group key={connection.id}>
            <Pipe3D connection={connection} mdot={mdot} open={open} selected={selected} onSelect={onSelect} />
            {connection.valveLike && <Valve3D connection={connection} open={open} onSelect={onSelect} />}
          </group>
        );
      })}

      {scene.nodes.map((node) => {
        if (node.type === "Ambient") return null;
        const sample = interpolateSample(nodeSamples[node.name], time);
        const selected = selectedId === `node:${node.name}`;
        const status = nodeStatus?.[node.name];
        if (node.type === "Engine") {
          return (
            <Engine3D
              key={node.id}
              node={node}
              thrust={numericValue(sample, "thrust")}
              isp={numericValue(sample, "Isp")}
              chamberPressure={numericValue(sample, "P")}
              chamberTempK={numericValue(sample, "T")}
              selected={selected}
              showLabel={showPartLabels}
              onSelect={onSelect}
            />
          );
        }
        return (
          <Tank3D
            key={node.id}
            node={node}
            fillLevel={numericValue(sample, "fill_level")}
            temperatureK={numericValue(sample, "T")}
            selected={selected}
            status={status}
            showLabel={showPartLabels}
            onSelect={onSelect}
          />
        );
      })}

      <OrbitControls makeDefault enableDamping dampingFactor={0.08} />
      <GizmoHelper alignment="bottom-right" margin={[64, 64]}>
        <GizmoViewport axisColors={["#ff6b6b", "#34d399", "#4d8dff"]} labelColor="#0b1220" />
      </GizmoHelper>

      <ContactShadows position={[0, -scene.extent, 0]} scale={scene.extent * 3} blur={2.5} opacity={0.45} far={scene.extent * 2} />

      {/* No bloom in the systems view — it read as flashing neon. This is an
          engineering schematic in 3D: matte hardware lit by the environment,
          antialiased only. */}
      <EffectComposer multisampling={0}>
        <SMAA />
      </EffectComposer>
    </Canvas>
  );
}
