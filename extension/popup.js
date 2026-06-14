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
