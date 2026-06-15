// Popup: fetch quality options from the desktop app and download directly.

const BASE = "http://127.0.0.1:8765";

const titleEl = document.getElementById("title");
const urlEl = document.getElementById("url");
const qualityEl = document.getElementById("quality");
const btn = document.getElementById("download");
const statusEl = document.getElementById("status");

let currentUrl = "";
let options = []; // [{label, selector, audio_only}]

function setStatus(text, cls) {
  statusEl.textContent = text;
  statusEl.className = cls || "";
}

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function appOnline() {
  try {
    const res = await fetch(`${BASE}/ping`, { method: "GET" });
    return res.ok;
  } catch {
    return false;
  }
}

async function loadFormats() {
  setStatus("Fetching qualities…", "muted");
  try {
    const res = await fetch(`${BASE}/formats`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: currentUrl }),
    });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
      throw new Error(data.error || "Could not read formats");
    }
    if (data.title) titleEl.textContent = data.title;
    options = data.options || [];
    qualityEl.innerHTML = "";
    options.forEach((opt, i) => {
      const o = document.createElement("option");
      o.value = String(i);
      o.textContent = opt.label;
      qualityEl.appendChild(o);
    });
    qualityEl.disabled = false;
    btn.disabled = false;
    setStatus("");
  } catch (e) {
    setStatus("Couldn't fetch formats. " + String(e.message || e), "err");
  }
}

async function startDownload() {
  const opt = options[Number(qualityEl.value)];
  if (!opt) return;
  btn.disabled = true;
  qualityEl.disabled = true;
  setStatus("Sending to app…", "muted");
  try {
    const res = await fetch(`${BASE}/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: currentUrl,
        selector: opt.selector,
        audio_only: !!opt.audio_only,
        title: titleEl.textContent || currentUrl,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok && data.ok !== false) {
      setStatus("✓ Downloading — check the app.", "ok");
      setTimeout(() => window.close(), 900);
    } else {
      throw new Error(data.error || "rejected");
    }
  } catch (e) {
    setStatus("Failed: " + String(e.message || e), "err");
    btn.disabled = false;
    qualityEl.disabled = false;
  }
}

btn.addEventListener("click", startDownload);

// --- capture toggle ---
const captureEl = document.getElementById("capture");
chrome.runtime.sendMessage({ type: "getSettings" }, (res) => {
  if (res && res.ok) captureEl.checked = !!res.captureEnabled;
});
captureEl.addEventListener("change", () => {
  chrome.runtime.sendMessage({ type: "setCapture", value: captureEl.checked });
});

// --- grab all links on the page ---
const grabBtn = document.getElementById("grab");
const grabList = document.getElementById("grablist");

function tabSend(tabId, msg) {
  return new Promise((resolve) => {
    try {
      chrome.tabs.sendMessage(tabId, msg, (r) => {
        void chrome.runtime.lastError;
        resolve(r || { ok: false });
      });
    } catch {
      resolve({ ok: false });
    }
  });
}

grabBtn.addEventListener("click", async () => {
  grabList.innerHTML = "<div class='hint'>Scanning…</div>";
  const tab = await getActiveTab();
  if (!tab) return;
  const [page, media] = await Promise.all([
    tabSend(tab.id, { type: "collectLinks" }),
    new Promise((res) => chrome.runtime.sendMessage({ type: "getMedia" }, res)),
  ]);
  const items = [];
  for (const s of (media && media.streams) || []) {
    items.push({ url: s.url, label: "● " + s.label, kind: "stream", streamKind: s.kind, headers: s.headers || {} });
  }
  for (const l of (page && page.links) || []) {
    items.push({ url: l.url, label: l.label, kind: "file" });
  }
  if (!items.length) {
    grabList.innerHTML = "<div class='hint'>No downloadable links or media found.</div>";
    return;
  }

  grabList.innerHTML = "";
  items.forEach((it, i) => {
    const row = document.createElement("label");
    row.className = "grab-item";
    row.innerHTML = `<input type="checkbox" data-i="${i}" checked><span title="${it.url}">${it.label}</span>`;
    grabList.appendChild(row);
  });
  const dlBtn = document.createElement("button");
  dlBtn.id = "grabdl";
  dlBtn.textContent = `Download selected`;
  grabList.appendChild(dlBtn);

  dlBtn.addEventListener("click", async () => {
    dlBtn.disabled = true;
    const checks = grabList.querySelectorAll("input[type=checkbox]:checked");
    let n = 0;
    for (const c of checks) {
      const it = items[Number(c.dataset.i)];
      if (it.kind === "stream") {
        await new Promise((res) => chrome.runtime.sendMessage({
          type: "stream", url: it.url, kind: it.streamKind,
          referrer: it.headers.referer || (tab.url || ""),
          cookies: it.headers.cookie || "", userAgent: it.headers.userAgent || "",
          origin: it.headers.origin || "",
          title: it.label,
        }, res));
      } else {
        await new Promise((res) => chrome.runtime.sendMessage({
          type: "capture", url: it.url, referrer: tab.url || "",
        }, res));
      }
      n++;
    }
    dlBtn.textContent = `Sent ${n} to app ✓`;
  });
});

(async () => {
  const tab = await getActiveTab();
  currentUrl = (tab && tab.url) || "";
  titleEl.textContent = (tab && tab.title) || "";
  urlEl.textContent = currentUrl || "No active tab URL.";

  if (!currentUrl) {
    setStatus("No URL in this tab.", "err");
    return;
  }
  if (!(await appOnline())) {
    qualityEl.innerHTML = "<option>App offline</option>";
    setStatus("Desktop app isn't running. Start it and reopen.", "err");
    return;
  }
  await loadFormats();
})();
