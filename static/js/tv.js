(() => {
  const video = document.getElementById("video");
  const canvas = document.getElementById("canvas");
  const ctx = canvas.getContext("2d");
  const breakOverlay = document.getElementById("break-overlay");
  const breakLabel = document.getElementById("break-label");
  const breakCount = document.getElementById("break-count");
  const breakFill = document.getElementById("break-fill");
  const offairEl = document.getElementById("offair");
  const offairNext = document.getElementById("offair-next");
  const powerOff = document.getElementById("power-off");
  const powerBtn = document.getElementById("power");
  const clockEl = document.getElementById("clock");
  const chIndicator = document.getElementById("ch-indicator");
  const osd = document.getElementById("osd");
  const nowLine = document.getElementById("now-line");

  const state = {
    on: false,
    ch: null,
    data: null,
    curEntryId: null,
    curSrc: null,
    pendingSeek: 0,
    breakRemaining: 0,
    staticOn: false,
    osdTimer: null,
  };

  const fmtTime = (iso) => {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };

  const fmtDur = (min) => (min >= 60 ? Math.floor(min / 60) + "h " + (min % 60) + "m" : min + "m");

  function mediaUrl(src) {
    return /^https?:\/\//.test(src) ? src : "/media/" + encodeURIComponent(src);
  }

  function channelList() {
    return state.data ? state.data.channels : [];
  }

  function currentChannel() {
    const list = channelList();
    if (!list.length) return null;
    return list.find((c) => c.channelId === state.ch) || list[0];
  }

  async function poll() {
    try {
      const r = await fetch("/api/now", { cache: "no-store" });
      state.data = await r.json();
      renderStatus();
      syncScreen();
    } catch (e) { /* keep last state */ }
  }

  function showOsd() {
    const c = currentChannel();
    if (!c) return;
    osd.textContent = "CH " + c.number;
    osd.classList.remove("hidden");
    clearTimeout(state.osdTimer);
    state.osdTimer = setTimeout(() => osd.classList.add("hidden"), 1600);
  }

  function selectChannel(id) {
    state.ch = id;
    state.curEntryId = null;
    renderStatus();
    showOsd();
    syncScreen();
  }

  function cycle(dir) {
    const list = channelList();
    if (!list.length) return;
    const i = list.findIndex((c) => c.channelId === state.ch);
    selectChannel(list[(i + dir + list.length) % list.length].channelId);
  }

  document.getElementById("knob-vhf").addEventListener("click", () => cycle(-1));
  document.getElementById("knob-uhf").addEventListener("click", () => cycle(1));

  function renderStatus() {
    if (!state.data) return;
    if (!state.ch) state.ch = state.data.channels[0].channelId;
    const c = currentChannel();
    chIndicator.textContent = "CH " + c.number;
    let txt;
    if (c.state === "program") txt = "▶ " + c.entry.title;
    else if (c.state === "break") txt = "◼ " + c.brk.label;
    else txt = c.next ? "off air · next " + fmtTime(c.next.start) : "off air";
    nowLine.textContent = "CH " + c.number + " · " + c.name + " — " + txt;
  }

  function syncScreen() {
    if (!state.on || !state.data) return;
    const c = currentChannel();
    if (!c) return;

    if (c.state === "program") {
      breakOverlay.classList.add("hidden");
      offairEl.classList.add("hidden");
      state.staticOn = false;
      const entry = c.entry;
      document.title = entry.title + " · CH " + c.number + " · RetroTV";
      if (entry.src) {
        canvas.classList.add("hidden");
        video.classList.remove("hidden");
        const url = mediaUrl(entry.src);
        if (state.curSrc !== url || state.curEntryId !== entry.id) {
          state.curSrc = url;
          state.curEntryId = entry.id;
          state.pendingSeek = c.offsetSeconds;
          video.src = url;
          video.load();
        } else if (video.readyState >= 1 && Math.abs(video.currentTime - c.offsetSeconds) > 2.5) {
          video.currentTime = c.offsetSeconds;
        }
        video.play().catch(() => {});
      } else {
        video.pause();
        video.removeAttribute("src");
        video.load();
        state.curSrc = null;
        state.curEntryId = entry.id;
        video.classList.add("hidden");
        canvas.classList.remove("hidden");
        drawPattern(entry, c.number, c.name);
      }
    } else if (c.state === "break") {
      video.pause();
      video.classList.add("hidden");
      canvas.classList.add("hidden");
      offairEl.classList.add("hidden");
      state.staticOn = false;
      state.breakRemaining = c.brk.remainingSeconds;
      breakLabel.textContent = c.brk.label;
      breakOverlay.classList.remove("hidden");
      document.title = c.brk.label + " · CH " + c.number + " · RetroTV";
      updateBreakCount(c.brk);
    } else {
      video.pause();
      video.classList.add("hidden");
      breakOverlay.classList.add("hidden");
      canvas.classList.remove("hidden");
      offairEl.classList.remove("hidden");
      state.staticOn = true;
      state.curEntryId = null;
      offairNext.textContent = c.next
        ? "next up: " + c.next.title + " at " + fmtTime(c.next.start)
        : "nothing scheduled";
      document.title = "Off Air · CH " + c.number + " · RetroTV";
    }
  }

  function updateBreakCount(brk) {
    const remain = Math.max(0, Math.ceil(state.breakRemaining));
    const total = brk.durationSeconds || 1;
    breakCount.textContent = remain + "s";
    breakFill.style.width = (100 * (1 - state.breakRemaining / total)).toFixed(1) + "%";
  }

  video.addEventListener("loadedmetadata", () => {
    if (state.pendingSeek > 0) {
      try { video.currentTime = state.pendingSeek; } catch (e) {}
      state.pendingSeek = 0;
    }
  });

  const BAR_COLORS = ["#5a5f6e", "#6e6a55", "#4f6e63", "#6e4f5c", "#55606e", "#6e6350", "#3f4a5e"];

  function drawPattern(entry, chNum, chName) {
    const w = (canvas.width = 640);
    const h = (canvas.height = 480);
    const barW = w / BAR_COLORS.length;
    for (let i = 0; i < BAR_COLORS.length; i++) {
      ctx.fillStyle = BAR_COLORS[i];
      ctx.fillRect(i * barW, 0, barW, h * 0.62);
    }
    ctx.fillStyle = "#1a1d26";
    ctx.fillRect(0, h * 0.62, w, h * 0.38);
    ctx.fillStyle = "#e8e4d8";
    ctx.textAlign = "center";
    ctx.font = "bold 44px 'Trebuchet MS', sans-serif";
    ctx.fillText(entry.title, w / 2, h * 0.36);
    ctx.font = "22px 'Trebuchet MS', sans-serif";
    ctx.fillStyle = "#9aa4bd";
    ctx.fillText(fmtDur(entry.durationMinutes) + " · " + (entry.kind === "movie" ? "MOVIE" : "SHOW"), w / 2, h * 0.36 + 38);
    ctx.font = "bold 30px 'Trebuchet MS', sans-serif";
    ctx.fillStyle = "#d8b46a";
    ctx.fillText("CH " + chNum + " · " + chName, w / 2, h * 0.82);
    ctx.font = "18px 'Trebuchet MS', sans-serif";
    ctx.fillStyle = "#7f8ba3";
    ctx.fillText("now showing · please stand by", w / 2, h * 0.82 + 32);
  }

  function drawStatic() {
    const w = (canvas.width = 160);
    const h = (canvas.height = 120);
    const img = ctx.createImageData(w, h);
    for (let i = 0; i < img.data.length; i += 4) {
      const v = Math.floor(Math.random() * 90) + 40;
      img.data[i] = v; img.data[i + 1] = v; img.data[i + 2] = v; img.data[i + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
  }

  function loop() {
    if (state.staticOn) {
      if (!loop.lastStatic || Date.now() - loop.lastStatic > 120) {
        drawStatic();
        loop.lastStatic = Date.now();
      }
    }
    requestAnimationFrame(loop);
  }

  powerBtn.addEventListener("click", () => {
    state.on = !state.on;
    powerBtn.classList.toggle("on", state.on);
    powerOff.classList.toggle("off", state.on);
    if (!state.on) {
      video.pause();
      breakOverlay.classList.add("hidden");
      offairEl.classList.add("hidden");
      state.staticOn = false;
      nowLine.textContent = "";
      document.title = "RetroTV";
    } else {
      syncScreen();
    }
  });

  setInterval(() => {
    clockEl.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }, 1000);

  setInterval(() => {
    if (state.on && !breakOverlay.classList.contains("hidden")) {
      state.breakRemaining = Math.max(0, state.breakRemaining - 1);
      const c = currentChannel();
      if (c && c.state === "break") updateBreakCount(c.brk);
    }
  }, 1000);

  setInterval(poll, 2000);
  poll();
  loop();
})();
