/**
 * DataLoader.ts — Streaming binary loader for DESI galaxy data.
 *
 * Binary format (little-endian):
 *   Header (16 bytes):
 *     uint32 magic    = 0x44455349
 *     uint32 version  = 1
 *     uint32 n_points
 *     uint32 flags
 *   Body per point (16 bytes):
 *     float32 x
 *     float32 y
 *     float32 z_cart
 *     uint8   tracer_type
 *     uint8   reserved
 *     uint16  z_encoded  (z * 10000)
 */

export interface GalaxyData {
  x: Float32Array;
  y: Float32Array;
  z: Float32Array;
  tracer: Uint8Array;
  redshift: Float32Array;
  nPoints: number;
}

export interface Metadata {
  version: number;
  n_points: number;
  tracers: Record<string, { name: string; color: string; z_range: [number, number] }>;
  bounds: { x: [number, number]; y: [number, number]; z: [number, number] };
  cosmology: { H0: number; Om0: number; model: string };
  data_release: string;
}

const MAGIC = 0x44455349;
const HEADER_BYTES = 16;
const RECORD_BYTES = 16;

type ProgressCallback = (loaded: number, total: number) => void;

export async function loadMetadata(url: string): Promise<Metadata> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to load metadata: ${res.status}`);
  return res.json();
}

export async function loadGalaxyBinary(
  url: string,
  onProgress?: ProgressCallback
): Promise<GalaxyData> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to load galaxy data: ${res.status}`);

  const total = parseInt(res.headers.get("content-length") ?? "0", 10);
  const reader = res.body!.getReader();
  const chunks: Uint8Array[] = [];
  let loaded = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.byteLength;
    onProgress?.(loaded, total);
  }

  // Concatenate all chunks
  const buffer = new ArrayBuffer(loaded);
  const view = new Uint8Array(buffer);
  let offset = 0;
  for (const chunk of chunks) {
    view.set(chunk, offset);
    offset += chunk.byteLength;
  }

  return parseBinary(buffer);
}

function parseBinary(buffer: ArrayBuffer): GalaxyData {
  const dv = new DataView(buffer);

  const magic = dv.getUint32(0, true);
  if (magic !== MAGIC) {
    throw new Error(`Invalid magic number: 0x${magic.toString(16)} (expected 0x44455349)`);
  }

  const version = dv.getUint32(4, true);
  if (version !== 1) {
    throw new Error(`Unsupported binary version: ${version}`);
  }

  const nPoints = dv.getUint32(8, true);

  const x = new Float32Array(nPoints);
  const y = new Float32Array(nPoints);
  const z = new Float32Array(nPoints);
  const tracer = new Uint8Array(nPoints);
  const redshift = new Float32Array(nPoints);

  let pos = HEADER_BYTES;
  for (let i = 0; i < nPoints; i++) {
    x[i] = dv.getFloat32(pos, true);
    y[i] = dv.getFloat32(pos + 4, true);
    z[i] = dv.getFloat32(pos + 8, true);
    tracer[i] = dv.getUint8(pos + 12);
    redshift[i] = dv.getUint16(pos + 14, true) / 10000;
    pos += RECORD_BYTES;
  }

  return { x, y, z, tracer, redshift, nPoints };
}
