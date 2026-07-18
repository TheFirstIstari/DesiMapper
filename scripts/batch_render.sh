#!/usr/bin/env bash
# batch_render.sh — Render DesiMapper in frame batches to manage disk space.
#
# 8K PNG frames are ~15 MB each; rendering in chunks of N frames, encoding each to
# MP4, then deleting the PNGs keeps peak disk use bounded (~9 GB at a time).
# Each chunk becomes a segment MP4; the final step concatenates them.
#
# Usage:
#   bash scripts/batch_render.sh                     # 8K default
#   RESOLUTION=1920x1080 FINAL_OUTPUT=renders/dm_1080p.mp4 bash scripts/batch_render.sh
#   bash scripts/batch_render.sh --chunk-size 600     # 10s @ 60fps
#   bash scripts/batch_render.sh --resume             # skip already-encoded chunks
#
# Requirements: Blender, ffmpeg
set -euo pipefail

BLENDER="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
SCRIPT="animation/render.py"
PARQUET="data/processed/all_galaxies.parquet"
FRAMES_DIR="renders/frames"
SEGMENTS_DIR="renders/segments"
CONCAT_LIST="renders/concat.txt"
RESOLUTION="${RESOLUTION:-7680x4320}"
FINAL_OUTPUT="${FINAL_OUTPUT:-renders/desimapper_8k_60fps.mp4}"
FPS=60
TOTAL_SECONDS=240
TOTAL_FRAMES=$((FPS * TOTAL_SECONDS))

CHUNK_SIZE=600
RESUME=false

for arg in "$@"; do
  case $arg in
    --chunk-size=*) CHUNK_SIZE="${arg#*=}" ;;
    --resume)       RESUME=true ;;
  esac
done

mkdir -p "$FRAMES_DIR" "$SEGMENTS_DIR"

echo "=== DesiMapper batched render ($RESOLUTION, ${FPS}fps) ==="
echo "  Total frames: $TOTAL_FRAMES (${TOTAL_SECONDS}s)"
echo "  Chunk size  : $CHUNK_SIZE frames"
echo "  Output      : $FINAL_OUTPUT"

N_CHUNKS=$(( (TOTAL_FRAMES + CHUNK_SIZE - 1) / CHUNK_SIZE ))

for ((chunk=0; chunk<N_CHUNKS; chunk++)); do
  START=$(( chunk * CHUNK_SIZE + 1 ))
  END=$(( (chunk + 1) * CHUNK_SIZE ))
  END=$(( END > TOTAL_FRAMES ? TOTAL_FRAMES : END ))
  SEGMENT="${SEGMENTS_DIR}/segment_$(printf '%04d' $chunk).mp4"

  if [ "$RESUME" = true ] && [ -f "$SEGMENT" ]; then
    echo "  skip chunk $((chunk+1))/$N_CHUNKS (already encoded)"
    continue
  fi

  echo "  chunk $((chunk+1))/$N_CHUNKS — frames $START-$END"
  "$BLENDER" --background --python "$SCRIPT" -- \
    --parquet "$PARQUET" --output "$FRAMES_DIR" \
    --resolution "$RESOLUTION" --fps "$FPS" --samples 64 \
    --start-frame "$START" --end-frame "$END" --max-points 1400000 \
    2>&1 | grep -E "Fra:|Render|complete|Error|WARNING" || true

  ffmpeg -y -framerate "$FPS" -pattern_type glob -i "${FRAMES_DIR}/frame_*.png" \
    -c:v hevc_videotoolbox -q:v 45 -tag:v hvc1 -pix_fmt yuv420p \
    -movflags +faststart "$SEGMENT" 2>&1 | tail -3

  rm -f "${FRAMES_DIR}"/frame_*.png
done

echo "=== concatenating $N_CHUNKS segments → $FINAL_OUTPUT ==="
> "$CONCAT_LIST"
for ((chunk=0; chunk<N_CHUNKS; chunk++)); do
  echo "file '$(pwd)/${SEGMENTS_DIR}/segment_$(printf '%04d' $chunk).mp4'" >> "$CONCAT_LIST"
done
ffmpeg -y -f concat -safe 0 -i "$CONCAT_LIST" -c copy "$FINAL_OUTPUT" 2>&1 | tail -3

echo "✓ Done: $FINAL_OUTPUT ($(du -sh "$FINAL_OUTPUT" | cut -f1))"
