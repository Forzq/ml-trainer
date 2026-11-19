"use strict";

class TrainerAvatar {
  constructor({ api, storage, toast }) {
    this.api = api;
    this.storage = storage;
    this.toast = toast;
    this.images = {};
    this.reaction = "neutral";
    this.message = "Можно начинать";
    this.enabled = storage.get("ml-avatar-visible") !== "off";
    this.openMouth = false;
    this.mouthLevel = 0;
    this.pack = null;
    this.preset = "custom";
    this.presets = [];
    this.rig = null;
    this.audio = null;
    this.context = null;
    this.nodes = new WeakMap();
    this.frame = null;
    this.dialog = document.querySelector("#avatar-dialog");
    this.dialog.querySelector(".avatar-close").onclick = () => this.dialog.close();
    this.dialog.querySelector("#avatar-visible").checked = this.enabled;
    this.dialog.querySelector("#avatar-visible").onchange = (event) => {
      this.enabled = event.target.checked;
      this.storage.set("ml-avatar-visible", this.enabled ? "on" : "off");
      this.draw();
    };
    this.dialog.addEventListener("change", (event) => {
      if (event.target.matches("input[data-avatar-slot]")) this.upload(event.target);
      if (event.target.id === "avatar-preset") this.selectPreset(event.target.value);
    });
    this.dialog.addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-avatar-remove]");
      if (!button || this.uploading) return;
      button.disabled = true;
      try { this.apply(await this.api(`/avatar/images/${button.dataset.avatarRemove}`, { method: "DELETE" })); }
      catch (error) { this.toast(error.message); }
      finally { button.disabled = false; }
    });
  }

  async load() { this.apply(await this.api("/avatar")); }
  apply(config) {
    this.rig?.destroy(); this.rig?.canvas.remove(); this.rig = null;
    this.pack = config.pack || null;
    this.preset = config.preset || "custom";
    this.presets = config.presets || [{ id: "custom", name: "Свои картинки" }];
    this.images = config.images || {};
    // Warm both mouth frames so a first syllable doesn't trigger an image download.
    if (!this.pack) for (const url of new Set(Object.values(this.images))) { const image = new Image(); image.src = url; }
    this.settings();
    this.draw();
  }
  show() { this.settings(); if (!this.dialog.open) this.dialog.showModal(); }
  async selectPreset(preset) {
    if (this.uploading) return;
    const select = this.dialog.querySelector("#avatar-preset"); select.disabled = true;
    try {
      this.apply(await this.api("/avatar/preset", { method: "PUT", body: { preset } }));
      this.enabled = true; this.storage.set("ml-avatar-visible", "on");
      this.dialog.querySelector("#avatar-visible").checked = true;
      this.draw();
    } catch (error) { this.toast(error.message); select.value = this.preset; }
    finally { select.disabled = false; }
  }
  settings() {
    const select = this.dialog.querySelector("#avatar-preset");
    select.replaceChildren(...this.presets.map((item) => new Option(item.name, item.id)));
    select.value = this.preset;
    this.dialog.querySelector("#avatar-preset-info").hidden = this.preset !== "marin";
    this.dialog.querySelector("#avatar-custom-settings").hidden = this.preset !== "custom";
    if (this.preset !== "custom") { this.dialog.querySelector("#avatar-frames").replaceChildren(); return; }
    const names = { neutral: "Обычная", listening: "Слушает", thinking: "Думает", positive: "Одобряет", supportive: "Объясняет" };
    this.dialog.querySelector("#avatar-frames").innerHTML = Object.entries(names).map(([reaction, name]) => `
      <section class="avatar-frame-group"><h3>${name}${reaction === "neutral" ? " · основные картинки" : " · необязательно"}</h3><div class="avatar-frame-pair">
      ${["closed", "open"].map((mouth) => {
        const slot = `${reaction}-${mouth}`, url = this.images[slot];
        return `<div class="avatar-upload"><label><span class="avatar-thumbnail">${url ? `<img src="${url}" alt="">` : "+"}</span><span>${mouth === "closed" ? "Рот закрыт" : "Рот открыт"}</span><input type="file" accept="image/png,image/jpeg,image/webp" data-avatar-slot="${slot}" aria-label="${name}: ${mouth === "closed" ? "рот закрыт" : "рот открыт"}"></label>${url ? `<button type="button" class="text-button" data-avatar-remove="${slot}">Убрать</button>` : ""}</div>`;
      }).join("")}</div></section>`).join("");
  }
  async upload(input) {
    const file = input.files?.[0];
    if (!file || this.uploading) return;
    this.uploading = true;
    this.dialog.setAttribute("aria-busy", "true");
    this.dialog.querySelector("#avatar-upload-status").textContent = "Сохраняю картинку…";
    let bitmap;
    try {
      if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) throw new Error("Выбери PNG, JPG или WebP.");
      if (file.size > 20 * 1024 * 1024) throw new Error("Исходная картинка должна быть меньше 20 МБ.");
      bitmap = await createImageBitmap(file);
      const scale = Math.min(1, 2048 / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const png = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
      if (!png || png.size > 6 * 1024 * 1024) throw new Error("Картинка слишком большая. Попробуй уменьшить её размер.");
      const body = new FormData(); body.append("image", png, "avatar.png");
      this.apply(await this.api(`/avatar/images/${input.dataset.avatarSlot}`, { method: "PUT", body }));
      this.dialog.querySelector("#avatar-upload-status").textContent = "Картинка сохранена на этом компьютере.";
    } catch (error) {
      this.dialog.querySelector("#avatar-upload-status").textContent = error.message;
      this.toast(error.message);
    } finally {
      bitmap?.close();
      input.value = "";
      this.uploading = false;
      this.dialog.removeAttribute("aria-busy");
    }
  }
  update(reaction, message) {
    this.reaction = reaction;
    this.message = message;
    this.draw();
  }
  draw() {
    const host = document.querySelector("#trainer-avatar");
    if (!host) { this.rig?.destroy(); this.rig = null; return; }
    host.hidden = !this.enabled;
    if (!this.enabled) { this.rig?.destroy(); this.rig?.canvas.remove(); this.rig = null; return; }
    const renderer = this.pack ? "portrait" : "frames";
    if (host.dataset.renderer !== renderer) {
      this.rig?.destroy(); this.rig = null; host.replaceChildren(); host.dataset.renderer = renderer;
      delete host.dataset.rigError;
    }
    if (!host.firstElementChild) {
      host.innerHTML = `<div class="trainer-avatar-card"><div class="trainer-avatar-heading"><span>ТВОЙ ТРЕНЕР</span><button class="text-button" type="button" data-action="avatar-settings">Настроить</button></div><div class="trainer-avatar-stage"><img class="trainer-avatar-image avatar-closed" alt="Аватар тренера" hidden><img class="trainer-avatar-image avatar-open" alt="Аватар тренера говорит" hidden><div class="trainer-avatar-empty"><span aria-hidden="true">✳</span><p>Выбери своего персонажа</p><button class="button small" type="button" data-action="avatar-settings">Добавить картинки</button></div></div><p class="trainer-avatar-status" role="status"></p></div>`;
    }
    const mouth = this.openMouth ? "open" : "closed";
    host.querySelector(".trainer-avatar-heading > span").textContent = this.pack?.name || "ТВОЙ ТРЕНЕР";
    // Never borrow an open-mouth expression from a different emotion.
    const hasReaction = Boolean(this.images[`${this.reaction}-closed`]);
    const reaction = hasReaction ? this.reaction : "neutral";
    const closed = this.images[`${reaction}-closed`];
    const open = this.images[`${reaction}-open`] || closed;
    if (this.pack) {
      const base = host.querySelector(".avatar-closed");
      if (base.getAttribute("src") !== this.pack.files.base) base.src = this.pack.files.base;
      base.hidden = false;
      host.querySelector(".avatar-open").hidden = true;
      if ((!this.rig || !this.rig.canvas.isConnected) && !host.dataset.rigError) {
        this.rig?.destroy();
        const canvas = document.createElement("canvas");
        canvas.className = "trainer-portrait"; canvas.setAttribute("role", "img");
        canvas.setAttribute("aria-label", "Ментор по ML — твой ML-тренер"); canvas.hidden = true;
        let stack = host.querySelector(".trainer-portrait-stack");
        if (!stack) {
          stack = document.createElement("div"); stack.className = "trainer-portrait-stack";
          host.querySelector(".trainer-avatar-stage").append(stack); stack.append(base);
        }
        stack.append(canvas);
        this.rig = new PortraitRig(canvas, this.pack);
        const rig = this.rig;
        rig.ready.then(() => {
          if (this.rig !== rig || rig.destroyed) return;
          base.hidden = false; canvas.hidden = false;
        }).catch(() => {
          rig.destroy(); canvas.remove(); host.dataset.rigError = "true";
          if (this.rig === rig) this.rig = null;
          base.hidden = false; this.toast("Не удалось загрузить анимацию. Портрет остаётся доступен.");
        });
      }
      this.rig?.update(this.reaction, this.openMouth ? this.mouthLevel : 0);
    }
    // Keep both images mounted: mouth movement must not fetch files every frame.
    for (const [kind, url] of this.pack ? [] : [["closed", closed], ["open", open]]) {
      const image = host.querySelector(`.avatar-${kind}`);
      if (url && image.getAttribute("src") !== url) image.setAttribute("src", url);
      image.hidden = !url || kind !== mouth;
    }
    host.querySelector(".trainer-avatar-empty").hidden = Boolean(closed);
    const label = host.querySelector(".trainer-avatar-status");
    if (label.textContent !== this.message) label.textContent = this.message;
    host.dataset.reaction = this.reaction;
    host.dataset.mouth = mouth;
  }
  attachAudio(audio) {
    this.stopAudio();
    // No avatar should ever interrupt playback if Web Audio isn't available.
    if (!Object.keys(this.images).length) return;
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
