"use strict";

// A fixed body plate plus small eye/mouth layers: never alternate full portraits.
class PortraitRig {
  constructor(canvas, pack) {
    this.canvas = canvas;
    this.pack = pack;
    this.images = {};
    this.patches = {};
    this.reaction = "neutral";
    this.displayedReaction = "neutral";
    this.pendingReaction = null;
    this.mouth = 0;
    this.targetMouth = 0;
    this.nextBlink = performance.now() + 3200 + Math.random() * 2200;
    this.blinkStart = null;
    this.frame = null;
    this.destroyed = false;
    this.reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    canvas.width = pack.width;
    canvas.height = pack.height;
    this.ready = this.load();
  }
  async load() {
    await Promise.all(Object.entries(this.pack.files).map(async ([key, url]) => {
      const image = new Image(); image.src = url; await image.decode(); this.images[key] = image;
    }));
    if (this.destroyed) return;
    for (const [key, source] of Object.entries(this.pack.eyes.source)) {
      const regions = key === "blink" ? this.pack.eyes.regions.map(([x, y, w, h]) => [x, y + 55, w, h - 55]) : this.pack.eyes.regions;
      this.patches[key] = this.patch(this.images[key], source, this.pack.eyes.target.slice(2), regions);
    }
    this.patches.mouth = this.patch(this.images.mouth, this.pack.mouth.source, this.pack.mouth.target.slice(2));
    this.canvas.dataset.ready = "true";
    this.paint(performance.now());
    this.tick();
  }
  patch(image, source, size, regions = null) {
    const canvas = document.createElement("canvas"); [canvas.width, canvas.height] = size;
    const context = canvas.getContext("2d");
    context.drawImage(image, ...source, 0, 0, ...size);
    // A soft runtime mask blends skin at the edges without modifying source assets.
    const mask = document.createElement("canvas"); [mask.width, mask.height] = size;
    const brush = mask.getContext("2d");
    brush.filter = "blur(4px)"; brush.fillStyle = "white";
    for (const [x, y, width, height] of regions || [[0, 0, ...size]]) brush.fillRect(x + 7, y + 7, width - 14, height - 14);
    context.globalCompositeOperation = "destination-in"; context.drawImage(mask, 0, 0);
    return canvas;
  }
  update(reaction, level) {
    if (reaction !== this.reaction) {
      this.reaction = reaction;
      if (this.reduced || !this.images.base) { this.displayedReaction = reaction; this.pendingReaction = null; }
      else { this.pendingReaction = reaction; this.blinkStart = performance.now(); }
    }
    this.targetMouth = Math.max(0, Math.min(1, level));
  }
  paint(now) {
    if (!this.images.base) return;
    const context = this.canvas.getContext("2d");
    const scale = this.canvas.width / this.pack.width;
    context.clearRect(0, 0, this.canvas.width, this.canvas.height);
    context.save(); context.scale(scale, scale);
    // The full body stays in a separate, immutable HTML image below this canvas.
    const eyes = (reaction, opacity) => {
      const patch = this.patches[reaction];
      if (patch && opacity > 0) { context.globalAlpha = opacity; context.drawImage(patch, ...this.pack.eyes.target); }
    };
    if (this.pendingReaction && this.blinkStart !== null && now - this.blinkStart >= 90) {
      this.displayedReaction = this.pendingReaction; this.pendingReaction = null;
    }
    eyes(this.displayedReaction, 1);
    if (!this.reduced && now >= this.nextBlink && this.blinkStart === null) this.blinkStart = now;
    if (this.blinkStart !== null) {
      const elapsed = now - this.blinkStart;
      const blink = elapsed < 90 ? elapsed / 90 : elapsed < 145 ? 1 : Math.max(0, 1 - (elapsed - 145) / 110);
      eyes("blink", blink);
      if (elapsed > 255) { this.blinkStart = null; this.nextBlink = now + 3600 + Math.random() * 2600; }
    }
    context.globalAlpha = 1;
    this.mouth += (this.targetMouth - this.mouth) * .42;
    if (this.mouth > .025) {
      const [x, y, width, height] = this.pack.mouth.target;
      // Open a little for quiet syllables and wider for stressed ones.
      const opening = .65 + .35 * this.mouth;
      context.drawImage(this.patches.mouth, x, y, width, height * opening);
    }
    context.restore();
    this.canvas.dataset.reaction = this.reaction;
    this.canvas.dataset.mouth = this.targetMouth > .05 ? "open" : "closed";
  }
  tick() {
    const step = (now) => {
      if (this.destroyed || !this.canvas.isConnected) { this.destroy(); return; }
      if (now - (this.lastFrame || 0) > 32 && !document.hidden) { this.paint(now); this.lastFrame = now; }
      this.frame = requestAnimationFrame(step);
    };
    this.frame = requestAnimationFrame(step);
  }
  destroy() { this.destroyed = true; cancelAnimationFrame(this.frame); }
}
