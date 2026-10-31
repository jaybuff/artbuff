// ArtBuff extension settings: the ArtBuff base URL lives in chrome.storage.sync
// under "artbuffBase"; background.js reads the same key.

const DEFAULT_BASE = "http://artbuff.jaybuff.com";
const input = document.getElementById("base");
const status = document.getElementById("status");

function cleanBase(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

async function originPattern(base) {
  try {
    return new URL(base).origin + "/*";
  } catch (_) {
    return null;
  }
}

async function ensurePermission(base) {
  // Fetching a custom base from the extension needs host permission for that
  // origin. The default is baked into the manifest; anything else is requested
  // here, inside the Save click (a user gesture, as required).
  const pattern = await originPattern(base);
  if (!pattern || pattern === DEFAULT_BASE + "/*") return true;
  if (!chrome.permissions || !chrome.permissions.request) return true;
  try {
    const has = await chrome.permissions.contains({ origins: [pattern] });
    if (has) return true;
    return await chrome.permissions.request({ origins: [pattern] });
  } catch (_) {
    return true; // permissions API unavailable — the send will fail visibly if blocked
  }
}

async function load() {
  const stored = await chrome.storage.sync.get({ artbuffBase: DEFAULT_BASE });
  input.value = stored.artbuffBase;
}

document.getElementById("save").addEventListener("click", async () => {
  const base = cleanBase(input.value) || DEFAULT_BASE;
  try {
    new URL(base);
  } catch (_) {
    status.textContent = "That doesn't look like a URL.";
    return;
  }
  const granted = await ensurePermission(base);
  await chrome.storage.sync.set({ artbuffBase: base });
  input.value = base;
  status.textContent = granted
    ? `Saved. Images will be sent to ${base}.`
    : `Saved, but permission for ${base} was declined — sends there will fail until it's allowed.`;
});

document.getElementById("test").addEventListener("click", async () => {
  const base = cleanBase(input.value) || DEFAULT_BASE;
  status.textContent = "Testing…";
  try {
    const res = await fetch(base + "/stats");
    status.textContent = res.ok
      ? `Reachable — ArtBuff answered at ${base}.`
      : `ArtBuff answered HTTP ${res.status} at ${base} (reachable, but check the server).`;
  } catch (_) {
    status.textContent = `No answer from ${base}. Is ArtBuff running? (If this is a new address, Save first to grant permission.)`;
  }
});

load();
