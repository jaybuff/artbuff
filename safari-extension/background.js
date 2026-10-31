// ArtBuff — "Send to Frame TV" background service worker.
// Adds a context-menu item on images; clicking it POSTs the image URL to the
// ArtBuff server (which downloads, validates and pushes it to the TV itself —
// the extension never fetches the image, so login-walled/hotlinked images are
// the server's problem, and CORS on image hosts doesn't apply).

const DEFAULT_BASE = "http://artbuff.jaybuff.com";
const MENU_ID = "send-to-frame-tv";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: MENU_ID,
    title: "Send to Frame TV",
    contexts: ["image"],
  });
});

async function getBase() {
  const stored = await chrome.storage.sync.get({ artbuffBase: DEFAULT_BASE });
  return String(stored.artbuffBase || DEFAULT_BASE).replace(/\/+$/, "");
}

function badge(text, color) {
  try {
    chrome.action.setBadgeText({ text });
    if (color) chrome.action.setBadgeBackgroundColor({ color });
    if (text) setTimeout(() => chrome.action.setBadgeText({ text: "" }), 4000);
  } catch (_) {
    /* action badge not available in this browser — feedback is best-effort */
  }
}

function notify(title, message) {
  try {
    if (chrome.notifications && chrome.notifications.create) {
      chrome.notifications.create({
        type: "basic",
        iconUrl: "icon.png",
        title,
        message,
      });
      return;
    }
  } catch (_) {
    /* notifications unsupported (Safari) — fall through to the badge */
  }
  badge(title.startsWith("Sent") ? "✓" : "!", title.startsWith("Sent") ? "#2e7d32" : "#c62828");
}

async function sendToFrame(info, tab) {
  const srcUrl = info.srcUrl;
  if (!srcUrl || !/^https?:\/\//i.test(srcUrl)) {
    notify("Can't send that image", "ArtBuff can only fetch http(s) image URLs.");
    return;
  }
  badge("…", "#555555");
  const base = await getBase();
  try {
    const res = await fetch(base + "/api/send-image", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: srcUrl,
        title: (tab && tab.title) || "",
        page_url: info.pageUrl || (tab && tab.url) || "",
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok && data.ok) {
      notify("Sent to Frame TV", "The image is on the TV.");
    } else if (data.saved) {
      notify("Saved to ArtBuff", data.error || "Saved, but the TV didn't respond.");
    } else {
      notify("Couldn't send image", data.error || `ArtBuff answered HTTP ${res.status}.`);
    }
  } catch (e) {
    notify(
      "Can't reach ArtBuff",
      `No answer from ${base}. Is ArtBuff running and the base URL right (extension Settings)?`
    );
  }
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === MENU_ID) sendToFrame(info, tab);
});
