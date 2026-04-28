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
  const wanted = new Set(urls);
  const allTabs = await chrome.tabs.query({});
  const byWindow = new Map();
  for (const t of allTabs) {
    if (!wanted.has(t.url)) continue;
    // Skip tabs Dia can't reliably address: pinned tabs (can't be grouped),
    // tabs without a stable id, and discarded/frozen tabs.
    if (t.pinned) continue;
    if (typeof t.id !== "number") continue;
    if (!byWindow.has(t.windowId)) byWindow.set(t.windowId, []);
    byWindow.get(t.windowId).push(t.id);
  }
  let groupCount = 0, grouped = 0, skipped = 0, errors = [];
  for (const [windowId, tabIds] of byWindow) {
    // Validate each tabId is still resolvable; drop ones Dia rejects.
    const live = [];
    for (const tid of tabIds) {
      try {
        await chrome.tabs.get(tid);
        live.push(tid);
      } catch (_) {
        skipped += 1;
      }
    }
    if (live.length === 0) continue;
    // Try the whole batch first; on failure, halve repeatedly until each
    // surviving subgroup succeeds. This isolates the bad TabSessionIDs.
    const groupedThisWindow = await groupResilient(windowId, live, title, color);
    grouped += groupedThisWindow.grouped;
    groupCount += groupedThisWindow.groups;
    for (const e of groupedThisWindow.errors) errors.push(e);
    skipped += groupedThisWindow.skipped;
  }
  reportResult(cmd.id, errors.length === 0 && grouped > 0,
    JSON.stringify({ groupCount, grouped, skipped, errors: errors.slice(0, 5) }));
}

async function groupResilient(windowId, tabIds, title, color) {
  if (tabIds.length === 0) return { grouped: 0, groups: 0, errors: [], skipped: 0 };
  try {
    const groupId = await chrome.tabs.group({ createProperties: { windowId }, tabIds });
    try {
      await chrome.tabGroups.update(groupId, { title, color, collapsed: true });
    } catch (_) { /* title/color may not stick on Dia, ignore */ }
    return { grouped: tabIds.length, groups: 1, errors: [], skipped: 0 };
  } catch (e) {
    if (tabIds.length === 1) {
      return { grouped: 0, groups: 0, errors: [String(e)], skipped: 1 };
    }
    const mid = Math.floor(tabIds.length / 2);
    const left  = await groupResilient(windowId, tabIds.slice(0, mid), title, color);
    const right = await groupResilient(windowId, tabIds.slice(mid),    title, color);
    return {
      grouped: left.grouped + right.grouped,
      groups:  left.groups  + right.groups,
      errors:  left.errors.concat(right.errors),
      skipped: left.skipped + right.skipped,
    };
  }
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
