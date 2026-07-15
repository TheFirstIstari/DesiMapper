"""Round-trip check for v3 SoA binary format. Run: python pipeline/test_binary_v3.py
Tests n both divisible and NOT divisible by 4 — the latter caught a padding bug."""
import struct
import numpy as np

MAGIC = 0x44452349
VERSION = 3
HEADER = 16


def _write(blob, n, x, y, z, tracer, color, zenc):
    body = (
        x.tobytes() + y.tobytes() + z.tobytes()
        + tracer.tobytes() + color.tobytes() + zenc.tobytes()
    )
    blob.extend(struct.pack("<IIII", MAGIC, VERSION, n, 0))
    blob.extend(body)


def _read(blob, n):
    f32 = np.frombuffer(blob, dtype="<f4", count=n * 3, offset=HEADER)
    rx, ry, rz = f32[0:n], f32[n:2 * n], f32[2 * n:3 * n]
    u8s = HEADER + n * 12
    u8 = np.frombuffer(blob, dtype="u1", count=n * 2, offset=u8s)
    rt, rc = u8[0:n], u8[n:2 * n]
    u16s = u8s + n * 2
    rzenc = np.frombuffer(blob, dtype="<u2", count=n, offset=u16s)
    return rx, ry, rz, rt, rc, rzenc


def check(n):
    rng = np.random.default_rng(n)
    x = rng.uniform(-5000, 5000, n).astype("<f4")
    y = rng.uniform(-5000, 5000, n).astype("<f4")
    z = rng.uniform(-5000, 5000, n).astype("<f4")
    tracer = rng.integers(0, 4, n).astype("<u1")
    color = rng.integers(0, 255, n).astype("<u1")
    zenc = np.clip(rng.uniform(0, 2.1, n) * 10000, 0, 65535).astype("<u2")

    blob = bytearray()
    _write(blob, n, x, y, z, tracer, color, zenc)
    assert len(blob) == HEADER + n * 16, f"size {len(blob)} != {HEADER + n*16}"
    rx, ry, rz, rt, rc, rzenc = _read(blob, n)
    assert np.array_equal(rx, x) and np.array_equal(ry, y) and np.array_equal(rz, z)
    assert np.array_equal(rt, tracer) and np.array_equal(rc, color)
    assert np.array_equal(rzenc, zenc)
    assert struct.unpack_from("<I", blob, 4)[0] == VERSION


for n in (1000, 1001):  # 1001: NOT divisible by 4 — exercises alignment edge
    check(n)
print("OK v3 round-trip (n=1000, n=1001)")
