/* Network-first, monotonic feed snapshot. Must load before app.js. */
(() => {
  'use strict';
  const KEY = 'sign-checker-feed-snapshot-v1';
  const RAW = 'https://raw.githubusercontent.com/NishiKohe/sign-checker-pwa/main/data/items.json';
  const nativeFetch = window.fetch.bind(window);
  const stamp = p => Date.parse(p?.generated_at || '');
  const valid = p => p && typeof p === 'object' && Array.isArray(p.items) && Number.isFinite(stamp(p)) && p.items.every(x => x && typeof x === 'object' && typeof x.id === 'string');
  function read() {
    try { const p = JSON.parse(localStorage.getItem(KEY) || 'null'); return valid(p) ? p : null; }
    catch { return null; }
  }
  function choose(a, b) {
    if (!valid(a)) return valid(b) ? b : null;
    if (!valid(b)) return a;
    // A transient failed crawl must never turn a populated feed into an empty page.
    if (a.items.length && !b.items.length) return a;
    if (b.items.length && !a.items.length) return b;
    const delta = stamp(b) - stamp(a);
    return delta > 0 || (delta === 0 && b.items.length > a.items.length) ? b : a;
  }
  function accept(p) {
    const selected = choose(read(), p);
    if (selected === p) {
      try { localStorage.setItem(KEY, JSON.stringify(p)); } catch (err) { console.warn('Feed snapshot storage unavailable', err); }
    }
    return selected;
  }
  async function getJSON(url, init) {
    const response = await nativeFetch(url, { ...init, cache: 'no-store' });
    if (!response.ok) throw new Error(`Feed request failed: ${response.status}`);
    const payload = await response.json();
    if (!valid(payload)) throw new Error('Invalid or incomplete feed');
    return payload;
  }
  async function latest(localUrl, init) {
    const timestamp = Date.now();
    const candidates = await Promise.allSettled([
      getJSON(`${RAW}?t=${timestamp}`, init),
      getJSON(localUrl, init)
    ]);
    let selected = read();
    let live = false;
    for (const result of candidates) {
      if (result.status !== 'fulfilled') continue;
      const newer = choose(selected, result.value);
      if (newer === result.value) { selected = newer; live = true; }
    }
    if (!selected) throw new Error('No saved feed and all sources unavailable');
    if (live) accept(selected);
    else if (candidates.every(x => x.status === 'rejected')) {
      // Network may be offline. Preserve the last successful collection.
      console.warn('Showing previously saved Sign Checker feed: network unavailable');
    }
    return selected;
  }
  window.SignCheckerFeedGuard = Object.freeze({ read, choose, accept, latest });
  window.fetch = function(input, init) {
    let url;
    try { url = new URL(input instanceof Request ? input.url : String(input), location.href); }
    catch { return nativeFetch(input, init); }
    const localFeed = url.origin === location.origin && /\/data\/items\.json$/.test(url.pathname);
    if (!localFeed || (init?.method && init.method.toUpperCase() !== 'GET')) return nativeFetch(input, init);
    return latest(url.href, init).then(p => new Response(JSON.stringify(p), {
      status: 200,
      headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }
    }));
  };
})();