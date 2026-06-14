// Service worker: right-click menu + message handler that talks to the app.

const BASE = "http://127.0.0.1:8765";

async function ping() {
  try {
    const res = await fetch(`${BASE}/ping`, { method: "GET" });
    return { ok: res.ok };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

async function getFormats(url) {
  if (!url) return { ok: false, error: "no url" };
  try {
    const res = await fetch(`${BASE}/formats`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
      return { ok: false, error: data.error || "could not read formats" };
    }
    return { ok: true, title: data.title, options: data.options || [] };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

// One-click direct download at a given selector (defaults to best quality).
async function download(url, { selector = "bestvideo+bestaudio/best",
                              audioOnly = false, title = "", label = "" } = {}) {
  if (!url) return { ok: false, error: "no url" };
  try {
    const res = await fetch(`${BASE}/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, selector, audio_only: audioOnly, title, label }),
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok && data.ok !== false, error: data.error };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

// Relay for the content script (page CSP blocks direct localhost fetch there).
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || !msg.type) return;
  if (msg.type === "ping") {
    ping().then(sendResponse);
  } else if (msg.type === "formats") {
    getFormats(msg.url).then(sendResponse);
  } else if (msg.type === "download") {
    download(msg.url, {
      selector: msg.selector,
      audioOnly: msg.audio_only,
      title: msg.title,
      label: msg.label,
    }).then(sendResponse);
  } else {
    return;
  }
  return true; // async response
});

function notify(title, message) {
  // Notifications require an icon in MV3; fall back silently if unavailable.
  try {
    chrome.notifications.create({
      type: "basic",
      iconUrl: "icons/icon128.png",
      title,
      message,
    });
  } catch (_) {
    /* no icon bundled — ignore */
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "download-best",
    title: "Download (best quality)",
    contexts: ["page", "link", "video"],
  });
  chrome.contextMenus.create({
    id: "download-mp3",
    title: "Download audio (MP3)",
    contexts: ["page", "link", "video"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const url = info.linkUrl || info.srcUrl || (tab && tab.url);
  const title = (tab && tab.title) || "";
  let r;
  if (info.menuItemId === "download-best") {
    r = await download(url, { title });
  } else if (info.menuItemId === "download-mp3") {
    r = await download(url, { selector: "__audio_mp3__", audioOnly: true, title });
  } else {
    return;
  }
  notify(
    r.ok ? "Downloading in YT Downloader" : "Failed to start",
    r.ok ? url : "Is the desktop app running?"
  );
});

// Popup uses fetch() directly, so no message handler is needed here.
