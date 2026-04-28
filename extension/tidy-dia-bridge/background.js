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
  if (cmd.action === "dump-tabs") {
    const all = await chrome.tabs.query({});
    const tabs = all.map(t => ({
      id: t.id, windowId: t.windowId, url: t.url || "",
      pinned: !!t.pinned, status: t.status || ""
    }));
    try {
      await fetch("http://127.0.0.1:7321/ext/tabs", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ id: cmd.id, profile_hint: cmd.profile_hint || null, tabs })
      });
    } catch (_) {}
    return reportResult(cmd.id, true, JSON.stringify({ count: tabs.length }));
  }
  if (cmd.action !== "group") return reportResult(cmd.id, false, "unknown action");
  const urls = cmd.urls || [];
  const title = cmd.title || "Triage";
  const color = cmd.color || "grey";
  // Match exactly OR by URL with fragment stripped OR by origin+path (no query).
  // This handles SAML/OAuth/hash drift between scan-time and group-time.
  const exact = new Set(urls);
  const noFrag = new Set();
  const originPath = new Set();
  for (const u of urls) {
    try {
      const p = new URL(u);
      noFrag.add(p.origin + p.pathname + p.search);
      originPath.add(p.origin + p.pathname);
    } catch (_) { /* skip malformed */ }
  }
  function matches(tabUrl) {
    if (exact.has(tabUrl)) return true;
    try {
      const p = new URL(tabUrl);
      if (noFrag.has(p.origin + p.pathname + p.search)) return true;
      if (originPath.has(p.origin + p.pathname)) return true;
    } catch (_) {}
    return false;
  }
  const allTabs = await chrome.tabs.query({});
  const byWindow = new Map();
  for (const t of allTabs) {
    if (!t.url || !matches(t.url)) continue;
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
    // Carry a single groupId across sub-batches so we end up with ONE Dia
    // group per window instead of N collapsed groups with the same title.
    const ctx = { groupId: null };
    const groupedThisWindow = await groupResilient(windowId, live, title, color, ctx);
    grouped += groupedThisWindow.grouped;
    groupCount += groupedThisWindow.groups;
    for (const e of groupedThisWindow.errors) errors.push(e);
    skipped += groupedThisWindow.skipped;
  }
  reportResult(cmd.id, errors.length === 0 && grouped > 0,
    JSON.stringify({ groupCount, grouped, skipped, errors: errors.slice(0, 5) }));
}

async function groupResilient(windowId, tabIds, title, color, ctx) {
  if (tabIds.length === 0) return { grouped: 0, groups: 0, errors: [], skipped: 0 };
  try {
    let groupId;
    if (ctx.groupId == null) {
      groupId = await chrome.tabs.group({ createProperties: { windowId }, tabIds });
      ctx.groupId = groupId;
      try {
        await chrome.tabGroups.update(groupId, { title, color, collapsed: true });
      } catch (_) { /* title/color may not stick on Dia, ignore */ }
      return { grouped: tabIds.length, groups: 1, errors: [], skipped: 0 };
    } else {
      // Add to the existing group instead of creating a new one.
      await chrome.tabs.group({ groupId: ctx.groupId, tabIds });
      return { grouped: tabIds.length, groups: 0, errors: [], skipped: 0 };
    }
  } catch (e) {
    if (tabIds.length === 1) {
      return { grouped: 0, groups: 0, errors: [String(e)], skipped: 1 };
    }
    const mid = Math.floor(tabIds.length / 2);
    const left  = await groupResilient(windowId, tabIds.slice(0, mid), title, color, ctx);
    const right = await groupResilient(windowId, tabIds.slice(mid),    title, color, ctx);
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
