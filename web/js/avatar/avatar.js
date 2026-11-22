"use strict";

class TrainerAvatar {
  constructor({ api, storage, toast, panel, voice }) {
    this.api = api;
    this.storage = storage;
    this.toast = toast;
    this.voice = voice;
    this.reaction = "neutral";
    this.message = "Можно начинать";
    this.enabled = storage.get("ml-avatar-visible") !== "off";
    this.openMouth = false;
    this.mouthLevel = 0;
    this.pack = null;
    this.rig = null;
    this.audio = null;
    this.context = null;
    this.nodes = new WeakMap();
    this.frame = null;

    this.visibilityLabel = panel.querySelector("#avatar-visible-label");
    this.visibility = panel.querySelector("#avatar-visible");
    this.visibility.checked = this.enabled;
    this.visibility.addEventListener("change", () => {
      this.enabled = this.visibility.checked;
      this.storage.set("ml-avatar-visible", this.enabled ? "on" : "off");
      this.draw();
    });
  }

  async load() {
    const { pack } = await this.api("/avatar");
    this.pack = pack;
    this.draw();
  }

  update(reaction, message) {
    this.reaction = reaction;
    this.message = message;
    this.draw();
  }

  draw() {
    const compatible = this.voice() === "female";
    const available = compatible && Boolean(this.pack);
    this.visibility.disabled = !available;
    this.visibilityLabel.title = compatible ? "" : "Аватар доступен с женским голосом.";

    const host = document.querySelector("#trainer-avatar");
    if (host) host.hidden = !available || !this.enabled;
    if (!host || host.hidden) {
      this.rig?.destroy();
      this.rig?.canvas.remove();
      this.rig = null;
      return;
    }

    if (!host.firstElementChild) {
      host.innerHTML = `
        <div class="trainer-avatar-card">
          <div class="trainer-avatar-heading"><span></span><button class="text-button" type="button" data-action="avatar-settings">Настроить</button></div>
          <div class="trainer-avatar-stage"><div class="trainer-portrait-stack"><img class="trainer-avatar-image" alt="Аватар тренера"></div></div>
          <p class="trainer-avatar-status" role="status"></p>
        </div>`;
      host.querySelector(".trainer-avatar-heading > span").textContent = this.pack.name;
      host.querySelector(".trainer-avatar-image").src = this.pack.files.base;
    }
    if ((!this.rig || !this.rig.canvas.isConnected) && !host.dataset.rigError) {
      this.rig?.destroy();
      const canvas = document.createElement("canvas");
      canvas.className = "trainer-portrait";
      canvas.setAttribute("role", "img");
      canvas.setAttribute("aria-label", this.pack.name);
      canvas.hidden = true;
      host.querySelector(".trainer-portrait-stack").append(canvas);
      const rig = new PortraitRig(canvas, this.pack);
      this.rig = rig;
      rig.ready.then(() => {
        if (this.rig === rig && !rig.destroyed) canvas.hidden = false;
      }).catch(() => {
        if (this.rig !== rig) return;
        rig.destroy();
        canvas.remove();
        host.dataset.rigError = "true";
        this.rig = null;
        this.toast("Не удалось загрузить анимацию. Портрет остаётся доступен.");
      });
    }

    this.rig?.update(this.reaction, this.openMouth ? this.mouthLevel : 0);
    const label = host.querySelector(".trainer-avatar-status");
    if (label.textContent !== this.message) label.textContent = this.message;
    host.dataset.reaction = this.reaction;
    host.dataset.mouth = this.openMouth ? "open" : "closed";
  }
  attachAudio(audio) {
    this.stopAudio();
    // No avatar should ever interrupt playback if Web Audio isn't available.
    const host = document.querySelector("#trainer-avatar");
    if (!host || host.hidden) return;
    const Context = window.AudioContext || window.webkitAudioContext;
    if (!Context) return;
    try {
      if (!this.context || this.context.state === "closed") this.context = new Context();
      let nodes = this.nodes.get(audio);
      if (!nodes) {
        const source = this.context.createMediaElementSource(audio);
        const analyser = this.context.createAnalyser();
        analyser.fftSize = 512;
        source.connect(analyser); analyser.connect(this.context.destination);
        nodes = { source, analyser, samples: new Uint8Array(analyser.fftSize) };
        this.nodes.set(audio, nodes);
      } else {
        nodes.source.connect(nodes.analyser); nodes.analyser.connect(this.context.destination);
      }
      this.audio = audio;
      this.audioNodes = nodes;
      this.context.resume().then(() => this.animate()).catch(() => {
        // Undo Web Audio routing when the host refuses an AudioContext.
        nodes.source.disconnect(); nodes.analyser.disconnect();
        nodes.source.connect(this.context.destination);
      });
    } catch { /* Speech continues without mouth animation. */ }
  }
  animate() {
    cancelAnimationFrame(this.frame);
    const tick = () => {
      const audio = this.audio;
      if (!audio || audio.ended) { this.openMouth = false; this.draw(); return; }
      let rms = 0;
      this.audioNodes.analyser.getByteTimeDomainData(this.audioNodes.samples);
      for (const value of this.audioNodes.samples) rms += ((value - 128) / 128) ** 2;
      rms = Math.sqrt(rms / this.audioNodes.samples.length);
      const level = rms / Math.max(audio.volume, 0.05);
      const open = !audio.paused && !audio.muted && audio.volume > 0 && level > (this.openMouth ? 0.018 : 0.035);
      this.mouthLevel = open ? Math.min(1, Math.max(.15, level / .18)) : 0;
      this.rig?.update(this.reaction, this.mouthLevel);
      if (this.openMouth !== open) { this.openMouth = open; this.draw(); }
      this.frame = requestAnimationFrame(tick);
    };
    tick();
  }
  stopAudio() {
    cancelAnimationFrame(this.frame);
    this.frame = null;
    this.audio = null;
    if (this.audioNodes) {
      this.audioNodes.source.disconnect(); this.audioNodes.analyser.disconnect();
      this.audioNodes = null;
    }
    this.openMouth = false;
    this.mouthLevel = 0;
    if (this.rig) { this.rig.mouth = 0; this.rig.update(this.reaction, 0); }
    this.draw();
  }
}
