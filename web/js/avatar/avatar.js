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
    this.preference = storage.get("ml-avatar-preset");
    this.packs = [];
    this.openMouth = false;
    this.mouthLevel = 0;
    this.speaking = false;
    this.pack = null;
    this.rig = null;
    this.audio = null;
    this.context = null;
    this.nodes = new WeakMap();
    this.frame = null;

    this.visibilityLabel = panel.querySelector("#avatar-visible-label");
    this.visibility = panel.querySelector("#avatar-visible");
    this.select = panel.querySelector("#avatar-preset");
    this.credit = panel.querySelector("#avatar-credit");
    this.visibility.checked = this.enabled;
    this.visibility.addEventListener("change", () => {
      this.enabled = this.visibility.checked;
      this.storage.set("ml-avatar-visible", this.enabled ? "on" : "off");
      this.draw();
    });
    this.select.addEventListener("change", () => {
      this.preference = this.select.value;
      this.storage.set("ml-avatar-preset", this.preference);
      this.draw();
    });
  }

  async load() {
    const { pack, packs } = await this.api("/avatar");
    this.packs = packs ?? (pack ? [pack] : []);
    this.select.replaceChildren(...this.packs.map(({ id, name }) => new Option(name, id)));
    this.draw();
  }

  update(reaction, message, speaking = false) {
    this.reaction = reaction;
    this.message = message;
    this.speaking = speaking;
    this.draw();
  }

  clearRig() {
    this.rig?.destroy();
    this.rig?.canvas.remove();
    this.rig = null;
  }

  draw() {
    const voice = this.voice();
    const compatible = this.packs.filter(({ voices = ["female"] }) => voices.includes(voice));
    this.pack = compatible.find(({ id }) => id === this.preference) ?? compatible[0] ?? null;
    const available = Boolean(this.pack);
    this.visibility.disabled = !available;
    this.visibilityLabel.title = available ? "" : "Для этого голоса нет доступного аватара.";
    this.select.disabled = !available;
    for (const option of this.select.options) option.disabled = !compatible.some(({ id }) => id === option.value);
    this.select.value = this.pack?.id ?? "";
    this.credit.hidden = this.pack?.id !== "oiia";

    const host = document.querySelector("#trainer-avatar");
    if (host) host.hidden = !available || !this.enabled;
    if (!host || host.hidden) {
      this.clearRig();
      return;
    }

    const turntable = this.pack.kind === "turntable";
    if (host.dataset.preset !== this.pack.id) {
      this.clearRig();
      host.dataset.preset = this.pack.id;
      delete host.dataset.rigError;
      host.innerHTML = `
        <div class="trainer-avatar-card">
          <div class="trainer-avatar-heading"><span></span><button class="text-button" type="button" data-action="avatar-settings">Настроить</button></div>
          <div class="trainer-avatar-stage"><div class="trainer-portrait-stack${turntable ? " trainer-turntable" : ""}"><img class="trainer-avatar-image" alt=""></div></div>
          <p class="trainer-avatar-status" role="status"></p>
        </div>`;
      host.querySelector(".trainer-avatar-heading > span").textContent = this.pack.name;
      const image = host.querySelector(".trainer-avatar-image");
      image.alt = this.pack.name;
      image.src = this.pack.files.base;
    }
    if ((!this.rig || !this.rig.canvas.isConnected) && !host.dataset.rigError) {
      this.clearRig();
      const canvas = document.createElement("canvas");
      canvas.className = "trainer-portrait";
      canvas.setAttribute("role", "img");
      canvas.setAttribute("aria-label", this.pack.name);
      canvas.hidden = true;
      host.querySelector(".trainer-portrait-stack").append(canvas);
      const rig = turntable ? new TurntableRig(canvas, this.pack) : new PortraitRig(canvas, this.pack);
      this.rig = rig;
      rig.ready.then(() => {
        if (this.rig === rig && !rig.destroyed) canvas.hidden = false;
      }).catch(() => {
        if (this.rig !== rig) return;
        rig.destroy();
        canvas.remove();
        host.dataset.rigError = "true";
        this.rig = null;
        this.toast("Не удалось загрузить анимацию. Изображение аватара доступно.");
      });
    }

    if (turntable) this.rig?.update(this.speaking);
    else this.rig?.update(this.reaction, this.openMouth ? this.mouthLevel : 0);
    const label = host.querySelector(".trainer-avatar-status");
    if (label.textContent !== this.message) label.textContent = this.message;
    host.dataset.reaction = turntable ? "neutral" : this.reaction;
    host.dataset.mouth = !turntable && this.openMouth ? "open" : "closed";
  }
  attachAudio(audio) {
    this.stopAudio();
    // No avatar should ever interrupt playback if Web Audio isn't available.
    const host = document.querySelector("#trainer-avatar");
    if (!host || host.hidden || this.pack?.kind === "turntable") return;
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
    if (this.rig instanceof PortraitRig) this.rig.mouth = 0;
    this.draw();
  }
}
