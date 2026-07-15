/**
 * DataLoader.ts — Streaming binary loader for DESI galaxy data.
 *
 * Binary format v3 (little-endian), struct-of-arrays with 4-byte field
 * alignment — each field block can be wrapped in a typed array ZERO-COPY:
 *   Header (16): magic, version, n_points, flags
 *   x[]          float32  [offset 16,          stride 4]
 *   y[]          float32  [offset 16 + 4n,     stride 4]
 *   z_cart[]     float32  [offset 16 + 8n,     stride 4]
 *   tracer[]     uint8    [offset 16 + 12n,    padded to 4n]
 *   color_byte[] uint8    [offset 16 + 12n + pad, padded to 4n]
 *   z_encoded[]  uint16   [offset ... , padded to 4n]
 * Each field array is created with a subarray view over the original buffer
 * (no allocation, no per-point loop).
 */

export interface GalaxyData {
  x: Float32Array;
  y: Float32Array;
  z: Float32Array;
  tracer: Uint8Array;
  /** g-r colour byte: 0=blue/star-forming, 255=red/passive, 128=neutral (non-BGS) */
  colorByte: Uint8Array;
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
const BINARY_VERSION = 3;
const HEADER_BYTES = 16;

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

  // Concatenate all chunks into one buffer, then parse zero-copy.
  const buffer = new ArrayBuffer(loaded);
  const view = new Uint8Array(buffer);
  let offset = 0;
  for (const chunk of chunks) {
    view.set(chunk, offset);
    offset += chunk.byteLength;
  }

  return parseBinary(buffer);
}

// ponytail: all field arrays are views into `buffer`; the caller owns `buffer`
// and must keep it alive for the lifetime of the GalaxyData (it does — it lives
// in module scope via GalaxyRenderer.data).
function parseBinary(buffer: ArrayBuffer): GalaxyData {
  const dv = new DataView(buffer);

  const magic = dv.getUint32(0, true);
  if (magic !== MAGIC) {
    throw new Error(`Invalid magic number: 0x${magic.toString(16)} (expected 0x44455349)`);
  }

  const version = dv.getUint32(4, true);
  if (version !== BINARY_VERSION) {
    throw new Error(
      `Unsupported binary version: ${version} (expected ${BINARY_VERSION}). ` +
      `Re-run 'mise run export-web' to regenerate galaxies.v3.bin.`
    );
  }

  const nPoints = dv.getUint32(8, true);

  // SoA field blocks — exact offsets (no padding; every view is aligned for
  // ANY n: f32 at multiples of 4, u8 at 16+12n (1-align), u16 at 16+14n
  // (always even)).
  const f32 = new Float32Array(buffer, HEADER_BYTES, nPoints * 3);
  const x = f32.subarray(0, nPoints);
  const y = f32.subarray(nPoints, nPoints * 2);
  const z = f32.subarray(nPoints * 2, nPoints * 3);

  const u8Start = HEADER_BYTES + nPoints * 12;
  const u8 = new Uint8Array(buffer, u8Start, nPoints * 2);
  const tracer = u8.subarray(0, nPoints);
  const colorByte = u8.subarray(nPoints, nPoints * 2);

  const u16Start = u8Start + nPoints * 2;
  const zEnc = new Uint16Array(buffer, u16Start, nPoints);
  const redshift = new Float32Array(nPoints);
  for (let i = 0; i < nPoints; i++) redshift[i] = zEnc[i] / 10000;

  return { x, y, z, tracer, colorByte, redshift, nPoints };
}
