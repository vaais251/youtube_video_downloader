// Injects an IDM-style "Download" button onto the YouTube player and a popup
// for picking a quality. All app communication goes through the background
// service worker, which is not subject to YouTube's page CSP.

const BTN_ID = "ytdl-download-btn";
const PANEL_ID = "ytdl-panel";

function send(type, payload = {}) {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage({ type, ...payload }, (resp) =>
        resolve(resp || { ok: false, error: "no response" })
      );
    } catch (e) {
      resolve({ ok: false, error: String(e) });
    }
  });
}

function isWatchPage() {
  return location.pathname === "/watch";
}

function closePanel() {
  const p = document.getElementById(PANEL_ID);
  if (p) p.remove();
}

function removeButton() {
  const b = document.getElementById(BTN_ID);
  if (b) b.remove();
  closePanel();
}

function ensureButton() {
  if (!isWatchPage()) {
    removeButton();
    return;
  }
  const player =
    document.querySelector("#movie_player") ||
    document.querySelector(".html5-video-player");
  if (!player || document.getElementById(BTN_ID)) return;

  const btn = document.createElement("button");
  btn.id = BTN_ID;
  btn.className = "ytdl-btn";
  btn.title = "Download with YT Downloader";
  btn.textContent = "⬇ Download";
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    e.preventDefault();
    if (document.getElementById(PANEL_ID)) closePanel();
    else openPanel();
  });
  player.appendChild(btn);
}

function positionPanel(panel) {
  const btn = document.getElementById(BTN_ID);
  if (btn) {
    const r = btn.getBoundingClientRect();
    panel.style.top = `${r.bottom + 8}px`;
    panel.style.left = `${Math.max(8, r.left)}px`;
  } else {
    panel.style.top = "80px";
    panel.style.left = "80px";
  }
}

async function openPanel() {
  closePanel();
  const url = location.href;

  const panel = document.createElement("div");
  panel.id = PANEL_ID;
  panel.className = "ytdl-panel";
  panel.innerHTML = `
    <div class="ytdl-head">
      <span>Download video</span>
      <button class="ytdl-x" title="Close">×</button>
    </div>
    <div class="ytdl-title">…</div>
    <label class="ytdl-label">Quality</label>
    <select class="ytdl-select" disabled><option>Loading…</option></select>
    <button class="ytdl-dl" disabled>Download</button>
    <div class="ytdl-status"></div>
  `;
  document.body.appendChild(panel);
  positionPanel(panel);

  const sel = panel.querySelector(".ytdl-select");
  const dl = panel.querySelector(".ytdl-dl");
  const status = panel.querySelector(".ytdl-status");
  const titleEl = panel.querySelector(".ytdl-title");
  panel.querySelector(".ytdl-x").addEventListener("click", closePanel);

  const setStatus = (t, cls) => {
    status.textContent = t;
    status.className = "ytdl-status" + (cls ? " " + cls : "");
  };

  const alive = await send("ping");
  if (!alive.ok) {
    sel.innerHTML = "<option>App offline</option>";
    setStatus("Desktop app isn't running. Start it and retry.", "err");
    return;
  }

  setStatus("Fetching qualities…", "muted");
  const res = await send("formats", { url });
  if (!res.ok) {
    setStatus("Failed: " + (res.error || "unknown"), "err");
    return;
  }

  const options = res.options || [];
  if (res.title) titleEl.textContent = res.title;
  sel.innerHTML = "";
  options.forEach((o, i) => {
    const el = document.createElement("option");
    el.value = String(i);
    el.textContent = o.label;
    sel.appendChild(el);
  });
  sel.disabled = false;
  dl.disabled = false;
  setStatus("");

  dl.addEventListener("click", async () => {
    const o = options[Number(sel.value)];
    if (!o) return;
    dl.disabled = true;
    sel.disabled = true;
    setStatus("Sending to app…", "muted");
    const r = await send("download", {
      url,
      selector: o.selector,
      audio_only: !!o.audio_only,
      title: titleEl.textContent || url,
      label: o.label,
    });
    if (r.ok) {
      setStatus("✓ Downloading — check the app.", "ok");
      setTimeout(closePanel, 1200);
    } else {
      setStatus("Failed: " + (r.error || "unknown"), "err");
      dl.disabled = false;
      sel.disabled = false;
    }
  });
}

// Close the panel on outside click or Escape.
document.addEventListener(
  "click",
  (e) => {
    const p = document.getElementById(PANEL_ID);
    const btn = document.getElementById(BTN_ID);
    if (!p) return;
    if (p.contains(e.target)) return;
    if (btn && btn.contains(e.target)) return;
    closePanel();
  },
  true
);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closePanel();
});

// YouTube is a single-page app: re-inject after navigation and periodically.
window.addEventListener("yt-navigate-finish", ensureButton);
setInterval(ensureButton, 1000);
ensureButton();
