import * as THREE from "three";
import type { Vec3 } from "./sceneModel";

/* Transform for a unit-Y cylinder/tube so it spans `start`→`end`: position it at
   the midpoint and rotate its +Y axis onto the segment direction. Length is the
   value to scale the geometry's Y by. */
export function segmentTransform(start: Vec3, end: Vec3): {
  mid: THREE.Vector3;
  quaternion: THREE.Quaternion;
  length: number;
} {
  const a = new THREE.Vector3(start.x, start.y, start.z);
  const b = new THREE.Vector3(end.x, end.y, end.z);
  const dir = new THREE.Vector3().subVectors(b, a);
  const length = dir.length();
  const mid = new THREE.Vector3().addVectors(a, b).multiplyScalar(0.5);
  const quaternion = new THREE.Quaternion().setFromUnitVectors(
    new THREE.Vector3(0, 1, 0),
    length > 1e-9 ? dir.clone().normalize() : new THREE.Vector3(0, 1, 0)
  );
  return { mid, quaternion, length };
}
