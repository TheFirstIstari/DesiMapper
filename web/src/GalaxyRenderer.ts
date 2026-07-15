/**
 * GalaxyRenderer.ts — Three.js point cloud renderer for DESI galaxies.
 *
 * Uses BufferGeometry + ShaderMaterial for GPU-side colour and size control,
 * enabling efficient rendering of 1M+ points at 60fps.
 *
 * Performance design:
 *  - Zero CPU work per frame / per slider interaction after initial load.
 *    All visibility, size, and opacity decisions are resolved in the vertex
 *    shader from uniforms — no BufferAttribute re-upload on slider moves.
 *  - aColor eliminated: tracer ID stored as uint8→float per point; 4 colours
 *    sent as uniform vec3[4] palette. Saves ~12 MB VRAM at 1M points.
 *  - gl_PointSize scaled by uCanvasHeight so points look identical across
 *    all resolutions / DPR settings.
 *  - Behind-camera guard: mvPosition.z >= 0 clips the vertex away cleanly.
 *  - gl_PointSize clamped to uMaxPointSize (from ALIASED_POINT_SIZE_RANGE).
 *
 * BGS colour coding:
 *  - aColorByte (0–255) encodes g-r colour from DESI dereddened fluxes.
 *    0 = blue/star-forming, 255 = red/passive.
 *  - The vertex shader mixes uBgsBlue↔uBgsRed for BGS points, ignoring
 *    the uniform palette colour.  Other tracers still use uColors[tid].
 *
 * Uniforms updated on slider interaction (cheap, no GPU buffer upload):
 *   uPointSize      — base size multiplier
 *   uOpacity        — global opacity
 *   uZCutoff        — redshift ceiling (points with z > cutoff → size 0)
 *   uTracerVisible  — bool[4] per-tracer visibility flags
 */

import * as THREE from "three";
import type { GalaxyData, Metadata } from "./DataLoader";

// Tracer colour palette (matches Spec.md) — uniform, not per-vertex.
const TRACER_COLORS_FLAT: number[] = [
  1.0, 0.549, 0.0,    // 0: BGS — orange
  0.8, 0.133, 0.0,    // 1: LRG — deep red
  0.0, 0.808, 0.820,  // 2: ELG — teal/cyan
  0.533, 0.533, 1.0,  // 3: QSO — blue-violet
];

const VERTEX_SHADER = /* glsl */ `
  // Per-vertex (static after load — never re-uploaded)
  attribute float aTracer;     // tracer index 0–3
  attribute float aRedshift;   // encoded redshift (0–2.1)
  attribute float aColorByte;  // g-r colour byte 0–255 (BGS only; 128=neutral)

  // Uniforms updated cheaply on slider interaction (no buffer upload)
  uniform vec3  uColors[4];
  uniform vec3  uBgsBlue;      // colour for star-forming BGS (g-r low)
  uniform vec3  uBgsRed;       // colour for passive BGS (g-r high)
  uniform float uPointSize;
  uniform float uOpacity;
  uniform float uZCutoff;
  uniform bool  uTracerVisible[4];
  uniform float uCanvasHeight;
  uniform float uMaxPointSize;

  varying vec3  vColor;
  varying float vAlpha;

  void main() {
    int tid = int(aTracer + 0.5);

    // Visibility: hidden tracer or above z cutoff → size 0, fully transparent
    bool visible = uTracerVisible[tid] && (aRedshift <= uZCutoff);

    // BGS: interpolate blue↔red ramp from per-galaxy g-r colour byte
    // Other tracers: use uniform palette colour
    if (tid == 0) {
      float t = aColorByte / 255.0;
      vColor = mix(uBgsBlue, uBgsRed, t);
    } else {
      vColor = uColors[tid];
    }
    vAlpha = visible ? uOpacity : 0.0;

    vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);

    // Clip points behind the camera
    if (mvPosition.z >= 0.0) {
      gl_Position = vec4(0.0, 0.0, 2.0, 1.0);
      gl_PointSize = 0.0;
      return;
    }

    float sz = visible
      ? uPointSize * (uCanvasHeight / 800.0) * (400.0 / -mvPosition.z)
      : 0.0;
    gl_PointSize = clamp(sz, 0.0, uMaxPointSize);
    gl_Position  = projectionMatrix * mvPosition;
  }
`;

