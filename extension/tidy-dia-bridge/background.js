// Tidy Dia Bridge — service worker
// Polls dia-organizer's local server for queued grouping commands and applies them.

const POLL_URL  = "http://127.0.0.1:7321/ext/poll";
const RESULT_URL = "http://127.0.0.1:7321/ext/result";
const POLL_PERIOD_SECONDS = 5;

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("poll", { periodInMinutes: POLL_PERIOD_SECONDS / 60 });
});
chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create("poll", { periodInMinutes: POLL_PERIOD_SECONDS / 60 });
});

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== "poll") return;
  try {
    const res = await fetch(POLL_URL);
    if (!res.ok) return;
    const cmds = await res.json();
    for (const cmd of (cmds || [])) {
      await handle(cmd);
    }
  } catch (e) {
    // Server not running or extension isn't allowed to reach localhost — ignore.
  }
});

async function handle(cmd) {
  if (cmd.action !== "group") return reportResult(cmd.id, false, "unknown action");
  const urls = cmd.urls || [];
  const title = cmd.title || "Triage";
  const color = cmd.color || "grey";
  // Find tab IDs whose URLs match the requested set, scoped to current window
  // for predictability. (chrome.tabGroups can only group tabs that are in
  // the SAME window. We group per window automatically.)
  const wanted = new Set(urls);
  const allTabs = await chrome.tabs.query({});
  const byWindow = new Map();
  for (const t of allTabs) {
    if (!wanted.has(t.url)) continue;
    if (!byWindow.has(t.windowId)) byWindow.set(t.windowId, []);
    byWindow.get(t.windowId).push(t.id);
  }
  let groupCount = 0, errors = [];
  for (const [windowId, tabIds] of byWindow) {
    try {
      const groupId = await chrome.tabs.group({ createProperties: { windowId }, tabIds });
      await chrome.tabGroups.update(groupId, { title, color, collapsed: true });
      groupCount += 1;
    } catch (e) {
      errors.push(String(e));
    }
  }
  reportResult(cmd.id, errors.length === 0, JSON.stringify({ groupCount, errors }));
}

async function reportResult(cmdId, ok, detail) {
  try {
    await fetch(RESULT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: cmdId, ok, detail })
    });
  } catch (_) { /* swallow */ }
}
