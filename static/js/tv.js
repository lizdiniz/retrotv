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
  const channelsEl = document.getElementById("channels");
  const clockEl = document.getElementById("clock");

  const state = {
    on: false,
    ch: null,
    data: null,
    curEntryId: null,
    curSrc: null,
    pendingSeek: 0,
    breakRemaining: 0,
    raf: null,
    staticOn: false,
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

  async function poll() {
    try {
      const r = await fetch("/api/now", { cache: "no-store" });
      state.data = await r.json();
      renderChannels();
      syncScreen();
    } catch (e) { /* keep last state */ }
  }

  function renderChannels() {
    if (!state.data) return;
    if (!state.ch) state.ch = state.data.channels[0].channelId;
    channelsEl.innerHTML = "";
    for (const c of state.data.channels) {
      const b = document.createElement("button");
      b.className = "ch-btn" + (c.channelId === state.ch ? " active" : "");
      let nowTxt, nowCls = "";
      if (c.state === "program") nowTxt = "▶ " + c.entry.title;
      else if (c.state === "break") { nowTxt = "◼ " + c.brk.label; nowCls = "break"; }
      else nowTxt = c.next ? "off air · next " + fmtTime(c.next.start) : "off air";
      b.innerHTML =
        '<div class="ch-num">CH ' + c.number + '</div>' +
        '<div class="ch-name">' + escapeHtml(c.name) + '</div>' +
        '<div class="ch-now ' + nowCls + '">' + escapeHtml(nowTxt) + "</div>";
      b.onclick = () => { state.ch = c.channelId; state.curEntryId = null; renderChannels(); syncScreen(); };
      channelsEl.appendChild(b);
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (m) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[m]));
  }

  function currentChannel() {
    if (!state.data) return null;
    return state.data.channels.find((c) => c.channelId === state.ch) || state.data.channels[0];
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
    ctx.imageSmoothingEnabled = true;
  }

  function loop() {
    if (state.staticOn) {
      if (!loop.lastStatic || Date.now() - loop.lastStatic > 120) {
        drawStatic();
        loop.lastStatic = Date.now();
      }
      canvas.width = canvas.width; // keep size
    }
    state.raf = requestAnimationFrame(loop);
  }

  powerBtn.onclick = () => {
    state.on = !state.on;
    powerBtn.classList.toggle("on", state.on);
    powerOff.classList.toggle("off", state.on);
    if (!state.on) {
      video.pause();
      breakOverlay.classList.add("hidden");
      offairEl.classList.add("hidden");
      state.staticOn = false;
      document.title = "RetroTV";
    } else {
      syncScreen();
    }
  };

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
