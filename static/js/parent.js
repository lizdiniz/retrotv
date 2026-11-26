(() => {
  let pin = sessionStorage.getItem("retrotv-pin") || "";
  let data = null;

  const $ = (id) => document.getElementById(id);
  const loginEl = $("login"), appEl = $("app");
  const toastEl = $("toast");

  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.remove("hidden");
    setTimeout(() => toastEl.classList.add("hidden"), 2200);
  }

  function el(tag, attrs, ...children) {
    const n = document.createElement(tag);
    if (attrs) for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") n.className = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v);
    }
    for (const c of children) n.append(c);
    return n;
  }

  async function api(path, body) {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin, ...body }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
    return j;
  }

  const fmtTime = (isoStr) => {
    const d = new Date(isoStr);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };
  const fmtDur = (min) => (min >= 60 ? Math.floor(min / 60) + "h" + (min % 60 ? " " + (min % 60) + "m" : "") : min + "m");
  const toLocalInput = (isoStr) => {
    const d = new Date(isoStr);
    const p = (n) => String(n).padStart(2, "0");
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
      "T" + p(d.getHours()) + ":" + p(d.getMinutes());
  };
  const fromLocalInput = (v) => new Date(v).toISOString();

  async function refresh() {
    data = await api("/api/parent/data", {});
    renderAll();
  }

  function renderAll() {
    renderSchedule();
    renderLibrary();
    renderChannels();
    const srcSel = $("lib-src");
    srcSel.innerHTML = "";
    srcSel.append(el("option", { value: "" }, "(test pattern)"));
    for (const f of data.mediaFiles || []) {
      srcSel.append(el("option", { value: f }, f));
    }
  }

  function renderSchedule() {
    const root = $("schedule-root");
    root.innerHTML = "";
    for (const ch of data.channels) {
      const card = el("div", { class: "card ch-card" });
      card.append(el("h3", {}, "CH " + ch.number + " · " + ch.name));

      const entries = data.schedule
        .filter((e) => e.channelId === ch.id)
        .sort((a, b) => a.start.localeCompare(b.start));

      if (!entries.length) card.append(el("p", { class: "hint" }, "Nothing scheduled — this channel is OFF AIR."));

      for (const e of entries) {
        const lib = data.library.find((l) => l.id === e.libraryId);
        const row = el("div", { class: "entry" });
        row.append(
          el("span", { class: "time" }, fmtTime(e.start) + "–" + fmtTime(e.end)),
          el("span", { class: "title" }, lib ? lib.title : "(deleted item)"),
          el("span", { class: "kind" }, e.kind.toUpperCase()),
          el("span", { class: "dur" }, fmtDur(e.durationMinutes)),
        );
        const startInput = el("input", { type: "datetime-local", value: toLocalInput(e.start), title: "Move start time" });
        startInput.addEventListener("change", async () => {
          try {
            await api("/api/parent/schedule/setstart", { id: e.id, start: fromLocalInput(startInput.value) });
            toast("Moved"); await refresh();
          } catch (err) { toast(err.message); }
        });
        row.append(startInput);
        const del = el("button", { class: "icon-btn", title: "Remove from schedule" }, "✕");
        del.onclick = async () => {
          try { await api("/api/parent/schedule/delete", { id: e.id }); toast("Removed"); await refresh(); }
          catch (err) { toast(err.message); }
        };
        row.append(del);

        const breaksDiv = el("div", { class: "breaks" });
        for (const b of e.breaks) {
          const chip = el("span", { class: "chip" }, b.label + " · @" + b.atMinutes + "m for " + b.durationMinutes + "m");
          const bx = el("button", { title: "Remove break" }, "✕");
          bx.onclick = async () => {
            try { await api("/api/parent/break/delete", { scheduleId: e.id, breakId: b.id }); await refresh(); }
            catch (err) { toast(err.message); }
          };
          chip.append(bx);
          breaksDiv.append(chip);
        }
        const bLabel = el("input", { placeholder: "Break label (e.g. Bathroom Break)", maxlength: "60", size: "22" });
        const bAt = el("input", { type: "number", min: "0", value: "0", title: "Starts at minute", size: "4" });
        const bDur = el("input", { type: "number", min: "1", value: "3", title: "Duration (minutes)", size: "4" });
        const bAdd = el("button", {}, "+ break");
        bAdd.onclick = async () => {
          try {
            await api("/api/parent/break/add", {
              scheduleId: e.id, label: bLabel.value || "Break",
              atMinutes: Number(bAt.value), durationMinutes: Number(bDur.value),
            });
            await refresh();
          } catch (err) { toast(err.message); }
        };
        const mini = el("div", { class: "mini-form" }, bLabel, bAt, bDur, bAdd);
        breaksDiv.append(mini);
        row.append(breaksDiv);
        card.append(row);
      }

      const libSel = el("select");
      for (const l of data.library) libSel.append(el("option", { value: l.id }, l.title + " (" + fmtDur(l.durationMinutes) + ")"));
      const startIn = el("input", { type: "datetime-local", value: toLocalInput(new Date().toISOString()) });
      const addBtn = el("button", {}, "+ schedule");
      addBtn.onclick = async () => {
        if (!libSel.value) return;
        try {
          await api("/api/parent/schedule/add", {
            channelId: ch.id, libraryId: libSel.value, start: fromLocalInput(startIn.value), breaks: [],
          });
          toast("Scheduled"); await refresh();
        } catch (err) { toast(err.message); }
      };
      card.append(el("div", { class: "mini-form" }, libSel, startIn, addBtn));
      root.append(card);
    }
  }

  function renderLibrary() {
    const root = $("library-root");
    root.innerHTML = "";
    const card = el("div", { class: "card" });
    const table = el("table");
    table.append(el("tr", {}, el("th", {}, "Title"), el("th", {}, "Type"), el("th", {}, "Length"), el("th", {}, "File"), el("th", {}, "")));
    for (const l of [...data.library].sort((a, b) => a.title.localeCompare(b.title))) {
      const tr = el("tr", {},
        el("td", {}, l.title),
        el("td", {}, l.kind),
        el("td", {}, fmtDur(l.durationMinutes)),
        el("td", {}, l.src || "test pattern"),
      );
      const del = el("button", { class: "icon-btn" }, "✕");
      del.onclick = async () => {
        try { await api("/api/parent/library/delete", { id: l.id }); toast("Deleted"); await refresh(); }
        catch (err) { toast(err.message); }
      };
      tr.append(el("td", {}, del));
      table.append(tr);
    }
    card.append(table);
    root.append(card);
  }

  function renderChannels() {
    const root = $("channels-root");
    root.innerHTML = "";
    for (const ch of data.channels) {
      const input = el("input", { value: ch.name, maxlength: "30" });
      const btn = el("button", {}, "Save");
      btn.onclick = async () => {
        try { await api("/api/parent/channel/rename", { id: ch.id, name: input.value }); toast("Renamed"); await refresh(); }
        catch (err) { toast(err.message); }
      };
      root.append(el("div", { class: "card form-row" },
        el("strong", {}, "CH " + ch.number), input, btn));
    }
  }

  $("tabs").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-tab]");
    if (!btn) return;
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + btn.dataset.tab));
  });

  $("library-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/parent/library/add", {
        title: $("lib-title").value.trim(),
        kind: $("lib-kind").value,
        durationMinutes: Number($("lib-dur").value),
        src: $("lib-src").value || null,
      });
      $("lib-title").value = "";
      $("lib-dur").value = "";
      toast("Added to library");
      await refresh();
    } catch (err) { toast(err.message); }
  });

  $("pin-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/parent/pin/change", { newPin: $("pin-new").value.trim() });
      pin = $("pin-new").value.trim();
      sessionStorage.setItem("retrotv-pin", pin);
      $("pin-new").value = "";
      toast("PIN updated");
    } catch (err) { toast(err.message); }
  });

  async function tryLogin() {
    try {
      await api("/api/parent/login", {});
      sessionStorage.setItem("retrotv-pin", pin);
      loginEl.classList.add("hidden");
      appEl.classList.remove("hidden");
      await refresh();
    } catch (err) {
      $("login-error").classList.remove("hidden");
    }
  }

  $("login-btn").onclick = () => { pin = $("pin-input").value.trim(); tryLogin(); };
  $("pin-input").addEventListener("keydown", (e) => { if (e.key === "Enter") $("login-btn").click(); });

  if (pin) { tryLogin(); } else { $("pin-input").focus(); }
})();
