// Service worker: talks to the desktop app, and (IDM-style) intercepts browser
// downloads of any file type, handing them off to the app instead.

const BASE = "http://127.0.0.1:8765";

// File types we capture by default (images are intentionally excluded so we
// don't grab every inline picture). Configurable via the popup.
const DEFAULT_EXTS = [
  "zip", "rar", "7z", "gz", "tar", "bz2", "xz", "tgz",
  "iso", "exe", "msi", "dmg", "apk", "deb", "rpm", "bin",
  "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "epub",
  "mp3", "wav", "flac", "aac", "ogg", "m4a", "wma",
  "mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "3gp", "ts",
  "torrent",
];

let settings = { captureEnabled: true, extensions: DEFAULT_EXTS };

async function loadSettings() {
  const s = await chrome.storage.local.get(["captureEnabled", "extensions"]);
  if (typeof s.captureEnabled === "boolean") settings.captureEnabled = s.captureEnabled;
  if (Array.isArray(s.extensions) && s.extensions.length) settings.extensions = s.extensions;
  return settings;
}
loadSettings();
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local") return;
  if (changes.captureEnabled) settings.captureEnabled = changes.captureEnabled.newValue;
  if (changes.extensions && Array.isArray(changes.extensions.newValue)) {
    settings.extensions = changes.extensions.newValue;
  }
});

// --- app API ---------------------------------------------------------------

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

// Media download (yt-dlp) at a given selector (defaults to best quality).
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

