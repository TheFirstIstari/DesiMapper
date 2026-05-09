@echo off
REM encode_video_windows.bat — Encode rendered PNG frames → YouTube-ready 8K H.265 MP4
REM                            Uses NVENC (NVIDIA GPU) for fast hardware encoding.
REM
REM Usage:
REM   scripts\encode_video_windows.bat
REM   scripts\encode_video_windows.bat renders\frames renders\desimapper_8k.mp4
REM   scripts\encode_video_windows.bat renders\frames renders\desimapper_8k.mp4 60 h264
REM
REM Arguments (all optional, positional):
REM   %1  frames dir  (default: renders\frames)
REM   %2  output file (default: renders\desimapper_8k.mp4)
REM   %3  fps         (default: 60)
REM   %4  codec       (default: h265 — use h264 for broader compatibility)
REM
REM Requirements:
REM   - ffmpeg on PATH (winget install ffmpeg)
REM   - NVIDIA GPU with NVENC support (GTX 900+ or RTX series)

setlocal enabledelayedexpansion

set "FRAMES_DIR=%~1"
if "%FRAMES_DIR%"=="" set "FRAMES_DIR=renders\frames"

set "OUTPUT=%~2"
if "%OUTPUT%"=="" set "OUTPUT=renders\desimapper_8k.mp4"

set "FPS=%~3"
if "%FPS%"=="" set "FPS=60"

set "CODEC=%~4"
if "%CODEC%"=="" set "CODEC=h265"

REM ─── Validate ──────────────────────────────────────────────────────────────
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo ERROR: ffmpeg not found on PATH.
    echo Install with: winget install ffmpeg
    pause
    exit /b 1
)

if not exist "%FRAMES_DIR%" (
    echo ERROR: Frames directory not found: %FRAMES_DIR%
    pause
    exit /b 1
)

REM Detect input format
set "INPUT_PATTERN=%FRAMES_DIR%\frame_%%04d.png"
for %%f in ("%FRAMES_DIR%\frame_*.exr") do (
    set "INPUT_PATTERN=%FRAMES_DIR%\frame_%%04d.exr"
    echo Input format: OpenEXR ^(HDR^)
    goto :format_detected
)
echo Input format: PNG

:format_detected
REM Create output directory
for %%d in ("%OUTPUT%") do if not exist "%%~dpd" mkdir "%%~dpd"

echo.
echo =========================================================
echo   DesiMapper -- 8K 60fps Video Encode (Windows/NVENC)
echo =========================================================
echo   Input  : %FRAMES_DIR%\
echo   Output : %OUTPUT%
echo   FPS    : %FPS%
echo   Codec  : %CODEC%
echo.

if "%CODEC%"=="h265" (
    echo Encoding with H.265 NVENC (hardware, fast^)...
    ffmpeg -y ^
        -framerate %FPS% ^
        -i "%INPUT_PATTERN%" ^
        -c:v hevc_nvenc ^
        -preset p6 ^
        -cq 20 ^
        -b:v 0 ^
        -pix_fmt yuv420p ^
        -tag:v hvc1 ^
        -movflags +faststart ^
        "%OUTPUT%"

    if errorlevel 1 (
        echo WARNING: NVENC H.265 failed. Falling back to software libx265...
        echo This will be slower but produce the same quality output.
        ffmpeg -y ^
            -framerate %FPS% ^
            -i "%INPUT_PATTERN%" ^
            -c:v libx265 ^
            -crf 18 ^
            -preset slow ^
            -pix_fmt yuv420p ^
            -movflags +faststart ^
            "%OUTPUT%"
    )
) else (
    echo Encoding with H.264 NVENC (hardware, fast^)...
    ffmpeg -y ^
        -framerate %FPS% ^
        -i "%INPUT_PATTERN%" ^
        -c:v h264_nvenc ^
        -preset p6 ^
        -cq 20 ^
        -b:v 0 ^
        -pix_fmt yuv420p ^
        -movflags +faststart ^
        "%OUTPUT%"

    if errorlevel 1 (
        echo WARNING: NVENC H.264 failed. Falling back to software libx264...
        ffmpeg -y ^
            -framerate %FPS% ^
            -i "%INPUT_PATTERN%" ^
            -c:v libx264 ^
            -crf 18 ^
            -preset slow ^
            -pix_fmt yuv420p ^
            -movflags +faststart ^
            "%OUTPUT%"
    )
)

if errorlevel 1 (
    echo ERROR: Encoding failed.
    pause
    exit /b 1
)

echo.
echo Done: %OUTPUT%
echo.
echo YouTube upload checklist:
echo   [ ] Upload via YouTube Studio
echo   [ ] Title: 'The Universe as Seen by DESI -- 40 Million Galaxies in 3D (8K 60fps^)'
echo   [ ] Upload as Unlisted first to verify quality, then publish
echo   [ ] YouTube processes 8K for ~30-60 min after upload
echo.
pause
