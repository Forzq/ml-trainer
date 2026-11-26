"use strict";

class TurntableRig {
  constructor(canvas, pack) {
    this.canvas = canvas;
    this.pack = pack;
    canvas.width = pack.width;
    canvas.height = pack.height;
    this.context = canvas.getContext("2d");
    this.sheet = new Image();
    this.angle = 0;
    this.restAngle = 0;
    this.speed = 0;
    this.elapsed = 0;
    this.speaking = false;
    this.displayedFrame = -1;
    this.destroyed = false;
    this.ready = this.load();
  }

  async load() {
    this.sheet.src = this.pack.files.spin;
    await this.sheet.decode();
    if (this.destroyed) return;
    this.paint(0);
    this.canvas.dataset.ready = "true";
    if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
      this.lastTime = performance.now();
      this.frame = requestAnimationFrame(this.tick);
    }
  }

  update(speaking) {
    if (this.speaking && !speaking) this.restAngle = Math.round(this.angle);
    this.speaking = speaking;
  }

  tick = (now) => {
    if (this.destroyed || !this.canvas.isConnected) { this.destroy(); return; }
    const step = Math.min(0.05, (now - this.lastTime) / 1000);
    this.lastTime = now;
    this.elapsed += step;
    if (this.speaking) {
      const targetSpeed = 1.8 + 0.12 * Math.sin(this.elapsed * 4);
      this.speed += (targetSpeed - this.speed) * (1 - Math.exp(-step * 10));
      this.angle = (this.angle + this.speed * step) % 1;
    } else {
      this.speed = 0;
      this.angle += (this.restAngle - this.angle) * (1 - Math.exp(-step * 10));
    }
    this.paint(Math.round(this.angle * this.pack.frames) % this.pack.frames);
    const lift = 2.1 * Math.sin(this.elapsed * 1.75) + 0.7 * Math.sin(this.elapsed * 3.13);
    this.canvas.style.transform = `translateY(${lift}px)`;
    this.frame = requestAnimationFrame(this.tick);
  };

  paint(frame) {
    if (this.displayedFrame === frame) return;
    const { width, height, columns } = this.pack;
    const x = (frame % columns) * width;
    const y = Math.floor(frame / columns) * height;
    this.context.clearRect(0, 0, width, height);
    this.context.drawImage(this.sheet, x, y, width, height, 0, 0, width, height);
    this.displayedFrame = frame;
  }

  destroy() {
    this.destroyed = true;
    cancelAnimationFrame(this.frame);
  }
}
