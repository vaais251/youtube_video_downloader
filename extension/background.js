// Service worker: adds a right-click menu and forwards URLs to the desktop app.

const APP_URL = "http://127.0.0.1:8765/add";

async function sendUrl(url) {
  if (!url) return { ok: false, error: "no url" };
  try {
    const res = await fetch(APP_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok && data.ok !== false };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

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
    id: "send-to-yt-downloader",
    title: "Send to YT Downloader",
    contexts: ["page", "link", "video"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "send-to-yt-downloader") return;
  const url = info.linkUrl || info.srcUrl || (tab && tab.url);
  const r = await sendUrl(url);
  notify(
    r.ok ? "Sent to YT Downloader" : "Failed to send",
    r.ok ? url : "Is the desktop app running?"
  );
});

// Allow the popup to ask the worker to send.
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "sendUrl") {
    sendUrl(msg.url).then(sendResponse);
    return true; // keep the channel open for the async response
  }
});
