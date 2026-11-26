(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  let api = null;
  let lastSignature = "";
  let healthNotified = false;
  let toastTimer = null;

  function boot() {
    if (window.pywebview && window.pywebview.api) {
      api = window.pywebview.api;
      bindEvents();
      refreshHealth();
      setInterval(poll, 320);
      poll();
    } else {
      setTimeout(boot, 60);
    }
  }

  async function call(name, ...args) {
    if (!api) throw new Error("The app bridge is not ready yet.");
    return await api[name](...args);
  }

  function toast(message, isError) {
    const element = $("toast");
    element.textContent = message;
    element.classList.toggle("error", Boolean(isError));
    element.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => element.classList.remove("show"), 3400);
  }

  function handleResult(result, successMessage) {
    if (!result) return false;
    if (result.ok === false && !result.cancelled) {
      toast(result.error || "Something went wrong.", true);
      return false;
    }
    if (result.cancelled) return false;
    if (successMessage) toast(successMessage);
    return true;
  }

  function fmtTime(seconds) {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    const m = Math.floor(total / 60);
    const s = total % 60;
    return m + ":" + String(s).padStart(2, "0");
  }

  function fmtDuration(seconds) {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return h ? h + ":" + String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0") : m + ":" + String(s).padStart(2, "0");
  }

  function settings() {
    return {
      clip_length: Number($("length-input").value),
      max_clips: Number($("count-input").value),
      sensitivity: Number($("sensitivity-input").value),
      accurate: $("accurate-input").checked,
    };
  }

  function paintRange(input) {
    const min = Number(input.min);
    const max = Number(input.max);
    const value = Number(input.value);
    const percent = ((value - min) / Math.max(1, max - min)) * 100;
    input.style.setProperty("--fill", percent + "%");
  }

  // ---------- Rendering ----------
  async function poll() {
    try {
      const state = await call("get_state");
      if (state) render(state);
    } catch (error) {
      // Bridge may be restarting; keep polling quietly.
    }
  }

  function render(state) {
    const busy = state.status === "analyzing" || state.status === "exporting";

    // Health indicator
    const health = state.ffmpeg || {};
    const pill = $("health-pill");
    pill.classList.remove("checking", "ok", "missing");
    if (health.available) {
      pill.classList.add("ok");
      $("health-text").textContent = "FFmpeg ready";
    } else {
      pill.classList.add("missing");
      $("health-text").textContent = "FFmpeg missing";
      if (!healthNotified) {
        healthNotified = true;
        toast("FFmpeg is missing. Install it or set the path in Settings.", true);
      }
    }

    // Source file
    if (state.source) {
      $("empty-state").classList.add("hidden");
      $("file-state").classList.remove("hidden");
      $("file-name").textContent = state.source.name || "Video";
      const bits = [];
      if (state.source.duration) bits.push(fmtDuration(state.source.duration));
      if (state.source.width) bits.push(state.source.width + "×" + state.source.height);
      if (state.source.size_text) bits.push(state.source.size_text);
      if (!state.source.has_audio) bits.push("no audio");
      $("file-meta").textContent = bits.join("  ·  ");
      $("stat-time").textContent = fmtDuration(state.source.duration);
    } else {
      $("empty-state").classList.remove("hidden");
      $("file-state").classList.add("hidden");
      $("stat-time").textContent = "—";
    }
    $("stat-clips").textContent = state.moments && state.moments.length ? state.moments.length : "—";

    // Settings mirror (only when the user is not actively dragging a slider)
    const s = state.settings || {};
    if (document.activeElement !== $("length-input")) {
      $("length-input").value = s.clip_length || 20;
      $("length-value").textContent = (s.clip_length || 20) + "s";
      paintRange($("length-input"));
    }
    if (document.activeElement !== $("count-input")) {
      $("count-input").value = s.max_clips || 5;
      $("count-value").textContent = s.max_clips || 5;
      paintRange($("count-input"));
    }
    if (document.activeElement !== $("sensitivity-input")) {
      $("sensitivity-input").value = s.sensitivity == null ? 65 : s.sensitivity;
      $("sensitivity-value").textContent = (s.sensitivity == null ? 65 : s.sensitivity) + "%";
      paintRange($("sensitivity-input"));
    }
    $("accurate-input").checked = s.accurate !== false;
    if (document.activeElement !== $("output-input")) {
      $("output-input").value = s.output_dir || "";
    }

    // Progress
    const showProgress = busy;
    $("progress-panel").classList.toggle("hidden", !showProgress);
    if (showProgress) {
      $("progress-stage").textContent = state.stage || (state.status === "analyzing" ? "Analysing…" : "Exporting…");
      $("progress-message").textContent = state.message || "";
      $("progress-percent").textContent = (state.progress || 0) + "%";
      $("progress-bar").style.width = (state.progress || 0) + "%";
    }

    // Error
    if (state.status === "error" && state.error) {
      $("error-box").textContent = state.error;
      $("error-box").classList.remove("hidden");
    } else {
      $("error-box").classList.add("hidden");
    }

    // Buttons
    $("find-btn").disabled = busy || !state.source;
    $("export-btn").disabled = busy || !state.moments || state.moments.length === 0;
    $("cancel-btn").disabled = !busy;
    $("browse-btn").disabled = busy;
    $("change-btn").disabled = busy;
    $("clear-btn").disabled = busy;
    $("footer-status").textContent = state.message || (busy ? "Working…" : "Ready");

    // Results
    const moments = state.moments || [];
    const exported = state.exported || [];
    const signature = moments.map((m) => [m.index, m.start, m.score].join(":")).join("|") + "#" + exported.length;
    $("results").classList.toggle("hidden", moments.length === 0);
    if (signature !== lastSignature) {
      lastSignature = signature;
      renderClips(moments, exported);
    }
  }

  function renderClips(moments, exported) {
    const grid = $("clip-grid");
    grid.innerHTML = "";
    moments.forEach((moment) => {
      const card = document.createElement("article");
      card.className = "clip-card";
      const thumb = moment.thumbnail
        ? '<div class="thumb" style="background-image:url(\'' + moment.thumbnail + '\')">'
        : '<div class="thumb"><span class="thumb-icon">▶</span>';
      const chips = (moment.reasons || [])
        .map((reason, i) => '<span class="chip' + (i === 0 ? " primary" : "") + '">' + escapeHtml(reason) + "</span>")
        .join("");
      const isExported = exported.some((item) => item.index === moment.index);
      card.innerHTML =
        thumb +
        '<span class="rank">#' + moment.index + "</span>" +
        '<span class="score">' + (moment.score || 0) + " / 100</span>" +
        "</div>" +
        '<div class="clip-body">' +
        '<div class="clip-time">' + fmtTime(moment.start) + " – " + fmtTime(moment.end) + "</div>" +
        '<div class="clip-duration">' + fmtTime(moment.duration) + " clip · starts at " + fmtTime(moment.start) + "</div>" +
        '<div class="reasons">' + chips + "</div>" +
        '<div class="clip-actions">' +
        '<button class="btn btn-soft" data-action="play" data-index="' + moment.index + '"' + (isExported ? "" : " disabled") + ">Play clip</button>" +
        "</div></div>";
      grid.appendChild(card);
    });
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  }

  async function refreshHealth() {
    try {
      const info = await call("get_health");
      if (info && info.version) {
        $("health-pill").title = info.version;
      }
    } catch (error) {
      // handled by polling
    }
  }

  // ---------- Events ----------
  function bindEvents() {
    ["length-input", "count-input", "sensitivity-input"].forEach((id) => {
      paintRange($(id));
      $(id).addEventListener("input", (event) => {
        const labels = { "length-input": "length-value", "count-input": "count-value", "sensitivity-input": "sensitivity-value" };
        const suffix = id === "length-input" ? "s" : id === "sensitivity-input" ? "%" : "";
        $(labels[id]).textContent = event.target.value + suffix;
        paintRange(event.target);
      });
      $(id).addEventListener("change", () => call("update_settings", settings()).catch(() => {}));
    });

    $("accurate-input").addEventListener("change", () => call("update_settings", settings()).catch(() => {}));

    $("browse-btn").addEventListener("click", chooseFile);
    $("change-btn").addEventListener("click", chooseFile);
    $("drop-zone").addEventListener("click", (event) => {
      if (!event.target.closest("button")) chooseFile();
    });
    ["dragenter", "dragover"].forEach((eventName) =>
      $("drop-zone").addEventListener(eventName, (event) => {
        event.preventDefault();
        $("drop-zone").classList.add("dragging");
      })
    );
    ["dragleave", "dragend"].forEach((eventName) =>
      $("drop-zone").addEventListener(eventName, () => $("drop-zone").classList.remove("dragging"))
    );

    $("clear-btn").addEventListener("click", async () => {
      const result = await call("clear");
      if (handleResult(result)) {
        lastSignature = "";
        toast("Cleared");
      }
    });

    $("output-btn").addEventListener("click", async () => {
      const result = await call("browse_output_folder");
      if (handleResult(result)) {
        $("output-input").value = (result.settings || {}).output_dir || "";
        toast("Output folder updated");
      }
    });

    $("settings-btn").addEventListener("click", () => {
      const panel = document.querySelector(".settings");
      panel.classList.toggle("hidden");
    });

    $("find-btn").addEventListener("click", async () => {
      const result = await call("analyze", settings());
      handleResult(result);
    });

    $("export-btn").addEventListener("click", async () => {
      const result = await call("export_clips", settings());
      if (handleResult(result)) toast("Exporting clips…");
    });

    $("cancel-btn").addEventListener("click", async () => {
      const result = await call("cancel");
      handleResult(result, "Cancelling…");
    });

    $("open-folder-btn").addEventListener("click", async () => {
      const result = await call("open_folder");
      handleResult(result);
    });

    $("clip-grid").addEventListener("click", async (event) => {
      const button = event.target.closest('button[data-action="play"]');
      if (!button || button.disabled) return;
      const result = await call("open_clip", Number(button.dataset.index));
      handleResult(result);
    });
  }

  async function chooseFile() {
    const result = await call("browse_file");
    if (handleResult(result)) {
      lastSignature = "";
      toast("Video loaded: " + (result.source ? result.source.name : "ready"));
    }
  }

  boot();
})();
