// Vehicle Studio — the complete generated rocket on a studio stage: reflective
// floor, procedural studio lighting (Lightformers, no network HDRI), contact
// shadows and subtle bloom. Cutaway reveals the propulsion package; CG/CP markers
// and stability come straight from vehicle_model.json. Renderer only.

import { useState } from "react";
import { Canvas } from "@react-three/fiber";
import {
  ContactShadows,
  Environment,
  Grid,
  Lightformer,
  MeshReflectorMaterial,
  OrbitControls,
} from "@react-three/drei";
import { Bloom, EffectComposer, SMAA, Vignette } from "@react-three/postprocessing";
import * as THREE from "three";
import { RocketMesh, RenderHints } from "../rocket/RocketMesh";

interface VehicleModel {
  name?: string;
  geometry: {
    body_diameter_m: number;
    total_length_m: number;
    nose: { kind: string; length_m: number };
    fins: { count: number; span_m: number; root_chord_m: number };
    render: RenderHints;
  };
  mass_properties: { dry_mass_kg: number; loaded_mass_kg: number; loaded_cg_z_m: number };
  aerodynamics: { cp_z_m: number; static_margin_cal: number };
  assumptions?: Array<{ field: string; value: unknown; source: string }>;
}

function StudioLights() {
  // Procedural environment: a few area lights give the metal crisp highlights
  // without downloading an HDRI (works fully offline).
  return (
    <Environment resolution={256} frames={1}>
      <color attach="background" args={["#05070d"]} />
      <Lightformer intensity={2.2} position={[0, 5, -4]} scale={[10, 4, 1]} color="#cfe0ff" />
      <Lightformer intensity={1.4} position={[5, 2, 2]} scale={[3, 6, 1]} color="#ffffff" />
      <Lightformer intensity={1.1} position={[-6, 1, 1]} scale={[3, 6, 1]} color="#9bb6ff" />
      <Lightformer intensity={0.8} position={[0, -3, 3]} scale={[8, 3, 1]} color="#3b4a6b" />
    </Environment>
  );
}

export default function VehicleStudio({ vehicle }: { vehicle: VehicleModel }) {
  const [cutaway, setCutaway] = useState(true);
  const g = vehicle.geometry;
  const half = g.total_length_m / 2;
  const L = g.total_length_m;
  const margin = vehicle.aerodynamics.static_margin_cal;
  const stable = margin >= 1.0;

  return (
    <div className="studio-stage" style={{ position: "relative", width: "100%", height: "100%" }}>
      <Canvas
        shadows
        dpr={[1, 2]}
        gl={{ alpha: true, antialias: true, toneMapping: THREE.ACESFilmicToneMapping }}
        camera={{ position: [L * 0.85, L * 0.18, L * 0.95], fov: 40 }}
      >
        <fog attach="fog" args={["#070b14", L * 1.4, L * 4]} />
        <ambientLight intensity={0.25} />
        <directionalLight
          position={[L * 0.6, L * 1.1, L * 0.5]}
          intensity={1.6}
          castShadow
          shadow-mapSize={[2048, 2048]}
          shadow-camera-near={0.1}
          shadow-camera-far={L * 4}
          shadow-camera-left={-L}
          shadow-camera-right={L}
          shadow-camera-top={L}
          shadow-camera-bottom={-L}
        />
        <StudioLights />

        {/* reflective stage floor + faint grid */}
        <group position={[0, -half, 0]}>
          <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
            <planeGeometry args={[L * 6, L * 6]} />
            <MeshReflectorMaterial
              resolution={1024}
              blur={[400, 200]}
              mixBlur={1}
              mixStrength={18}
              roughness={0.85}
              depthScale={1.1}
              minDepthThreshold={0.4}
              maxDepthThreshold={1.2}
              color="#0a0e16"
              metalness={0.7}
            />
          </mesh>
          <Grid
            args={[L * 3, L * 3]}
            cellSize={g.body_diameter_m}
            cellColor="#1c2738"
            sectionSize={g.body_diameter_m * 5}
            sectionColor="#2b3a55"
            fadeDistance={L * 3.2}
            fadeStrength={2}
            position={[0, 0.002, 0]}
          />
          <ContactShadows position={[0, 0.004, 0]} scale={L * 1.6} blur={2.4} opacity={0.55} far={L} />

          <RocketMesh
            render={g.render}
            cutaway={cutaway}
            showMarkers
            cgZ={vehicle.mass_properties.loaded_cg_z_m}
            cpZ={vehicle.aerodynamics.cp_z_m}
          />
        </group>

        <OrbitControls makeDefault enableDamping autoRotate autoRotateSpeed={0.6} target={[0, 0, 0]} minDistance={L * 0.5} maxDistance={L * 2.4} />

        <EffectComposer multisampling={0}>
          <Bloom intensity={0.7} luminanceThreshold={0.75} luminanceSmoothing={0.2} mipmapBlur />
          <SMAA />
          <Vignette eskil={false} offset={0.2} darkness={0.75} />
        </EffectComposer>
      </Canvas>

      <div className="vehicle-inspector">
        <div className="vehicle-inspector__title">{vehicle.name ?? "Vehicle"} · Studio</div>
        <button className="vehicle-inspector__toggle" onClick={() => setCutaway((c) => !c)}>
          {cutaway ? "Opaque exterior" : "Cutaway view"}
        </button>
        <dl className="vehicle-inspector__stats">
          <div><dt>Length</dt><dd>{g.total_length_m.toFixed(2)} m</dd></div>
          <div><dt>Diameter</dt><dd>{(g.body_diameter_m * 1000).toFixed(0)} mm</dd></div>
          <div><dt>Loaded mass</dt><dd>{vehicle.mass_properties.loaded_mass_kg.toFixed(1)} kg</dd></div>
          <div><dt>Dry mass</dt><dd>{vehicle.mass_properties.dry_mass_kg.toFixed(1)} kg</dd></div>
          <div><dt><span className="dot dot--cg" /> CG</dt><dd>{vehicle.mass_properties.loaded_cg_z_m.toFixed(2)} m</dd></div>
          <div><dt><span className="dot dot--cp" /> CP</dt><dd>{vehicle.aerodynamics.cp_z_m.toFixed(2)} m</dd></div>
          <div>
            <dt>Static margin</dt>
            <dd className={stable ? "ok" : "warn"}>{margin.toFixed(2)} cal {stable ? "✓" : "⚠ unstable"}</dd>
          </div>
        </dl>
        {vehicle.assumptions && vehicle.assumptions.length > 0 && (
          <details className="vehicle-inspector__assumptions">
            <summary>{vehicle.assumptions.length} assumptions</summary>
            <ul>
              {vehicle.assumptions.slice(0, 12).map((a, i) => (
                <li key={i}><code>{a.field}</code> = {String(a.value)} <em>({a.source})</em></li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  );
}
