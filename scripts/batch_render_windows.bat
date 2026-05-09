@echo off
REM batch_render_windows.bat — Render DesiMapper on Windows with NVIDIA GPU (OptiX)
REM
REM Renders 8K frames in chunks, encodes each chunk to H.265 MP4 via NVENC,
REM then deletes PNG frames before the next chunk to cap disk usage.
REM
REM Requirements:
REM   - Blender 4.3+ or 5.x installed (default path or set BLENDER below)
REM   - ffmpeg on PATH (winget install ffmpeg, or https://ffmpeg.org)
REM   - NVIDIA GPU with CUDA 12+ drivers installed
REM   - Python data pipeline already run (data\processed\all_galaxies.parquet exists)
REM
REM Usage:
REM   batch_render_windows.bat
REM   batch_render_windows.bat 600          -- chunk size in frames (default 600)
REM   batch_render_windows.bat 600 resume   -- skip already-encoded chunks
REM
REM Run from the repo root:
REM   cd C:\path\to\DesiMapper
REM   scripts\batch_render_windows.bat

setlocal enabledelayedexpansion

REM ─── Configuration ─────────────────────────────────────────────────────────
set "BLENDER=%PROGRAMFILES%\Blender Foundation\Blender 5.1\blender.exe"
if not exist "%BLENDER%" (
    set "BLENDER=%PROGRAMFILES%\Blender Foundation\Blender 5.0\blender.exe"
)
if not exist "%BLENDER%" (
    set "BLENDER=%PROGRAMFILES%\Blender Foundation\Blender 4.4\blender.exe"
)
if not exist "%BLENDER%" (
    set "BLENDER=%PROGRAMFILES%\Blender Foundation\Blender 4.3\blender.exe"
)
if not exist "%BLENDER%" (
    echo ERROR: Blender not found at default paths. Set the BLENDER variable in this script.
    echo   Searched: Blender 5.1, 5.0, 4.4, 4.3 under %PROGRAMFILES%\Blender Foundation\
    pause
    exit /b 1
)

set "SCRIPT=animation\render.py"
set "PARQUET=data\processed\all_galaxies.parquet"
set "FRAMES_DIR=renders\frames"
set "SEGMENTS_DIR=renders\segments"
set "FINAL_OUTPUT=renders\desimapper_8k_60fps.mp4"
set "CONCAT_LIST=renders\concat.txt"

set "FPS=60"
set "TOTAL_SECONDS=390"
set /a "TOTAL_FRAMES=FPS * TOTAL_SECONDS"

REM Default chunk = 600 frames (10s @ 60fps, ~9 GB PNGs on disk at once)
set "CHUNK_SIZE=600"
set "RESUME=false"

if not "%~1"=="" set "CHUNK_SIZE=%~1"
if "%~2"=="resume" set "RESUME=true"

REM ─── Validate prerequisites ────────────────────────────────────────────────
if not exist "%PARQUET%" (
    echo ERROR: Galaxy data not found at %PARQUET%
    echo Run the pipeline first: python pipeline\fetch.py ^&^& python pipeline\process.py
    pause
    exit /b 1
)

where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo ERROR: ffmpeg not found on PATH.
    echo Install with: winget install ffmpeg
    echo Or download from https://ffmpeg.org/download.html and add to PATH.
    pause
    exit /b 1
)

if not exist "%FRAMES_DIR%" mkdir "%FRAMES_DIR%"
if not exist "%SEGMENTS_DIR%" mkdir "%SEGMENTS_DIR%"

REM ─── Print configuration ───────────────────────────────────────────────────
echo.
echo =========================================================
echo   DesiMapper -- Batched 8K 60fps Render (Windows/NVENC)
echo =========================================================
echo.
echo   Blender     : %BLENDER%
echo   Parquet     : %PARQUET%
echo   Total frames: %TOTAL_FRAMES% (%TOTAL_SECONDS%s @ %FPS%fps)
echo   Chunk size  : %CHUNK_SIZE% frames
echo   Resume mode : %RESUME%
echo.

REM ─── Calculate number of chunks ────────────────────────────────────────────
set /a "N_CHUNKS=(TOTAL_FRAMES + CHUNK_SIZE - 1) / CHUNK_SIZE"
echo   Chunks total: %N_CHUNKS%
echo.

REM ─── Render loop ───────────────────────────────────────────────────────────
set "CHUNK=0"
:render_loop
if %CHUNK% GEQ %N_CHUNKS% goto concat

set /a "START=CHUNK * CHUNK_SIZE + 1"
set /a "END=(CHUNK + 1) * CHUNK_SIZE"
if %END% GTR %TOTAL_FRAMES% set "END=%TOTAL_FRAMES%"

