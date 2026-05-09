/**
 * CameraController.ts — Orbit + pan camera controls for the galaxy viewer.
 *
 * Implements touch-friendly orbit, zoom, and pan without external dependencies.
 * Designed for exploring a galaxy point cloud: smooth inertia, min/max distance clamps.
 */

import * as THREE from "three";

const HALF_PI = Math.PI / 2 - 0.001;

export class CameraController {
  private camera: THREE.PerspectiveCamera;
  private domElement: HTMLElement;

  // Spherical coordinates around target
  private theta = Math.PI * 0.3;   // azimuth
  private phi = Math.PI * 0.35;    // polar angle
  private radius = 4000;            // distance in Mpc

  private target = new THREE.Vector3(0, 0, 0);

  // Interaction state
  private isDragging = false;
  private lastX = 0;
  private lastY = 0;

  // Inertia
  private dTheta = 0;
  private dPhi = 0;
  private damping = 0.88;

  // Zoom
  private minRadius = 50;
  private maxRadius = 20_000;

  constructor(camera: THREE.PerspectiveCamera, domElement: HTMLElement) {
    this.camera = camera;
    this.domElement = domElement;
    this.bindEvents();
    this.updateCamera();
  }

  private bindEvents(): void {
    const el = this.domElement;

    el.addEventListener("mousedown", this.onMouseDown);
    window.addEventListener("mousemove", this.onMouseMove);
    window.addEventListener("mouseup", this.onMouseUp);
    el.addEventListener("wheel", this.onWheel, { passive: false });

    // Touch
    el.addEventListener("touchstart", this.onTouchStart, { passive: true });
    el.addEventListener("touchmove", this.onTouchMove, { passive: false });
    el.addEventListener("touchend", this.onTouchEnd, { passive: true });
  }

  private onMouseDown = (e: MouseEvent) => {
    this.isDragging = true;
    this.lastX = e.clientX;
    this.lastY = e.clientY;
  };

  private onMouseMove = (e: MouseEvent) => {
    if (!this.isDragging) return;
    const dx = e.clientX - this.lastX;
    const dy = e.clientY - this.lastY;
    this.lastX = e.clientX;
    this.lastY = e.clientY;

    this.dTheta = -dx * 0.004;
    this.dPhi = -dy * 0.004;
    this.theta += this.dTheta;
    this.phi = Math.max(-HALF_PI, Math.min(HALF_PI, this.phi + this.dPhi));
  };

  private onMouseUp = () => {
    this.isDragging = false;
  };

  private onWheel = (e: WheelEvent) => {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 1.1 : 0.9;
    this.radius = Math.max(this.minRadius, Math.min(this.maxRadius, this.radius * factor));
  };

  // Touch support
  private lastTouchDist = 0;

  private onTouchStart = (e: TouchEvent) => {
    if (e.touches.length === 1) {
      this.isDragging = true;
      this.lastX = e.touches[0].clientX;
      this.lastY = e.touches[0].clientY;
    } else if (e.touches.length === 2) {
      this.lastTouchDist = this.getTouchDist(e);
    }
  };

  private onTouchMove = (e: TouchEvent) => {
    e.preventDefault();
    if (e.touches.length === 1 && this.isDragging) {
      const dx = e.touches[0].clientX - this.lastX;
      const dy = e.touches[0].clientY - this.lastY;
      this.lastX = e.touches[0].clientX;
      this.lastY = e.touches[0].clientY;
      this.theta -= dx * 0.004;
      this.phi = Math.max(-HALF_PI, Math.min(HALF_PI, this.phi - dy * 0.004));
    } else if (e.touches.length === 2) {
      const dist = this.getTouchDist(e);
      const factor = this.lastTouchDist / dist;
      this.radius = Math.max(this.minRadius, Math.min(this.maxRadius, this.radius * factor));
      this.lastTouchDist = dist;
    }
  };

  private onTouchEnd = () => {
    this.isDragging = false;
  };

  private getTouchDist(e: TouchEvent): number {
    const dx = e.touches[0].clientX - e.touches[1].clientX;
    const dy = e.touches[0].clientY - e.touches[1].clientY;
    return Math.sqrt(dx * dx + dy * dy);
  }

  private updateCamera(): void {
    const x = this.radius * Math.cos(this.phi) * Math.sin(this.theta);
    const y = this.radius * Math.sin(this.phi);
    const z = this.radius * Math.cos(this.phi) * Math.cos(this.theta);

    this.camera.position.set(
      this.target.x + x,
      this.target.y + y,
      this.target.z + z
    );
    this.camera.lookAt(this.target);
  }

  tick(): void {
    if (!this.isDragging) {
      this.theta += this.dTheta;
      this.phi += this.dPhi;
      this.phi = Math.max(-HALF_PI, Math.min(HALF_PI, this.phi));
      this.dTheta *= this.damping;
      this.dPhi *= this.damping;
    }
    this.updateCamera();
  }

  dispose(): void {
    const el = this.domElement;
    el.removeEventListener("mousedown", this.onMouseDown);
    window.removeEventListener("mousemove", this.onMouseMove);
    window.removeEventListener("mouseup", this.onMouseUp);
    el.removeEventListener("wheel", this.onWheel);
  }
}