// Stream download: hand a sniffed media URL (+ its captured headers) to the app.
async function streamDownload({ url, kind = "", referrer = "", cookies = "",
                              userAgent = "", origin = "", title = "" }) {
  if (!url) return { ok: false, error: "no url" };
  try {
    const res = await fetch(`${BASE}/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, kind, referrer, cookies, userAgent, origin, title }),
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok && data.ok !== false, error: data.error };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

// Generic file capture: hand a direct file URL (+ headers) to the app. Passing
// the right Referer/Cookie/User-Agent is what makes hotlink-protected CDNs
// (which otherwise return 403) work — exactly like IDM.
async function capture({ url, filename = "", referrer = "", cookies = null,
                        userAgent = "", origin = "", mime = "", size = 0 }) {
  if (!url) return { ok: false, error: "no url" };
  if (cookies == null) {
    cookies = "";
    try {
      const cks = await chrome.cookies.getAll({ url });
      cookies = cks.map((c) => `${c.name}=${c.value}`).join("; ");
    } catch (_) {
      /* cookies optional */
    }
  }
  try {
    const res = await fetch(`${BASE}/capture`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url, filename, referrer, cookies, origin,
        userAgent: userAgent || navigator.userAgent, mime, size,
      }),
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok && data.ok !== false, error: data.error };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

function _host(u) {
  try { return new URL(u).host; } catch { return ""; }
}

// Headers the sniffer captured for a URL: exact match first, then any media on
// the same host (Referer/Origin are page-level, so a same-host match is valid).
function findSniffedHeaders(url) {
  const host = _host(url);
  let sameHost = null;
  for (const list of tabMedia.values()) {
    for (const c of list) {
      if (c.url === url) return c.headers || {};
      if (!sameHost && host && _host(c.url) === host) sameHost = c.headers || {};
    }
  }
  return sameHost;
}

// --- download interception (the IDM behaviour) -----------------------------

function extOf(item) {
  const src = ((item.filename || item.url || "").split("?")[0]).split("#")[0];
  const m = src.match(/\.([a-z0-9]{1,5})$/i);
  return m ? m[1].toLowerCase() : "";
}

function shouldCapture(item) {
  if (!settings.captureEnabled) return false;
  const url = item.finalUrl || item.url || "";
  if (!/^https?:/i.test(url)) return false; // skip blob:, data:, file:, etc.
  if (settings.extensions.includes(extOf(item))) return true;
  return (item.mime || "").toLowerCase() === "application/octet-stream";
}

chrome.downloads.onCreated.addListener(async (item) => {
  try {
    await loadSettings();
    if (!shouldCapture(item)) return;
    if (!(await ping()).ok) return; // app offline -> let the browser download

    const url = item.finalUrl || item.url;
    const filename = item.filename ? item.filename.split(/[\\/]/).pop() : "";

    // Use the exact headers the sniffer saw for this URL (Referer is what most
    // 403-on-direct-download CDNs require). Fall back to the active tab's URL.
    const sniff = findSniffedHeaders(url) || {};
    let referrer = item.referrer || sniff.referer || "";
    if (!referrer) {
      try {
        const [t] = await chrome.tabs.query({ active: true, currentWindow: true });
        referrer = (t && t.url) || "";
      } catch (_) {
        /* ignore */
      }
    }

    const r = await capture({
      url,
      filename,
      referrer,
      cookies: sniff.cookie || null, // null -> capture() reads cookies itself
      userAgent: sniff.userAgent || "",
      origin: sniff.origin || "",
      mime: item.mime || "",
      size: item.fileSize && item.fileSize > 0 ? item.fileSize : 0,
    });
    if (r.ok) {
      // Stop the browser's own download and remove it from the list.
      chrome.downloads.cancel(item.id, () => {
        void chrome.runtime.lastError;
        chrome.downloads.erase({ id: item.id }, () => void chrome.runtime.lastError);
      });
      notify("Downloading in YT Downloader", filename || url);
    }
  } catch (_) {
    /* never let interception throw */
  }
});

// --- media sniffer (IDM-style stream detection) ----------------------------
// Watches network requests, records media URLs + the exact headers the browser
// sent (referer/cookie/user-agent), bucketed per tab. HLS/DASH manifests and
// standalone media files are kept; individual HLS segments (.ts/.m4s) are not.

const tabMedia = new Map(); // tabId -> [{ url, kind, label, headers }]
const MEDIA_RE =
  /\.(m3u8|mpd|mp4|webm|m4a|mp3|aac|flac|wav|ogg|mov|mkv|flv|m4v)(\?|#|$)/i;
const SEGMENT_RE = /\.(ts|m4s)(\?|#|$)/i;

function streamKind(url, ct) {
  if (/\.m3u8(\?|#|$)/i.test(url) || /mpegurl/i.test(ct || "")) return "hls";
  if (/\.mpd(\?|#|$)/i.test(url) || /dash\+xml/i.test(ct || "")) return "dash";
  return "file";
}

function labelFor(url, kind) {
  let name = "";
  try {
    name = decodeURIComponent(new URL(url).pathname.split("/").pop() || "");
  } catch (_) {
    /* ignore */
  }
  if (kind === "hls") return `HLS stream${name ? " · " + name : ""}`;
  if (kind === "dash") return `DASH stream${name ? " · " + name : ""}`;
  return name || "media file";
}

function addCandidate(tabId, url, headers, ct) {
  if (tabId < 0) return;
  if (SEGMENT_RE.test(url)) return; // skip HLS/DASH segments
  const kind = streamKind(url, ct);
  let list = tabMedia.get(tabId);
  if (!list) {
    list = [];
    tabMedia.set(tabId, list);
  }
  if (list.some((c) => c.url === url)) return; // dedupe
  list.push({ url, kind, label: labelFor(url, kind), headers });
  if (list.length > 30) list.shift();
}

chrome.webRequest.onBeforeSendHeaders.addListener(
  (d) => {
    if (d.tabId < 0) return;
    const isMedia = d.type === "media" || MEDIA_RE.test(d.url);
    if (!isMedia) return;
    const h = {};
    for (const hd of d.requestHeaders || []) {
      const n = hd.name.toLowerCase();
      if (n === "referer") h.referer = hd.value;
      else if (n === "cookie") h.cookie = hd.value;
      else if (n === "user-agent") h.userAgent = hd.value;
      else if (n === "origin") h.origin = hd.value;
    }
    addCandidate(d.tabId, d.url, h);
  },
  { urls: ["<all_urls>"] },
  ["requestHeaders", "extraHeaders"]
);

// Clear a tab's candidates when it navigates to a new page.
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.url) tabMedia.delete(tabId);
});
chrome.tabs.onRemoved.addListener((tabId) => tabMedia.delete(tabId));

// --- messaging (content script + popup) ------------------------------------

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
  } else if (msg.type === "getMedia") {
    (async () => {
      let tabId = _sender.tab && _sender.tab.id;
      if (tabId == null) {
        const [t] = await chrome.tabs.query({ active: true, currentWindow: true });
        tabId = t && t.id;
      }
      sendResponse({ ok: true, streams: (tabId != null && tabMedia.get(tabId)) || [] });
    })();
  } else if (msg.type === "stream") {
    streamDownload({
      url: msg.url,
      kind: msg.kind,
      referrer: msg.referrer,
      cookies: msg.cookies,
      userAgent: msg.userAgent,
      origin: msg.origin,
      title: msg.title,
    }).then(sendResponse);
  } else if (msg.type === "capture") {
    capture({
      url: msg.url,
      filename: msg.filename || "",
      referrer: msg.referrer || "",
    }).then(sendResponse);
  } else if (msg.type === "getSettings") {
    loadSettings().then(() => sendResponse({ ok: true, ...settings }));
  } else if (msg.type === "setCapture") {
    chrome.storage.local.set({ captureEnabled: !!msg.value }, () =>
      sendResponse({ ok: true })
    );
  } else {
    return;
  }
  return true; // async response
});

// --- notifications + context menus -----------------------------------------

function notify(title, message) {
  try {
    chrome.notifications.create(
      {
        type: "basic",
        iconUrl: chrome.runtime.getURL("icons/icon128.png"),
        title,
        message,
      },
      () => void chrome.runtime.lastError // swallow "image download" errors
    );
  } catch (_) {
    /* ignore */
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "download-best",
    title: "Download video (best quality)",
    contexts: ["page", "link", "video"],
  });
  chrome.contextMenus.create({
    id: "download-mp3",
    title: "Download audio (MP3)",
    contexts: ["page", "link", "video"],
  });
  chrome.contextMenus.create({
    id: "download-link",
    title: "Download this link with YT Downloader",
    contexts: ["link"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const title = (tab && tab.title) || "";
  let r;
  if (info.menuItemId === "download-best") {
    r = await download(info.linkUrl || info.srcUrl || (tab && tab.url), { title });
  } else if (info.menuItemId === "download-mp3") {
    r = await download(info.linkUrl || info.srcUrl || (tab && tab.url),
      { selector: "__audio_mp3__", audioOnly: true, title });
  } else if (info.menuItemId === "download-link") {
    r = await capture({ url: info.linkUrl, referrer: (tab && tab.url) || "" });
  } else {
    return;
  }
  notify(
    r.ok ? "Sent to YT Downloader" : "Failed to start",
    r.ok ? "Check the desktop app." : "Is the desktop app running?"
  );
});
