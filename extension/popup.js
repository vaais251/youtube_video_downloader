// Popup: show the active tab's URL and send it to the desktop app on click.

const urlEl = document.getElementById("url");
const btn = document.getElementById("send");
const statusEl = document.getElementById("status");

let currentUrl = "";

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

(async () => {
  const tab = await getActiveTab();
  currentUrl = (tab && tab.url) || "";
  urlEl.textContent = currentUrl || "No active tab URL.";
  btn.disabled = !currentUrl;
})();

btn.addEventListener("click", () => {
  if (!currentUrl) return;
  btn.disabled = true;
  statusEl.textContent = "Sending…";
  statusEl.className = "";
  chrome.runtime.sendMessage({ type: "sendUrl", url: currentUrl }, (res) => {
    if (res && res.ok) {
      statusEl.textContent = "Sent! Check the app.";
      statusEl.className = "ok";
    } else {
      statusEl.textContent = "Failed — is the app running?";
      statusEl.className = "err";
      btn.disabled = false;
    }
  });
});
