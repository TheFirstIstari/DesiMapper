/**
 * main.ts — DesiMapper web viewer entry point.
 *
 * Orchestrates Three.js scene setup, data loading, UI wiring,
 * and the render loop.
 */

import * as THREE from "three";
import { loadGalaxyBinary, loadMetadata } from "./DataLoader";
import { GalaxyRenderer, type RenderOptions } from "./GalaxyRenderer";
import { CameraController } from "./CameraController";

// ─── Loading UI ────────────────────────────────────────────────────────────

const loadingEl = document.getElementById("loading")!;
const loadingBar = document.getElementById("loading-bar")!;
const loadingText = document.getElementById("loading-text")!;
const statsEl = document.getElementById("stats")!;

function setProgress(pct: number, label: string) {
  loadingBar.style.width = `${pct}%`;
  loadingText.textContent = label;
}

function hideLoading() {
  loadingEl.style.opacity = "0";
  setTimeout(() => { loadingEl.style.display = "none"; }, 600);
}

// ─── Scene Setup ───────────────────────────────────────────────────────────

const container = document.getElementById("canvas-container")!;
const W = window.innerWidth;
const H = window.innerHeight;

const renderer = new THREE.WebGLRenderer({ antialias: false, alpha: false });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(W, H);
renderer.setClearColor(0x000005, 1);
container.appendChild(renderer.domElement);

const scene = new THREE.Scene();

const camera = new THREE.PerspectiveCamera(60, W / H, 1, 50_000);
camera.position.set(0, 2000, 5000);

const controller = new CameraController(camera, renderer.domElement);

// Subtle background stars
function addBackgroundStars() {
  const n = 8000;
  const pos = new Float32Array(n * 3);
  for (let i = 0; i < n * 3; i++) {
    pos[i] = (Math.random() - 0.5) * 40_000;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  const mat = new THREE.PointsMaterial({ color: 0x334466, size: 1.5, sizeAttenuation: false });
  scene.add(new THREE.Points(geo, mat));
}
addBackgroundStars();

// ─── Galaxy Renderer ────────────────────────────────────────────────────────

const galaxyRenderer = new GalaxyRenderer(scene);

const renderOptions: RenderOptions = {
  pointSize: 1.5,
  opacity: 0.7,
  zCutoff: 2.1,
  hiddenTracers: new Set(),
};

// ─── UI Controls ────────────────────────────────────────────────────────────

const sizeSlider = document.getElementById("size-slider") as HTMLInputElement;
const opacitySlider = document.getElementById("opacity-slider") as HTMLInputElement;
const zSlider = document.getElementById("z-slider") as HTMLInputElement;

sizeSlider.addEventListener("input", () => {
  renderOptions.pointSize = parseFloat(sizeSlider.value);
  galaxyRenderer.update(renderOptions);
});

opacitySlider.addEventListener("input", () => {
  renderOptions.opacity = parseFloat(opacitySlider.value);
  galaxyRenderer.update(renderOptions);
});

zSlider.addEventListener("input", () => {
  renderOptions.zCutoff = parseFloat(zSlider.value);
  galaxyRenderer.update(renderOptions);
});

// Tracer toggle buttons
document.querySelectorAll<HTMLElement>(".legend-item").forEach((el) => {
  const tid = parseInt(el.dataset.tracer ?? "0", 10);
  el.addEventListener("click", () => {
    if (renderOptions.hiddenTracers.has(tid)) {
      renderOptions.hiddenTracers.delete(tid);
      el.classList.remove("hidden");
    } else {
      renderOptions.hiddenTracers.add(tid);
      el.classList.add("hidden");
    }
    galaxyRenderer.update(renderOptions);
  });
});

// ─── Resize Handling ────────────────────────────────────────────────────────

window.addEventListener("resize", () => {
  const w = window.innerWidth;
  const h = window.innerHeight;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
});

// ─── Stats ──────────────────────────────────────────────────────────────────

let frameCount = 0;
let lastFpsTime = performance.now();
let fps = 0;

function updateStats() {
  const now = performance.now();
  frameCount++;
  if (now - lastFpsTime > 500) {
    fps = Math.round((frameCount * 1000) / (now - lastFpsTime));
    frameCount = 0;
    lastFpsTime = now;
    statsEl.textContent = `${fps} fps · ${galaxyRenderer.pointCount.toLocaleString()} galaxies`;
  }
}

// ─── Render Loop ────────────────────────────────────────────────────────────

function animate() {
  requestAnimationFrame(animate);
  controller.tick();
  renderer.render(scene, camera);
  updateStats();
}

// ─── Boot ───────────────────────────────────────────────────────────────────

async function boot() {
  try {
    setProgress(5, "Loading metadata…");
    const metadata = await loadMetadata("/data/metadata.json");

    setProgress(15, `Loading ${metadata.n_points.toLocaleString()} galaxies…`);
    const data = await loadGalaxyBinary("/data/galaxies.bin", (loaded, total) => {
      const pct = total > 0 ? 15 + (loaded / total) * 75 : 50;
      setProgress(pct, `Downloading galaxy data… ${(loaded / 1e6).toFixed(1)} MB`);
    });

    setProgress(92, "Building point cloud…");
    galaxyRenderer.load(data, metadata);

    setProgress(100, "Ready");
    setTimeout(hideLoading, 300);
    animate();
  } catch (err) {
    loadingText.textContent = `Error: ${err}`;
    loadingBar.style.background = "#cc2200";
    console.error(err);
  }
}

boot();
