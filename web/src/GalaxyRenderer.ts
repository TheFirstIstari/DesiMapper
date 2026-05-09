/**
 * GalaxyRenderer.ts — Three.js point cloud renderer for DESI galaxies.
 *
 * Uses BufferGeometry + ShaderMaterial for GPU-side colour and size control,
 * enabling efficient rendering of 500k+ points at 60fps.
 */

import * as THREE from "three";
import type { GalaxyData, Metadata } from "./DataLoader";

// Tracer colour palette (matches Spec.md)
const TRACER_COLORS: Record<number, [number, number, number]> = {
  0: [1.0, 0.549, 0.0],   // BGS — orange
  1: [0.8, 0.133, 0.0],   // LRG — deep red
  2: [0.0, 0.808, 0.820], // ELG — teal/cyan
  3: [0.533, 0.533, 1.0], // QSO — blue-violet
};

const VERTEX_SHADER = /* glsl */ `
  attribute float aSize;
  attribute vec3 aColor;
  attribute float aAlpha;

  varying vec3 vColor;
  varying float vAlpha;

  void main() {
    vColor = aColor;
    vAlpha = aAlpha;
    vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = aSize * (400.0 / -mvPosition.z);
    gl_Position = projectionMatrix * mvPosition;
  }
`;

const FRAGMENT_SHADER = /* glsl */ `
  varying vec3 vColor;
  varying float vAlpha;

  void main() {
    // Circular point with soft edge
    float r = length(gl_PointCoord - vec2(0.5));
    if (r > 0.5) discard;
    float alpha = vAlpha * (1.0 - smoothstep(0.3, 0.5, r));
    gl_FragColor = vec4(vColor, alpha);
  }
`;

export interface RenderOptions {
  pointSize: number;   // base point size
  opacity: number;     // global opacity multiplier
  zCutoff: number;     // hide galaxies with z > zCutoff
  hiddenTracers: Set<number>; // tracer IDs to hide
}

export class GalaxyRenderer {
  private scene: THREE.Scene;
  private points: THREE.Points | null = null;
  private geometry: THREE.BufferGeometry | null = null;
  private material: THREE.ShaderMaterial | null = null;
  private data: GalaxyData | null = null;
  private metadata: Metadata | null = null;

  // Cached attribute arrays for hot-path updates
  private sizeAttr: THREE.BufferAttribute | null = null;
  private alphaAttr: THREE.BufferAttribute | null = null;

  constructor(scene: THREE.Scene) {
    this.scene = scene;
  }

  load(data: GalaxyData, metadata: Metadata): void {
    this.data = data;
    this.metadata = metadata;
    this.buildGeometry();
  }

  /** Expose metadata for external UI (e.g. cosmology info panel). */
  getMetadata(): Metadata | null {
    return this.metadata;
  }

  private buildGeometry(): void {
    if (!this.data) return;
    const { x, y, z, tracer, nPoints } = this.data;

    // Scale factor: convert Mpc → scene units (1 Mpc = 1 unit, ~thousands of units across)
    const positions = new Float32Array(nPoints * 3);
    const colors = new Float32Array(nPoints * 3);
    const sizes = new Float32Array(nPoints);
    const alphas = new Float32Array(nPoints);

    for (let i = 0; i < nPoints; i++) {
      positions[i * 3 + 0] = x[i];
      positions[i * 3 + 1] = y[i];
      positions[i * 3 + 2] = z[i];

      const tid = tracer[i];
      const col = TRACER_COLORS[tid] ?? [1, 1, 1];
      colors[i * 3 + 0] = col[0];
      colors[i * 3 + 1] = col[1];
      colors[i * 3 + 2] = col[2];

      sizes[i] = 1.5;
      alphas[i] = 0.7;
    }

    if (this.points) {
      this.scene.remove(this.points);
      this.geometry?.dispose();
      this.material?.dispose();
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geo.setAttribute("aColor", new THREE.BufferAttribute(colors, 3));

    const sizeAttr = new THREE.BufferAttribute(sizes, 1);
    const alphaAttr = new THREE.BufferAttribute(alphas, 1);
    geo.setAttribute("aSize", sizeAttr);
    geo.setAttribute("aAlpha", alphaAttr);

    this.sizeAttr = sizeAttr;
    this.alphaAttr = alphaAttr;

    const mat = new THREE.ShaderMaterial({
      vertexShader: VERTEX_SHADER,
      fragmentShader: FRAGMENT_SHADER,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });

    this.geometry = geo;
    this.material = mat;
    this.points = new THREE.Points(geo, mat);
    this.scene.add(this.points);
  }

  update(options: RenderOptions): void {
    if (!this.data || !this.sizeAttr || !this.alphaAttr) return;

    const { tracer, redshift, nPoints } = this.data;
    const sizes = this.sizeAttr.array as Float32Array;
    const alphas = this.alphaAttr.array as Float32Array;

    for (let i = 0; i < nPoints; i++) {
      const tid = tracer[i];
      const z = redshift[i];
      const hidden = options.hiddenTracers.has(tid) || z > options.zCutoff;
      sizes[i] = hidden ? 0 : options.pointSize;
      alphas[i] = hidden ? 0 : options.opacity;
    }

    this.sizeAttr.needsUpdate = true;
    this.alphaAttr.needsUpdate = true;
  }

  get pointCount(): number {
    return this.data?.nPoints ?? 0;
  }
}