const FRAGMENT_SHADER = /* glsl */ `
  varying vec3  vColor;
  varying float vAlpha;

  void main() {
    if (vAlpha <= 0.0) discard;
    float r = length(gl_PointCoord - vec2(0.5));
    if (r > 0.5) discard;
    float alpha = vAlpha * (1.0 - smoothstep(0.3, 0.5, r));
    gl_FragColor = vec4(vColor, alpha);
  }
`;

export interface RenderOptions {
  pointSize: number;
  opacity: number;
  zCutoff: number;
  hiddenTracers: Set<number>;
}

export class GalaxyRenderer {
  private scene: THREE.Scene;
  private points: THREE.Points | null = null;
  private geometry: THREE.BufferGeometry | null = null;
  private material: THREE.ShaderMaterial | null = null;
  private data: GalaxyData | null = null;
  private metadata: Metadata | null = null;

  constructor(scene: THREE.Scene) {
    this.scene = scene;
  }

  load(data: GalaxyData, metadata: Metadata): void {
    this.data = data;
    this.metadata = metadata;
    this.buildGeometry();
  }

  getMetadata(): Metadata | null {
    return this.metadata;
  }

  setCanvasHeight(h: number): void {
    if (this.material) {
      (this.material.uniforms["uCanvasHeight"] as THREE.IUniform<number>).value = h;
    }
  }

  setMaxPointSize(size: number): void {
    if (this.material) {
      (this.material.uniforms["uMaxPointSize"] as THREE.IUniform<number>).value = size;
    }
  }

  private buildGeometry(): void {
    if (!this.data) return;
    const { x, y, z, tracer, colorByte, redshift, nPoints } = this.data;

    // position MUST be interleaved xyz for Three.js; single copy, unavoidable.
    // tracer/redshift/colorByte are already SoA Float32/Uint8 views — wrap
    // them directly, no re-copy.
    const positions = new Float32Array(nPoints * 3);
    for (let i = 0; i < nPoints; i++) {
      positions[i * 3]     = x[i];
      positions[i * 3 + 1] = y[i];
      positions[i * 3 + 2] = z[i];
    }

    if (this.points) {
      this.scene.remove(this.points);
      this.geometry?.dispose();
      this.material?.dispose();
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position",   new THREE.BufferAttribute(positions, 3));
    geo.setAttribute("aTracer",    new THREE.BufferAttribute(tracer, 1));
    geo.setAttribute("aRedshift",  new THREE.BufferAttribute(redshift, 1));
    geo.setAttribute("aColorByte", new THREE.BufferAttribute(colorByte, 1));

    const mat = new THREE.ShaderMaterial({
      vertexShader: VERTEX_SHADER,
      fragmentShader: FRAGMENT_SHADER,
      uniforms: {
        uColors:        { value: TRACER_COLORS_FLAT },
        // BGS colour ramp: blue star-forming → red passive
        uBgsBlue:       { value: new THREE.Vector3(0.27, 0.53, 1.0) },   // #4587FF
        uBgsRed:        { value: new THREE.Vector3(1.0,  0.22, 0.05) },  // #FF3800
        uPointSize:     { value: 1.5 },
        uOpacity:       { value: 0.7 },
        uZCutoff:       { value: 2.1 },
        uTracerVisible: { value: [true, true, true, true] },
        uCanvasHeight:  { value: window.innerHeight * Math.min(window.devicePixelRatio, 2) },
        uMaxPointSize:  { value: 64.0 },
      },
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });

    this.geometry = geo;
    this.material = mat;
    this.points = new THREE.Points(geo, mat);
    this.scene.add(this.points);
  }

  /**
   * Update render options — purely uniform writes, zero CPU iteration,
   * zero GPU buffer upload regardless of point count.
   */
  update(options: RenderOptions): void {
    if (!this.material) return;
    const u = this.material.uniforms;
    (u["uPointSize"] as THREE.IUniform<number>).value = options.pointSize;
    (u["uOpacity"]   as THREE.IUniform<number>).value = options.opacity;
    (u["uZCutoff"]   as THREE.IUniform<number>).value = options.zCutoff;
    (u["uTracerVisible"] as THREE.IUniform<boolean[]>).value = [
      !options.hiddenTracers.has(0),
      !options.hiddenTracers.has(1),
      !options.hiddenTracers.has(2),
      !options.hiddenTracers.has(3),
    ];
  }

  get pointCount(): number {
    return this.data?.nPoints ?? 0;
  }
}
