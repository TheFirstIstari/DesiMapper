#!/usr/bin/env bash
# encode_video.sh — Encode rendered EXR/PNG frames → YouTube-ready 8K 60fps MP4
#
# Usage:
#   bash scripts/encode_video.sh                        # defaults
#   bash scripts/encode_video.sh renders/frames/ renders/desimapper_8k.mp4
#
# Requirements: ffmpeg with libx265 (HEVC) support
#   brew install ffmpeg
#
# YouTube 8K upload notes:
#   - YouTube requires H.264 or H.265 (HEVC) for 8K
#   - H.265 at CRF 18 gives excellent quality at ~80 Mbit/s
#   - Use H.264 fallback (--codec h264) if H.265 upload is rejected
#   - Processing time on YouTube for 8K can be 30-60 min after upload
#   - Upload as 'unlisted' first to verify quality before publishing
set -euo pipefail

FRAMES_DIR="${1:-renders/frames}"
OUTPUT="${2:-renders/desimapper_8k.mp4}"
FPS="${3:-60}"
CODEC="${4:-h265}"   # h265 (recommended) or h264

if ! command -v ffmpeg &> /dev/null; then
  echo "Error: ffmpeg not found. Install with: brew install ffmpeg"
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT")"

# Detect input format — prefer EXR (HDR), fall back to PNG
if ls "${FRAMES_DIR}"/frame_*.exr &>/dev/null 2>&1; then
  INPUT_PATTERN="${FRAMES_DIR}/frame_%04d.exr"
  echo "Input format: OpenEXR (HDR)"
else
  INPUT_PATTERN="${FRAMES_DIR}/frame_%04d.png"
  echo "Input format: PNG"
fi

echo "╔══════════════════════════════════════════╗"
echo "║  DesiMapper — 8K 60fps Video Encode      ║"
echo "╚══════════════════════════════════════════╝"
echo "  Input  : ${FRAMES_DIR}/"
echo "  Output : ${OUTPUT}"
echo "  FPS    : ${FPS}"
echo "  Codec  : ${CODEC}"
echo ""

if [ "$CODEC" = "h265" ]; then
  # H.265 / HEVC — best for 8K YouTube, ~80 Mbit/s at CRF 18
  # VideoToolbox hardware H.265 encoder on macOS for speed
  echo "Encoding with H.265 (HEVC)…"
  ffmpeg -y \
    -framerate "${FPS}" \
    -i "${INPUT_PATTERN}" \
    -c:v hevc_videotoolbox \
    -q:v 45 \
    -tag:v hvc1 \
    -pix_fmt yuv420p \
    -color_primaries bt2020 \
    -color_trc smpte2084 \
    -colorspace bt2020nc \
    -movflags +faststart \
    -vf "scale=7680:4320:flags=lanczos" \
    "$OUTPUT" \
  || {
    echo "VideoToolbox H.265 failed — falling back to software libx265…"
    ffmpeg -y \
      -framerate "${FPS}" \
      -i "${INPUT_PATTERN}" \
      -c:v libx265 \
      -crf 18 \
      -preset slow \
      -x265-params "hdr-opt=1:repeat-headers=1:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc" \
      -pix_fmt yuv420p10le \
      -movflags +faststart \
      -vf "scale=7680:4320:flags=lanczos" \
      "$OUTPUT"
  }
else
  # H.264 fallback — universally compatible
  echo "Encoding with H.264…"
  ffmpeg -y \
    -framerate "${FPS}" \
    -i "${INPUT_PATTERN}" \
    -c:v h264_videotoolbox \
    -q:v 40 \
    -pix_fmt yuv420p \
    -movflags +faststart \
    -vf "scale=7680:4320:flags=lanczos" \
    "$OUTPUT" \
  || {
    echo "VideoToolbox H.264 failed — falling back to software libx264…"
    ffmpeg -y \
      -framerate "${FPS}" \
      -i "${INPUT_PATTERN}" \
      -c:v libx264 \
      -crf 18 \
      -preset slow \
      -pix_fmt yuv420p \
      -movflags +faststart \
      -vf "scale=7680:4320:flags=lanczos" \
      "$OUTPUT"
  }
fi

SIZE=$(du -sh "$OUTPUT" | cut -f1)
DURATION=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$OUTPUT" 2>/dev/null || echo "?")
echo ""
echo "✓ Encoded: ${OUTPUT}"
echo "  Size    : ${SIZE}"
echo "  Duration: ${DURATION}s"
echo ""
echo "Storage breakdown:"
echo "  8K EXR frames : ~50 MB/frame"
echo "  Final MP4     : ${SIZE}"
echo ""
echo "YouTube upload checklist:"
echo "  [ ] Upload via YouTube Studio at 4K or 8K resolution"
echo "  [ ] Set title: 'The Universe as Seen by DESI — 40 Million Galaxies in 3D'"
echo "  [ ] Add description with DESI citation (see README)"
echo "  [ ] Upload unlisted first → verify quality → publish"
echo "  [ ] YouTube processes 8K in 30-60 min after upload"
