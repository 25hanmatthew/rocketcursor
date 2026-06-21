// Vehicle Studio — the complete generated rocket: airframe, nose, fins, and the
// propulsion package inside (cutaway), with CG/CP markers, stability, and mass.
// Procedural R3F driven by vehicle_model.json. Renderer only; no engineering math.

import { useState } from "react";
import { Canvas } from "@react-three/fiber";
import { Grid, OrbitControls } from "@react-three/drei";
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

export default function VehicleStudio({ vehicle }: { vehicle: VehicleModel }) {
  const [cutaway, setCutaway] = useState(true);
  const g = vehicle.geometry;
  const half = g.total_length_m / 2;
  const margin = vehicle.aerodynamics.static_margin_cal;
  const stable = margin >= 1.0;

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <Canvas camera={{ position: [g.total_length_m * 0.9, g.total_length_m * 0.15, g.total_length_m * 0.9], fov: 42 }}>
        <ambientLight intensity={0.7} />
        <hemisphereLight args={["#9fc0ff", "#0a0f18", 0.6]} />
        <directionalLight position={[6, 10, 8]} intensity={1.2} castShadow />
        <directionalLight position={[-8, 4, -6]} intensity={0.4} color="#7da7ff" />
        <Grid position={[0, -half, 0]} args={[20, 20]} cellColor="#1f2937" sectionColor="#374151" infiniteGrid fadeDistance={30} />
        {/* center the rocket on the origin for orbiting */}
        <group position={[0, -half, 0]}>
          <RocketMesh
            render={g.render}
            cutaway={cutaway}
            showMarkers
            cgZ={vehicle.mass_properties.loaded_cg_z_m}
            cpZ={vehicle.aerodynamics.cp_z_m}
          />
        </group>
        <OrbitControls makeDefault enableDamping target={[0, 0, 0]} />
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
