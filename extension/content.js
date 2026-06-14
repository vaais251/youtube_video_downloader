// Injects an IDM-style "Download" button over videos on ANY website, plus a
// popup for picking quality. App communication goes through the background
// service worker (not subject to page CSP).

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

function closePanel() {
  const p = document.getElementById(PANEL_ID);
  if (p) p.remove();
}

// --- per-video buttons ------------------------------------------------------

const tracked = new Map(); // <video> -> button element

function pickUrl(video) {
  // Only use the element's direct src when it's a clean, static media file
  // (no query string / token). Tokenized streaming CDN URLs are hotlink-
  // protected and refuse direct hits — for those we hand yt-dlp the page/embed
  // URL so its site-specific extractor (VK, OK, Vimeo, …) can do the work.
  const src = video.currentSrc || video.src || "";
  const cleanFile =
    /^https?:\/\/[^?#]+\.(mp4|webm|m4v|mkv|mov|m4a|mp3|ogg|flac|wav)$/i;
  if (cleanFile.test(src)) return src;
  return location.href;
}

function makeButton(onClick) {
  const btn = document.createElement("button");
  btn.className = "ytdl-btn";
  btn.title = "Download with YT Downloader";
  btn.textContent = "⬇ Download";
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    e.preventDefault();
    onClick();
  });
  return btn;
}

function refreshButtons() {
  document.querySelectorAll("video").forEach((video) => {
    const rect = video.getBoundingClientRect();
    const bigEnough = rect.width >= 220 && rect.height >= 130;
    const onScreen = rect.bottom > 0 && rect.top < window.innerHeight;

    let btn = tracked.get(video);
    if (!bigEnough) {
      if (btn) btn.style.display = "none";
      return;
    }
    if (!btn) {
      btn = makeButton(() => {
        if (document.getElementById(PANEL_ID)) closePanel();
        else openPanel(pickUrl(video), btn);
      });
      document.body.appendChild(btn);
      tracked.set(video, btn);
    }
    btn.style.display = onScreen ? "" : "none";
    btn.style.top = `${Math.max(8, rect.top + 10)}px`;
    btn.style.left = `${Math.max(8, rect.left + 10)}px`;
  });

  // Drop buttons whose <video> is gone.
  for (const [video, btn] of tracked) {
    if (!document.contains(video)) {
      btn.remove();
      tracked.delete(video);
    }
  }
}

// --- quality popup ----------------------------------------------------------

function positionPanel(panel, anchor) {
  if (anchor) {
    const r = anchor.getBoundingClientRect();
    panel.style.top = `${r.bottom + 8}px`;
    panel.style.left = `${Math.max(8, r.left)}px`;
  } else {
    panel.style.top = "80px";
    panel.style.left = "80px";
  }
}

async function openPanel(url, anchor) {
  closePanel();

  const panel = document.createElement("div");
  panel.id = PANEL_ID;
  panel.className = "ytdl-panel";
  panel.innerHTML = `
    <div class="ytdl-head">
      <span>Download</span>
      <button class="ytdl-x" title="Close">×</button>
    </div>
    <div class="ytdl-title">…</div>
    <label class="ytdl-label">Quality</label>
    <select class="ytdl-select" disabled><option>Loading…</option></select>
    <button class="ytdl-dl" disabled>Download</button>
    <div class="ytdl-status"></div>
  `;
  document.body.appendChild(panel);
  positionPanel(panel, anchor);

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

  setStatus("Detecting…", "muted");

  // Gather sniffed streams (from the background's network watcher) AND yt-dlp
  // formats for the page URL, in parallel.
  const [mediaRes, fmtRes] = await Promise.all([
    send("getMedia"),
    send("formats", { url }),
  ]);

  const options = []; // {label, kind: 'stream'|'media', ...}
  for (const s of (mediaRes && mediaRes.streams) || []) {
    options.push({
      label: "● " + s.label,
      kind: "stream",
      url: s.url,
      streamKind: s.kind,
      headers: s.headers || {},
    });
  }
  if (fmtRes && fmtRes.ok) {
    if (fmtRes.title) titleEl.textContent = fmtRes.title;
    for (const o of fmtRes.options || []) {
      options.push({
        label: o.label,
        kind: "media",
        selector: o.selector,
        audio_only: o.audio_only,
      });
    }
  }

  if (!options.length) {
    setStatus(
      "Nothing to download here. " +
        ((fmtRes && fmtRes.error) || "No media detected — try playing the video first."),
      "err"
    );
    return;
  }

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

    let r;
    if (o.kind === "stream") {
      r = await send("stream", {
        url: o.url,
        kind: o.streamKind,
        referrer: o.headers.referer || location.href,
        cookies: o.headers.cookie || "",
        userAgent: o.headers.userAgent || navigator.userAgent,
        title: titleEl.textContent || document.title || o.url,
      });
    } else {
      r = await send("download", {
        url,
        selector: o.selector,
        audio_only: !!o.audio_only,
        title: titleEl.textContent || url,
        label: o.label,
      });
    }

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

// --- lifecycle --------------------------------------------------------------

document.addEventListener(
  "click",
  (e) => {
    const p = document.getElementById(PANEL_ID);
    if (!p || p.contains(e.target)) return;
    if (e.target.classList && e.target.classList.contains("ytdl-btn")) return;
    closePanel();
  },
  true
);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closePanel();
});

window.addEventListener("scroll", refreshButtons, { passive: true });
window.addEventListener("resize", refreshButtons, { passive: true });
window.addEventListener("yt-navigate-finish", refreshButtons);
setInterval(refreshButtons, 1000);
refreshButtons();
