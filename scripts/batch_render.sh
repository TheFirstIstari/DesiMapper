#!/usr/bin/env bash
# batch_render.sh — Render DesiMapper in frame batches to manage disk space.
#
# 8K PNG frames are ~15 MB each. At 60fps × 390s = 23,400 frames = ~340 GB total.
# This script renders in chunks of N frames, encodes each chunk to MP4,
# then deletes the PNG frames before the next batch — keeping disk use ~30 GB max.
#
# Each chunk produces a segment MP4; the final step concatenates them.
#
# Usage:
#   bash scripts/batch_render.sh
#   bash scripts/batch_render.sh --chunk-size 600  # 600 frames = 10s @ 60fps
#   bash scripts/batch_render.sh --resume           # skip already-encoded chunks
#
# Requirements: Blender 4.3, ffmpeg
set -euo pipefail

BLENDER="/Applications/Blender.app/Contents/MacOS/Blender"
SCRIPT="animation/render.py"
PARQUET="data/processed/all_galaxies.parquet"
FRAMES_DIR="renders/frames"
SEGMENTS_DIR="renders/segments"
FINAL_OUTPUT="renders/desimapper_8k_60fps.mp4"
CONCAT_LIST="renders/concat.txt"

FPS=60
TOTAL_SECONDS=390
TOTAL_FRAMES=$((FPS * TOTAL_SECONDS))  # 23,400

CHUNK_SIZE=600    # 10 seconds per batch = ~9 GB of PNGs at a time
RESUME=false

for arg in "$@"; do
  case $arg in
    --chunk-size=*) CHUNK_SIZE="${arg#*=}" ;;
    --resume)       RESUME=true ;;
  esac
done

mkdir -p "$FRAMES_DIR" "$SEGMENTS_DIR"

echo "╔══════════════════════════════════════════════════════╗"
echo "║  DesiMapper — Batched 8K 60fps Render                ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  Total frames  : $TOTAL_FRAMES (${TOTAL_SECONDS}s @ ${FPS}fps)"
echo "  Chunk size     : $CHUNK_SIZE frames ($(echo "scale=1; $CHUNK_SIZE / $FPS" | bc)s per batch)"
echo "  Chunks total   : $(echo "scale=0; ($TOTAL_FRAMES + $CHUNK_SIZE - 1) / $CHUNK_SIZE" | bc)"
echo "  Peak disk use  : ~$(echo "scale=0; $CHUNK_SIZE * 15 / 1024" | bc) GB per batch"
echo ""

# Compute number of chunks
N_CHUNKS=$(( (TOTAL_FRAMES + CHUNK_SIZE - 1) / CHUNK_SIZE ))

for ((chunk=0; chunk<N_CHUNKS; chunk++)); do
  START=$(( chunk * CHUNK_SIZE + 1 ))
  END=$(( (chunk + 1) * CHUNK_SIZE ))
  END=$(( END > TOTAL_FRAMES ? TOTAL_FRAMES : END ))
  SEGMENT="${SEGMENTS_DIR}/segment_$(printf '%04d' $chunk).mp4"

  if [ "$RESUME" = true ] && [ -f "$SEGMENT" ]; then
    echo "  ✓ Chunk $((chunk+1))/$N_CHUNKS already encoded — skipping (frames $START–$END)"
    continue
  fi

  echo "▶ Chunk $((chunk+1))/$N_CHUNKS — frames $START–$END ($(echo "scale=1; ($END - $START + 1) / $FPS" | bc)s)"

  # Render frames
  "$BLENDER" --background --python "$SCRIPT" -- \
    --parquet "$PARQUET" \
    --output "$FRAMES_DIR" \
    --resolution "7680x4320" \
    --fps "$FPS" \
    --samples 128 \
    --start-frame "$START" \
    --end-frame "$END" \
    --max-points 1400000 \
    2>&1 | grep -E "Fra:|Render|complete|Error|WARNING" || true

  # Count rendered frames
  N_RENDERED=$(ls "${FRAMES_DIR}"/frame_*.png 2>/dev/null | wc -l | tr -d ' ')
  echo "  Rendered $N_RENDERED frames"

  # Encode this chunk to MP4 segment
  echo "  Encoding segment → $SEGMENT"
  ffmpeg -y \
    -framerate "$FPS" \
    -pattern_type glob \
    -i "${FRAMES_DIR}/frame_*.png" \
    -c:v hevc_videotoolbox \
    -q:v 45 \
    -tag:v hvc1 \
    -pix_fmt yuv420p \
    -movflags +faststart \
    "$SEGMENT" \
  2>&1 | tail -3

  SEGMENT_SIZE=$(du -sh "$SEGMENT" | cut -f1)
  echo "  ✓ Segment encoded (${SEGMENT_SIZE})"

  # Remove PNG frames to free disk space
  rm -f "${FRAMES_DIR}"/frame_*.png
  echo "  ✓ Frame PNGs cleared"
  echo ""
done

# Concatenate all segments into final video
echo "▶ Concatenating $N_CHUNKS segments → $FINAL_OUTPUT"
> "$CONCAT_LIST"
for ((chunk=0; chunk<N_CHUNKS; chunk++)); do
  SEGMENT="${SEGMENTS_DIR}/segment_$(printf '%04d' $chunk).mp4"
  echo "file '$(pwd)/${SEGMENT}'" >> "$CONCAT_LIST"
done

ffmpeg -y \
  -f concat \
  -safe 0 \
  -i "$CONCAT_LIST" \
  -c copy \
  "$FINAL_OUTPUT" \
  2>&1 | tail -5

FINAL_SIZE=$(du -sh "$FINAL_OUTPUT" | cut -f1)
echo ""
echo "✓ Done! Final video: $FINAL_OUTPUT (${FINAL_SIZE})"
echo ""
echo "YouTube upload checklist:"
echo "  Title: 'The Universe as Seen by DESI — 40 Million Galaxies in 3D (8K 60fps)'"
echo "  Upload as 'Unlisted' first to verify quality, then publish"
echo "  YouTube will process 8K for ~30-60 min after upload"
