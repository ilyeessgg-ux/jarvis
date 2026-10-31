/* ═══════════════════════════════════════════════════════════════════
   J.A.R.V.I.S. HUD controller — SSE, reactor, waveform, transcript
   ═══════════════════════════════════════════════════════════════════ */

(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const ui = {
    boot: $("#boot"),
    bootBar: $("#boot-bar"),
    bootLog: $("#boot-log"),
    transcript: $("#transcript"),
    command: $("#command-input"),
    stateLabel: $("#state-label"),
    stateDetail: $("#state-detail"),
    reactor: $("#reactor"),
    reactorMode: $("#reactor-mode"),
    wave: $("#wave"),
    quickActions: $("#quick-actions"),
    reminders: $("#reminders"),
    settingsModal: $("#settings-modal"),
    lightbox: $("#lightbox"),
    lightboxImg: $("#lightbox-img"),
    toasts: $("#toasts"),
    stopBtn: $("#stop-btn"),
    pttBtn: $("#ptt-btn"),
    wakeToggle: $("#wake-toggle"),
    voiceToggle: $("#voice-toggle"),
    footerStatus: $("#footer-status"),
    hint: $("#hint-text"),
    latency: $("#latency"),
    weatherChip: $("#weather-chip"),
    weatherTemp: $("#weather-temp"),
    weatherCity: $("#weather-city"),
    llmPill: $("#pill-llm"),
    micPill: $("#pill-mic"),
    systemPill: $("#pill-system"),
  };

  const state = {
    settings: {},
    voices: [],
    quick: [],
    stats: {},
    audio: { available: false },
    llm: { configured: false },
    currentState: "boot",
    level: 0,
    streaming: new Map(),
    toolEvents: new Map(),
    lastAudioError: "",
    es: null,
    reconnectTimer: null,
  };

  const emptyTemplate = $("#log-empty") ? $("#log-empty").outerHTML : "";

  /* ───────────────────────────── utilities ───────────────────────────── */

  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

  function timeLabel(timestamp) {
    const date = timestamp ? new Date(timestamp * 1000) : new Date();
    return date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false });
  }

  function escapeText(value) {
    return String(value == null ? "" : value);
  }

  function api(path, body = null, method = "POST") {
    const options = { method, headers: {} };
    if (body !== null) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    return fetch(path, options).then(async (response) => {
      let payload = {};
      try {
        payload = await response.json();
      } catch (_) {
        /* ignore */
      }
      if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
      return payload;
    });
  }

  function toast(text, level = "info", title = "SYSTEM") {
    if (!text) return;
    const element = document.createElement("div");
    element.className = `toast ${level}`;
    const heading = document.createElement("b");
    heading.textContent = title;
    const body = document.createElement("div");
    body.textContent = text;
    element.append(heading, body);
    ui.toasts.appendChild(element);
    const remove = () => {
      element.classList.add("leaving");
      setTimeout(() => element.remove(), 260);
    };
    setTimeout(remove, level === "error" ? 8000 : 5200);
    element.addEventListener("click", remove);
  }

  function scrollTranscript(force = false) {
    const distance = ui.transcript.scrollHeight - ui.transcript.scrollTop - ui.transcript.clientHeight;
    if (force || distance < 140) ui.transcript.scrollTop = ui.transcript.scrollHeight;
  }

  function removeEmpty() {
    const empty = $("#log-empty");
    if (empty) empty.remove();
  }

  function showEmpty() {
    if (!emptyTemplate) return;
    ui.transcript.innerHTML = emptyTemplate;
  }

  /* ───────────────────────────── boot ───────────────────────────── */

  const bootLines = [
    ["INITIALISING STARK OS KERNEL", "ok"],
    ["NEURAL LATTICE ................ ONLINE", "ok"],
    ["VOICE INTERFACE ............... ARMED", "gold"],
    ["ARC REACTOR ................... STABLE", "ok"],
    ["MEMORY CORE ................... MOUNTED", "ok"],
    ["OPENROUTER UPLINK ............. READY", "gold"],
    ["WELCOME BACK, SIR.", "gold"],
  ];

  let bootFinished = false;
  const bootTimers = [];

  function finishBoot() {
    if (bootFinished) return;
    bootFinished = true;
    bootTimers.forEach(clearTimeout);
    ui.bootBar.style.width = "100%";
    ui.boot.classList.add("done");
    setTimeout(() => {
      ui.boot.style.display = "none";
      ui.command.focus();
    }, 850);
  }

  function runBoot() {
    if (reduceMotion) {
      finishBoot();
      return;
    }
    ui.bootBar.style.width = "8%";
    bootLines.forEach(([line, tone], index) => {
      const timer = setTimeout(() => {
        const row = document.createElement("div");
        row.className = tone;
        row.textContent = `> ${line}`;
        ui.bootLog.appendChild(row);
        ui.bootBar.style.width = `${12 + ((index + 1) / bootLines.length) * 82}%`;
      }, 240 + index * 330);
      bootTimers.push(timer);
    });
    bootTimers.push(setTimeout(finishBoot, 240 + bootLines.length * 330 + 700));
  }

  ui.boot.addEventListener("click", finishBoot);
  document.addEventListener("keydown", (event) => {
    if (!bootFinished) {
      finishBoot();
      return;
    }
    if (event.key === "Escape") {
      closeSettings();
      closeLightbox();
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      ui.command.focus();
    }
  });

  /* ───────────────────────────── starfield ───────────────────────────── */

  const starsCanvas = $("#starfield");
  const starsCtx = starsCanvas.getContext("2d");
  let starList = [];
  let starsWidth = 0;
  let starsHeight = 0;

  function resizeStars() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    starsWidth = window.innerWidth;
    starsHeight = window.innerHeight;
    starsCanvas.width = Math.floor(starsWidth * dpr);
    starsCanvas.height = Math.floor(starsHeight * dpr);
    starsCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const count = Math.floor((starsWidth * starsHeight) / 16000);
    starList = Array.from({ length: clamp(count, 55, 150) }, () => ({
      x: Math.random() * starsWidth,
      y: Math.random() * starsHeight,
      r: Math.random() * 1.1 + 0.25,
      depth: Math.random() * 0.7 + 0.3,
      speed: Math.random() * 0.045 + 0.008,
      gold: Math.random() < 0.08,
    }));
  }

  function drawStars(time) {
    starsCtx.clearRect(0, 0, starsWidth, starsHeight);
    for (const star of starList) {
      star.y += star.speed * star.depth;
      if (star.y > starsHeight + 2) {
        star.y = -2;
        star.x = Math.random() * starsWidth;
      }
      const alpha = 0.18 + star.depth * 0.45 + Math.sin(time * 0.001 + star.x) * 0.08;
      starsCtx.beginPath();
      starsCtx.arc(star.x, star.y, star.r, 0, Math.PI * 2);
      starsCtx.fillStyle = star.gold
        ? `rgba(255, 199, 107, ${alpha * 0.8})`
        : `rgba(120, 225, 255, ${alpha})`;
      starsCtx.fill();
    }
    if (!reduceMotion) requestAnimationFrame(drawStars);
  }

  /* ───────────────────────────── reactor ticks ───────────────────────────── */

  function buildTicks() {
    const group = $("#ticks");
    if (!group) return;
    const ns = "http://www.w3.org/2000/svg";
    for (let index = 0; index < 72; index += 1) {
      const angle = (index / 72) * Math.PI * 2;
      const major = index % 6 === 0;
      const inner = major ? 193 : 198;
      const outer = 204;
      const line = document.createElementNS(ns, "line");
      line.setAttribute("x1", 210 + Math.cos(angle) * inner);
      line.setAttribute("y1", 210 + Math.sin(angle) * inner);
      line.setAttribute("x2", 210 + Math.cos(angle) * outer);
      line.setAttribute("y2", 210 + Math.sin(angle) * outer);
      line.setAttribute("stroke-opacity", major ? "0.55" : "0.2");
      group.appendChild(line);
    }
  }

  /* ───────────────────────────── waveform ───────────────────────────── */

  const waveCanvas = ui.wave;
  const waveCtx = waveCanvas.getContext("2d");
  const waveHistory = new Array(72).fill(0.02);
  let waveWidth = 0;
  let waveHeight = 0;

  function resizeWave() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rect = waveCanvas.getBoundingClientRect();
    waveWidth = rect.width;
    waveHeight = rect.height;
    waveCanvas.width = Math.floor(waveWidth * dpr);
    waveCanvas.height = Math.floor(waveHeight * dpr);
    waveCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function accentColor() {
    const style = getComputedStyle(document.querySelector(".stage"));
    return style.getPropertyValue("--accent").trim() || "#63e6ff";
  }

  function drawWave(time) {
    if (!waveWidth || !waveHeight) {
      requestAnimationFrame(drawWave);
      return;
    }
    waveCtx.clearRect(0, 0, waveWidth, waveHeight);
    const accent = accentColor();
    const current = document.body.dataset.state;
    const center = waveHeight / 2;
    const bars = 64;
    const gap = 2;
    const barWidth = Math.max(1.5, (waveWidth - gap * (bars - 1)) / bars);
    const step = barWidth + gap;

    waveCtx.save();
    waveCtx.shadowBlur = 9;
    waveCtx.shadowColor = accent;
    waveCtx.fillStyle = accent;
    waveCtx.globalAlpha = 0.82;

    for (let index = 0; index < bars; index += 1) {
      let amplitude;
      if (current === "speaking") {
        amplitude =
          0.2 +
          Math.abs(Math.sin(time * 0.006 + index * 0.45)) * 0.22 +
          Math.abs(Math.sin(time * 0.017 + index * 1.7)) * 0.12;
      } else if (current === "listening" || current === "recording") {
        amplitude = Math.max(0.03, waveHistory[index] * 2.1);
      } else if (current === "thinking" || current === "transcribing") {
        amplitude = 0.06 + Math.abs(Math.sin(time * 0.003 + index * 0.35)) * 0.09;
      } else {
        amplitude = 0.045 + Math.abs(Math.sin(time * 0.0014 + index * 0.22)) * 0.05;
      }
      const height = clamp(amplitude * waveHeight * 0.72, 2, waveHeight * 0.88);
      const x = index * step;
      waveCtx.fillRect(x, center - height / 2, barWidth, height);
    }
    waveCtx.restore();

    waveCtx.save();
    waveCtx.strokeStyle = accent;
    waveCtx.globalAlpha = 0.13;
    waveCtx.lineWidth = 1;
    waveCtx.beginPath();
    waveCtx.moveTo(0, center + 0.5);
    waveCtx.lineTo(waveWidth, center + 0.5);
    waveCtx.stroke();
    waveCtx.restore();

    if (!reduceMotion) requestAnimationFrame(drawWave);
  }

  function pushLevel(level) {
    state.level = clamp(Number(level) || 0, 0, 1);
    waveHistory.push(state.level);
    if (waveHistory.length > 72) waveHistory.shift();
    ui.reactor.style.setProperty("--level", state.level.toFixed(3));
    setTimeout(() => {
      if (state.currentState === "idle") ui.reactor.style.setProperty("--level", "0.04");
    }, 240);
  }

  /* ───────────────────────────── state presentation ───────────────────────────── */

  const STATE_COPY = {
    boot: ["INITIALISING", "Bringing systems online…"],
    idle: ["STANDING BY", "Say “Hey Jarvis” or type a command below."],
    listening: ["LISTENING", "Voice link open — speak now."],
    recording: ["LISTENING", "Voice link open — speak now."],
    transcribing: ["DECODING", "Transcribing voice input…"],
    thinking: ["PROCESSING", "Consulting the neural core…"],
    speaking: ["RESPONDING", "Voice channel active."],
    error: ["SYSTEM FAULT", "A subsystem requires attention."],
  };

  const REACTOR_COPY = {
    boot: "INIT",
    idle: "STANDBY",
    listening: "LISTEN",
    recording: "LISTEN",
    transcribing: "DECODE",
    thinking: "COMPUTE",
    speaking: "OUTPUT",
    error: "FAULT",
  };

  function setState(name, detail = "") {
    const next = STATE_COPY[name] ? name : "idle";
    state.currentState = next;
    document.body.dataset.state = next;
    const [label, defaultDetail] = STATE_COPY[next];
    ui.stateLabel.textContent = label;
    ui.stateDetail.textContent = detail || defaultDetail;
    ui.reactorMode.textContent = REACTOR_COPY[next] || "STANDBY";

    const systemText = {
      boot: "BOOT",
      idle: "ONLINE",
      listening: "LISTENING",
      recording: "LISTENING",
      transcribing: "DECODING",
      thinking: "PROCESSING",
      speaking: "SPEAKING",
      error: "FAULT",
    }[next];
    $("#sys-state").textContent = systemText;
    ui.systemPill.classList.toggle("warn", ["listening", "recording", "transcribing", "thinking"].includes(next));
    ui.systemPill.classList.toggle("off", next === "error");

    const footer = {
      boot: "INITIALISING SYSTEMS",
      idle: "ALL SYSTEMS NOMINAL",
      listening: "VOICE CHANNEL OPEN",
      recording: "VOICE CHANNEL OPEN",
      transcribing: "DECODING AUDIO",
      thinking: "NEURAL CORE ACTIVE",
      speaking: "VOICE SYNTHESIS ACTIVE",
      error: "SYSTEM FAULT",
    }[next];
    ui.footerStatus.innerHTML = "<i></i>";
    ui.footerStatus.append(document.createTextNode(` ${footer}`));
    ui.footerStatus.classList.toggle("warn", ["listening", "recording", "transcribing", "thinking"].includes(next));
    ui.footerStatus.classList.toggle("error", next === "error");

    ui.stopBtn.classList.toggle("hidden", !["thinking", "speaking", "transcribing"].includes(next));
    ui.pttBtn.classList.toggle("active", ["listening", "recording"].includes(next));
    const hints = {
      boot: "SYSTEMS INITIALISING",
      idle: "VOICE LINK ARMED",
      listening: "RECORDING — SPEAK NOW",
      recording: "RECORDING — SPEAK NOW",
      transcribing: "PROCESSING VOICE INPUT",
      thinking: "NEURAL CORE ACTIVE",
      speaking: "VOICE SYNTHESIS ACTIVE",
      error: "SUBSYSTEM FAULT",
    };
    ui.hint.textContent = hints[next] || "VOICE LINK ARMED";
  }

  function updateMicPill() {
    const text = $("#mic-state");
    if (!state.audio || !state.audio.available) {
      text.textContent = "OFFLINE";
      ui.micPill.classList.add("off");
      ui.micPill.classList.remove("warn");
      return;
    }
    if (!state.settings.wake_enabled) {
      text.textContent = "STANDBY";
      ui.micPill.classList.add("warn");
      ui.micPill.classList.remove("off");
      return;
    }
    text.textContent = "ARMED";
    ui.micPill.classList.remove("off", "warn");
  }

  function updateLlmPill() {
    const text = $("#llm-state");
    if (state.llm && state.llm.configured) {
      text.textContent = "READY";
      ui.llmPill.classList.remove("off", "warn");
    } else {
      text.textContent = "NO KEY";
      ui.llmPill.classList.add("off");
    }
  }

  /* ───────────────────────────── transcript ───────────────────────────── */

  function messageElement(role, text, id, timestamp, streaming = false) {
    const wrap = document.createElement("div");
    wrap.className = `msg ${role}${streaming ? " streaming" : ""}`;
    if (id) wrap.dataset.id = id;

    const head = document.createElement("div");
    head.className = "msg-head";
    const roleLabel = document.createElement("span");
    roleLabel.className = "msg-role";
    roleLabel.textContent = role === "user" ? "YOU" : "J.A.R.V.I.S.";
    const time = document.createElement("time");
    time.textContent = timeLabel(timestamp);
    head.append(roleLabel, time);

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = escapeText(text);

    wrap.append(head, bubble);
    return wrap;
  }

  function addMessage(role, text, id = null, timestamp = null) {
    removeEmpty();
    const element = messageElement(role, text, id, timestamp);
    ui.transcript.appendChild(element);
    trimTranscript();
    scrollTranscript(role === "assistant" || role === "user");
    return element;
  }

  function ensureStreaming(id) {
    if (state.streaming.has(id)) return state.streaming.get(id);
    removeEmpty();
    const element = messageElement("assistant", "", id, null, true);
    ui.transcript.appendChild(element);
    state.streaming.set(id, element);
    trimTranscript();
    scrollTranscript();
    return element;
  }

  function appendDelta(id, text) {
    const element = ensureStreaming(id);
    const bubble = element.querySelector(".bubble");
    bubble.textContent += text;
    scrollTranscript();
  }

  function finalizeAssistant(id, text) {
    let element = state.streaming.get(id);
    if (element) {
      element.classList.remove("streaming");
      element.querySelector(".bubble").textContent = text;
      state.streaming.delete(id);
    } else {
      element = addMessage("assistant", text, id);
    }
    scrollTranscript(true);
  }

  function discardAssistant(id) {
    const element = state.streaming.get(id);
    if (element) {
      element.remove();
      state.streaming.delete(id);
    }
  }

  function toolIcon(ok, pending) {
    if (pending) {
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="8" stroke-dasharray="3 4"/><circle cx="12" cy="12" r="2" fill="currentColor" stroke="none"/></svg>';
    }
    if (ok) {
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m5 12 4 4L19 6"/></svg>';
    }
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 7v6M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>';
  }

  function addToolEvent(id, name, ok, message, duration) {
    removeEmpty();
    let element = state.toolEvents.get(id);
    if (!element) {
      element = document.createElement("div");
      element.className = "tool-event";
      element.dataset.id = id;
      const icon = document.createElement("span");
      icon.className = "tool-icon";
      const nameSpan = document.createElement("span");
      nameSpan.className = "tool-name";
      const messageSpan = document.createElement("span");
      messageSpan.className = "tool-msg";
      const durationSpan = document.createElement("span");
      durationSpan.className = "tool-dur";
      element.append(icon, nameSpan, messageSpan, durationSpan);
      ui.transcript.appendChild(element);
      state.toolEvents.set(id, element);
    }
    element.classList.toggle("ok", ok === true);
    element.classList.toggle("fail", ok === false);
    element.querySelector(".tool-icon").innerHTML = toolIcon(ok, ok === null);
    element.querySelector(".tool-name").textContent = name.replace(/_/g, " ").toUpperCase();
    element.querySelector(".tool-msg").textContent = message ? `· ${message}` : "";
    element.querySelector(".tool-dur").textContent = duration != null ? `${duration.toFixed ? duration.toFixed(1) : duration}s` : "";
    trimTranscript();
    scrollTranscript();
  }

  function addArtifact(artifact) {
    if (!artifact || !artifact.url) return;
    removeEmpty();
    const wrap = document.createElement("div");
    wrap.className = "msg assistant";
    const head = document.createElement("div");
    head.className = "msg-head";
    head.innerHTML = '<span class="msg-role">VISUAL FEED</span>';
    const image = document.createElement("img");
    image.className = "msg-artifact";
    image.src = artifact.url;
    image.alt = artifact.name || "Screenshot";
    image.loading = "lazy";
    image.addEventListener("click", () => openLightbox(artifact.url));
    wrap.append(head, image);
    ui.transcript.appendChild(wrap);
    trimTranscript();
    scrollTranscript(true);
  }

  function trimTranscript() {
    while (ui.transcript.children.length > 180) {
      ui.transcript.firstElementChild.remove();
    }
  }

  function renderHistory(history) {
    state.streaming.clear();
    state.toolEvents.clear();
    ui.transcript.innerHTML = "";
    if (!history || !history.length) {
      showEmpty();
      return;
    }
    for (const item of history) {
      if (item.role === "user" || item.role === "assistant") {
        ui.transcript.appendChild(messageElement(item.role, item.content, null, item.ts));
      }
    }
    scrollTranscript(true);
  }

  /* ───────────────────────────── reminders / stats / quick ───────────────────────────── */

  function renderReminders(reminders) {
    ui.reminders.innerHTML = "";
    if (!reminders || !reminders.length) {
      const empty = document.createElement("div");
      empty.className = "empty-line";
      empty.textContent = "NO ACTIVE REMINDERS";
      const hint = document.createElement("div");
      hint.className = "empty-hint";
      hint.textContent = "Ask “remind me to…” or use the button below.";
      ui.reminders.append(empty, hint);
      return;
    }
    for (const reminder of reminders) {
      const item = document.createElement("div");
      item.className = "reminder-item";
      item.dataset.id = reminder.id;
      const dot = document.createElement("i");
      const text = document.createElement("div");
      const title = document.createElement("b");
      title.textContent = reminder.text;
      const due = document.createElement("span");
      due.textContent = reminder.due;
      text.append(title, due);
      item.append(dot, text);
      ui.reminders.appendChild(item);
    }
  }

  function updateStats(stats) {
    if (!stats) return;
    state.stats = { ...state.stats, ...stats };
    $("#stat-messages").textContent = stats.messages ?? state.stats.messages ?? 0;
    $("#stat-facts").textContent = stats.facts ?? state.stats.facts ?? 0;
    $("#stat-notes").textContent = stats.notes ?? state.stats.notes ?? 0;
    $("#stat-reminders").textContent = stats.reminders ?? state.stats.reminders ?? 0;
    const modalStats = $("#modal-stats");
    if (modalStats) {
      modalStats.innerHTML = "";
      const bits = [
        ["DIALOGUES", state.stats.messages ?? 0],
        ["FACTS", state.stats.facts ?? 0],
        ["NOTES", state.stats.notes ?? 0],
        ["TASKS", state.stats.reminders ?? 0],
      ];
      for (const [label, value] of bits) {
        const span = document.createElement("span");
        span.textContent = `${label} `;
        const bold = document.createElement("b");
        bold.textContent = value;
        span.appendChild(bold);
        modalStats.appendChild(span);
      }
    }
  }

  function renderQuick(prompts) {
    ui.quickActions.innerHTML = "";
    for (const prompt of prompts || []) {
      const button = document.createElement("button");
      button.className = "quick-chip";
      button.textContent = prompt;
      button.addEventListener("click", () => sendCommand(prompt));
      ui.quickActions.appendChild(button);
    }
  }

  /* ───────────────────────────── settings ───────────────────────────── */

  function populateVoices() {
    const select = $("#set-voice");
    const current = state.settings.voice || "en-GB-RyanNeural";
    select.innerHTML = "";
    const voices = state.voices && state.voices.length
      ? state.voices
      : [{ id: current, label: current }];
    let found = false;
    for (const voice of voices) {
      const option = document.createElement("option");
      option.value = voice.id;
      option.textContent = voice.label;
      if (voice.id === current) found = true;
      select.appendChild(option);
    }
    if (!found) {
      const option = document.createElement("option");
      option.value = current;
      option.textContent = current;
      select.appendChild(option);
    }
    select.value = current;
  }

  function applySettings(settings, options = {}) {
    if (!settings) return;
    state.settings = { ...state.settings, ...settings };
    ui.wakeToggle.setAttribute("aria-checked", String(Boolean(state.settings.wake_enabled)));
    $("#set-wake").setAttribute("aria-checked", String(Boolean(state.settings.wake_enabled)));
    $("#set-speak").setAttribute("aria-checked", String(Boolean(state.settings.speak_replies)));
    const voiceOn = Boolean(state.settings.speak_replies);
    ui.voiceToggle.classList.toggle("muted", !voiceOn);
    ui.voiceToggle.querySelector("span").textContent = voiceOn ? "VOICE ON" : "VOICE OFF";
    $("#set-user").value = state.settings.user_name || "sir";
    $("#set-city").value = state.settings.city || "London";
    $("#set-model").value = state.settings.model || "";
    $("#set-threshold").value = state.settings.wake_threshold ?? 0.55;
    $("#threshold-val").textContent = Number(state.settings.wake_threshold ?? 0.55).toFixed(2);
    populateVoices();
    updateMicPill();
    if (!options.silent) updateLlmPill();
  }

  function openSettings() {
    applySettings(state.settings);
    updateStats(state.stats);
    ui.settingsModal.hidden = false;
  }

  function closeSettings() {
    ui.settingsModal.hidden = true;
  }

  async function saveSettings() {
    const payload = {
      user_name: $("#set-user").value.trim(),
      city: $("#set-city").value.trim(),
      model: $("#set-model").value.trim(),
      voice: $("#set-voice").value,
      wake_threshold: Number($("#set-threshold").value),
      wake_enabled: $("#set-wake").getAttribute("aria-checked") === "true",
      speak_replies: $("#set-speak").getAttribute("aria-checked") === "true",
    };
    try {
      const response = await api("/api/settings", payload);
      applySettings(response.settings);
      toast("Configuration saved.", "success", "CONFIG");
      setTimeout(closeSettings, 450);
    } catch (error) {
      toast(error.message, "error", "CONFIG");
    }
  }

  /* ───────────────────────────── actions ───────────────────────────── */

  async function sendCommand(text) {
    const value = (text ?? ui.command.value).trim();
    if (!value) return;
    ui.command.value = "";
    try {
      await api("/api/ask", { text: value });
      setState("thinking", "Consulting the neural core…");
    } catch (error) {
      toast(error.message, "error", "UPLINK");
    }
  }

  async function startListening() {
    if (!state.audio || !state.audio.available) {
      toast("No microphone is available. Use the text console instead.", "warn", "VOICE");
      ui.command.focus();
      return;
    }
    try {
      await api("/api/listen", {});
      setState("listening", "Voice link open — speak now.");
    } catch (error) {
      toast(error.message, "error", "VOICE");
    }
  }

  async function stopAll() {
    try {
      await api("/api/stop", {});
      setState("idle");
    } catch (error) {
      toast(error.message, "error", "SYSTEM");
    }
  }

  async function toggleWake() {
    const next = !state.settings.wake_enabled;
    try {
      const response = await api("/api/settings", { wake_enabled: next });
      applySettings(response.settings);
      toast(next ? "Wake word armed. Say “Hey Jarvis”." : "Wake word paused.", next ? "success" : "warn", "VOICE");
    } catch (error) {
      toast(error.message, "error", "VOICE");
    }
  }

  async function toggleVoice() {
    const next = !state.settings.speak_replies;
    try {
      const response = await api("/api/settings", { speak_replies: next });
      applySettings(response.settings);
      if (!next) {
        await api("/api/stop", {});
        toast("Spoken responses muted.", "warn", "VOICE");
      } else {
        toast("Spoken responses enabled.", "success", "VOICE");
      }
    } catch (error) {
      toast(error.message, "error", "VOICE");
    }
  }

  async function clearHistory() {
    if (!window.confirm("Clear the entire conversation log? Memory facts, notes, and reminders are kept.")) return;
    try {
      await api("/api/clear", {});
      state.streaming.clear();
      state.toolEvents.clear();
      ui.transcript.innerHTML = "";
      showEmpty();
      toast("Conversation log cleared.", "success", "LOG");
    } catch (error) {
      toast(error.message, "error", "LOG");
    }
  }

  function openLightbox(url) {
    ui.lightboxImg.src = url;
    ui.lightbox.hidden = false;
  }

  function closeLightbox() {
    ui.lightbox.hidden = true;
    ui.lightboxImg.removeAttribute("src");
  }

  /* ───────────────────────────── SSE ───────────────────────────── */

  function connectEvents() {
    if (state.es) state.es.close();
    const source = new EventSource("/api/events");
    state.es = source;

    source.onopen = () => {
      ui.footerStatus.classList.remove("error");
    };

    source.onerror = () => {
      ui.footerStatus.classList.add("error");
      ui.footerStatus.innerHTML = "<i></i> UPLINK LOST · RECONNECTING";
      source.close();
      state.es = null;
      clearTimeout(state.reconnectTimer);
      state.reconnectTimer = setTimeout(connectEvents, 2500);
    };

    source.onmessage = (event) => {
      try {
        handleEvent(JSON.parse(event.data));
      } catch (error) {
        console.error("Bad SSE event", error);
      }
    };
  }

  function handleEvent(event) {
    switch (event.type) {
      case "snapshot": {
        state.audio = event.audio || state.audio;
        state.llm = event.llm || state.llm;
        state.voices = event.voices || state.voices;
        state.quick = event.quick_prompts || state.quick;
        applySettings(event.settings, { silent: true });
        renderHistory(event.history);
        renderReminders(event.reminders);
        renderQuick(event.quick_prompts);
        updateStats(event.stats);
        updateMicPill();
        updateLlmPill();
        if (event.paths?.config) {
          const configPath = $("#config-path");
          const dataPath = $("#data-path");
          if (configPath) configPath.textContent = event.paths.config;
          if (dataPath) dataPath.textContent = event.paths.data;
        }
        if (!event.llm?.configured) {
          const where = event.paths?.config ? ` ${event.paths.config}` : " jarvis/.env";
          toast(`No OpenRouter key found. Add OPENROUTER_API_KEY to${where}.`, "error", "NEURAL LINK");
        }
        if (event.state) setState(event.state, event.state === "idle" ? "" : "Synchronising state…");
        break;
      }
      case "state":
        setState(event.state, event.detail);
        break;
      case "level":
        pushLevel(event.level);
        break;
      case "user":
        addMessage("user", event.text);
        break;
      case "assistant_delta":
        appendDelta(event.id, event.text);
        break;
      case "assistant_discard":
        discardAssistant(event.id);
        break;
      case "assistant_done":
        finalizeAssistant(event.id, event.text);
        break;
      case "tool_call":
        addToolEvent(event.id, event.name, null, "executing", null);
        break;
      case "tool_result":
        addToolEvent(event.id, event.name, Boolean(event.ok), event.message, event.duration);
        if (event.artifact) addArtifact(event.artifact);
        break;
      case "turn_complete": {
        const tools = event.tool_count ? ` · ${event.tool_count} TOOL${event.tool_count === 1 ? "" : "S"}` : "";
        ui.latency.textContent = `LATENCY ${Number(event.elapsed || 0).toFixed(1)}S${tools}`;
        break;
      }
      case "reminder":
        toast(event.text, "warn", "REMINDER");
        if (event.id != null) {
          const item = ui.reminders.querySelector(`[data-id="${event.id}"]`);
          if (item) item.remove();
          if (!ui.reminders.children.length) renderReminders([]);
          updateStats({ ...state.stats, reminders: Math.max(0, (state.stats.reminders || 1) - 1) });
        }
        break;
      case "error":
        toast(event.message, "error", "FAULT");
        break;
      case "toast":
        toast(event.text, event.level || "info", event.level === "warn" ? "ATTENTION" : "SYSTEM");
        break;
      case "settings":
        applySettings(event.settings);
        break;
      case "audio":
        state.audio.available = Boolean(event.available);
        updateMicPill();
        if (event.message && event.message !== state.lastAudioError && !event.available) {
          state.lastAudioError = event.message;
          toast(event.message, "warn", "VOICE");
        }
        break;
      case "wake":
        toast("Wake word detected. Listening…", "info", "VOICE");
        break;
      case "speech_start":
        if (state.currentState !== "speaking") setState("speaking");
        break;
      case "speech_end":
        if (state.currentState === "speaking") setState("idle");
        break;
      case "history_cleared":
        renderHistory([]);
        break;
      case "queued":
        break;
      default:
        break;
    }
  }

  /* ───────────────────────────── metrics / clock / weather ───────────────────────────── */

  function updateClock() {
    const now = new Date();
    $("#clock-time").textContent = now.toLocaleTimeString("en-GB", { hour12: false });
    $("#clock-date").textContent = now
      .toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short", year: "numeric" })
      .toUpperCase();
  }

  function setBar(id, value) {
    $(id).style.width = `${clamp(Number(value) || 0, 0, 100)}%`;
  }

  async function refreshMetrics() {
    try {
      const response = await fetch("/api/status");
      if (!response.ok) return;
      const data = await response.json();
      const metrics = data.metrics || {};
      $("#cpu-val").textContent = `${Math.round(metrics.cpu || 0)}%`;
      $("#mem-val").textContent = `${Math.round(metrics.memory || 0)}%`;
      $("#disk-val").textContent = `${Math.round(metrics.disk || 0)}%`;
      setBar("#cpu-bar", metrics.cpu);
      setBar("#mem-bar", metrics.memory);
      setBar("#disk-bar", metrics.disk);
      $("#mem-sub").textContent = `${metrics.memory_used_gb ?? "—"} / ${metrics.memory_total_gb ?? "—"} GB`;
      $("#disk-sub").textContent = `${metrics.disk_free_gb ?? "—"} GB FREE`;
      $("#net-down").textContent = Number(metrics.down_kbps || 0).toFixed(1);
      $("#net-up").textContent = Number(metrics.up_kbps || 0).toFixed(1);
      const uptimeHours = Math.floor((metrics.uptime || 0) / 3600);
      $("#uptime").textContent = uptimeHours >= 24 ? `${Math.floor(uptimeHours / 24)}D ${uptimeHours % 24}H` : `${uptimeHours}H`;
      $("#processes").textContent = metrics.processes ?? "—";
      if (metrics.battery != null) {
        $("#battery-val").textContent = `${Math.round(metrics.battery)}%`;
        setBar("#battery-bar", metrics.battery);
        $("#battery-label").textContent = metrics.battery_plugged ? "AC POWER" : "BATTERY";
      } else {
        $("#battery-val").textContent = "AC";
        setBar("#battery-bar", 100);
        $("#battery-label").textContent = "POWER";
      }
    } catch (_) {
      /* offline — SSE status will show it */
    }
  }

  async function refreshWeather() {
    try {
      const response = await fetch("/api/weather");
      if (!response.ok) return;
      const data = await response.json();
      if (!data.ok) return;
      const current = data.current || {};
      ui.weatherTemp.textContent = `${Math.round(current.temperature_c)}°`;
      ui.weatherCity.textContent = (data.location || "").split(",")[0].toUpperCase();
      ui.weatherChip.title = data.summary || "Local conditions";
    } catch (_) {
      /* silent */
    }
  }

  /* ───────────────────────────── wiring ───────────────────────────── */

  $("#send-btn").addEventListener("click", () => sendCommand());
  ui.command.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      sendCommand();
    }
  });
  ui.pttBtn.addEventListener("click", startListening);
  ui.stopBtn.addEventListener("click", stopAll);
  ui.wakeToggle.addEventListener("click", toggleWake);
  ui.voiceToggle.addEventListener("click", toggleVoice);
  $("#settings-btn").addEventListener("click", openSettings);
  $("#settings-close").addEventListener("click", closeSettings);
  $("#settings-save").addEventListener("click", saveSettings);
  $("#set-threshold").addEventListener("input", (event) => {
    $("#threshold-val").textContent = Number(event.target.value).toFixed(2);
  });
  $("#set-wake").addEventListener("click", (event) => {
    const button = event.currentTarget;
    button.setAttribute("aria-checked", button.getAttribute("aria-checked") === "true" ? "false" : "true");
  });
  $("#set-speak").addEventListener("click", (event) => {
    const button = event.currentTarget;
    button.setAttribute("aria-checked", button.getAttribute("aria-checked") === "true" ? "false" : "true");
  });
  $("#clear-btn").addEventListener("click", clearHistory);
  $("#export-btn").addEventListener("click", () => {
    window.location.href = "/api/export";
  });
  $("#add-reminder-btn").addEventListener("click", () => {
    ui.command.value = "Remind me to ";
    ui.command.focus();
    ui.command.setSelectionRange(ui.command.value.length, ui.command.value.length);
  });
  $("#open-data").addEventListener("click", async () => {
    try {
      await api("/api/open-data-folder", {});
    } catch (error) {
      toast(error.message, "error", "FILES");
    }
  });
  ui.settingsModal.addEventListener("click", (event) => {
    if (event.target === ui.settingsModal) closeSettings();
  });
  ui.lightbox.addEventListener("click", (event) => {
    if (event.target === ui.lightbox) closeLightbox();
  });
  $("#lightbox-close").addEventListener("click", closeLightbox);

  /* ───────────────────────────── start ───────────────────────────── */

  buildTicks();
  resizeStars();
  resizeWave();
  updateClock();
  setState("boot");
  if (new URLSearchParams(window.location.search).get("skipboot") === "1") {
    setTimeout(finishBoot, 80);
  } else {
    runBoot();
  }
  connectEvents();
  refreshMetrics();
  refreshWeather();
  setInterval(updateClock, 1000);
  setInterval(refreshMetrics, 4500);
  setInterval(refreshWeather, 600000);

  window.addEventListener("resize", () => {
    resizeStars();
    resizeWave();
  });
  new ResizeObserver(() => resizeWave()).observe(ui.wave);

  requestAnimationFrame(drawStars);
  requestAnimationFrame(drawWave);
})();