REM Zero-pad chunk number for segment filename
set "CHUNK_PAD=000%CHUNK%"
set "CHUNK_PAD=!CHUNK_PAD:~-4!"
set "SEGMENT=%SEGMENTS_DIR%\segment_!CHUNK_PAD!.mp4"

set /a "CHUNK_DISPLAY=CHUNK + 1"
echo [Chunk %CHUNK_DISPLAY%/%N_CHUNKS%] Frames %START%-%END%

if "%RESUME%"=="true" if exist "!SEGMENT!" (
    echo   Already encoded -- skipping
    echo.
    set /a "CHUNK+=1"
    goto render_loop
)

REM ── Render frames ──────────────────────────────────────────────────────────
echo   Rendering...
"%BLENDER%" --background --python "%SCRIPT%" -- ^
    --parquet "%PARQUET%" ^
    --output "%FRAMES_DIR%" ^
    --resolution "7680x4320" ^
    --fps %FPS% ^
    --samples 128 ^
    --start-frame %START% ^
    --end-frame %END% ^
    --max-points 1400000

if errorlevel 1 (
    echo ERROR: Blender render failed on chunk %CHUNK_DISPLAY%
    pause
    exit /b 1
)

REM Count rendered frames
set "N_RENDERED=0"
for %%f in ("%FRAMES_DIR%\frame_*.png") do set /a "N_RENDERED+=1"
echo   Rendered %N_RENDERED% frames

REM ── Encode chunk to MP4 via NVENC (GPU H.265) ──────────────────────────────
REM Note: Windows cmd does not expand globs — use %%04d sequential pattern.
REM Blender names frames frame_0001.png … frame_NNNN.png.
REM -start_number tells ffmpeg which frame number the chunk begins at.
echo   Encoding segment: !SEGMENT!
ffmpeg -y ^
    -framerate %FPS% ^
    -start_number %START% ^
    -i "%FRAMES_DIR%\frame_%%04d.png" ^
    -c:v hevc_nvenc ^
    -preset p6 ^
    -cq 20 ^
    -b:v 0 ^
    -pix_fmt yuv420p ^
    -tag:v hvc1 ^
    -movflags +faststart ^
    "!SEGMENT!"

if errorlevel 1 (
    echo WARNING: NVENC H.265 failed. Falling back to software libx265...
    ffmpeg -y ^
        -framerate %FPS% ^
        -start_number %START% ^
        -i "%FRAMES_DIR%\frame_%%04d.png" ^
        -c:v libx265 ^
        -crf 18 ^
        -preset slow ^
        -pix_fmt yuv420p ^
        -movflags +faststart ^
        "!SEGMENT!"
)

if errorlevel 1 (
    echo ERROR: Encoding failed for chunk %CHUNK_DISPLAY%
    pause
    exit /b 1
)

echo   Encoded: !SEGMENT!

REM ── Delete PNG frames to free disk space ───────────────────────────────────
del /q "%FRAMES_DIR%\frame_*.png"
echo   PNG frames cleared
echo.

set /a "CHUNK+=1"
goto render_loop

REM ─── Concatenate segments ──────────────────────────────────────────────────
:concat
echo.
echo Concatenating %N_CHUNKS% segments into final video...
if exist "%CONCAT_LIST%" del "%CONCAT_LIST%"

set "CHUNK=0"
:concat_loop
if %CHUNK% GEQ %N_CHUNKS% goto concat_done
set "CHUNK_PAD=000%CHUNK%"
set "CHUNK_PAD=!CHUNK_PAD:~-4!"
echo file '%CD%\%SEGMENTS_DIR%\segment_!CHUNK_PAD!.mp4'>> "%CONCAT_LIST%"
set /a "CHUNK+=1"
goto concat_loop

:concat_done
ffmpeg -y ^
    -f concat ^
    -safe 0 ^
    -i "%CONCAT_LIST%" ^
    -c copy ^
    "%FINAL_OUTPUT%"

if errorlevel 1 (
    echo ERROR: Final concatenation failed
    pause
    exit /b 1
)

echo.
echo =========================================================
echo   DONE!
echo   Final video: %FINAL_OUTPUT%
echo =========================================================
echo.
echo YouTube upload checklist:
echo   [ ] Title: 'The Universe as Seen by DESI -- 40 Million Galaxies in 3D (8K 60fps)'
echo   [ ] Upload as Unlisted first to verify quality, then publish
echo   [ ] YouTube processes 8K for ~30-60 min after upload
echo.
pause
