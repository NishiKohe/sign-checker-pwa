const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Storage {
  constructor() { this.values = new Map(); }
  getItem(key) { return this.values.get(key) ?? null; }
  setItem(key, value) { this.values.set(key, String(value)); }
}
class Response {
  constructor(body, options = {}) { this.body = body; this.status = options.status || 200; this.ok = this.status >= 200 && this.status < 300; }
  async json() { return JSON.parse(this.body); }
}
class Request {
  constructor(url) { this.url = url; }
}
function feed(generatedAt, count, idPrefix = 'item') {
  return {
    generated_at: generatedAt,
    count,
    items: Array.from({ length: count }, (_, i) => ({ id: `${idPrefix}${i}`, title: `Title ${i}`, source: 'test' }))
  };
}
function setupGuard({ saved = null, raw = null, local = null } = {}) {
  const storage = new Storage();
  if (saved) storage.setItem('sign-checker-feed-snapshot-v1', JSON.stringify(saved));
  const requests = [];
  const fetch = async input => {
    const url = String(input);
    requests.push(url);
    const payload = url.includes('raw.githubusercontent.com') ? raw : local;
    if (payload instanceof Error) throw payload;
    if (!payload) return new Response('Not found', { status: 404 });
    return new Response(JSON.stringify(payload));
  };
  const ctx = vm.createContext({
    window: { fetch }, fetch, localStorage: storage,
    location: { href: 'https://nishikohe.github.io/sign-checker-pwa/', origin: 'https://nishikohe.github.io' },
    URL, Request, Response, console, Date, JSON, Promise
  });
  vm.runInContext(fs.readFileSync('feed-guard.js', 'utf8'), ctx, { filename: 'feed-guard.js' });
  return { ctx, storage, requests };
}

(async () => {
  const old = feed('2026-09-17T09:00:00Z', 2);
  const latest = feed('2026-09-17T11:00:00Z', 3);
  const staleDeploy = feed('2026-09-17T10:00:00Z', 1);
  let fixture = setupGuard({ saved: latest, raw: old, local: staleDeploy });
  let response = await fixture.ctx.window.fetch('./data/items.json?t=1', { cache: 'no-store' });
  assert.equal((await response.json()).count, 3, 'Reopening must not regress to a stale deployed feed');
  assert.equal(fixture.ctx.window.SignCheckerFeedGuard.read().count, 3);

  const newer = feed('2026-09-17T12:00:00Z', 4);
  fixture = setupGuard({ saved: old, raw: newer, local: staleDeploy });
  response = await fixture.ctx.window.fetch('./data/items.json');
  assert.equal((await response.json()).count, 4, 'Fresh remote feed must replace older saved feed');
  assert.equal(fixture.ctx.window.SignCheckerFeedGuard.read().count, 4);

  fixture = setupGuard({ saved: latest, raw: new Error('offline'), local: new Error('offline') });
  response = await fixture.ctx.window.fetch('./data/items.json');
  assert.equal((await response.json()).count, 3, 'Offline reopen must use the saved collection');

  fixture = setupGuard({ saved: latest, raw: feed('2026-09-17T13:00:00Z', 0), local: staleDeploy });
  response = await fixture.ctx.window.fetch('./data/items.json');
  assert.equal((await response.json()).count, 3, 'Empty transient crawl must not wipe populated snapshot');

  const storage = new Storage();
  const state = { items: [
    { id: 'followed', title: 'Favorite', favorite: true, completed: false, seen: false, ignored: false },
    { id: 'done', title: 'Completed', favorite: false, completed: true, seen: true, ignored: false, completed_at: '2026-09-16' },
    { id: 'ignored', title: 'Ignored', favorite: false, completed: false, seen: false, ignored: true }
  ] };
  const ctx = vm.createContext({ localStorage: storage, console, state });
  vm.runInContext(`
    function mergeFeed(items) {
      const old = new Map(state.items.map(x => [x.id, x]));
      const ids = new Set(items.map(x => x.id));
      state.items = items.map(x => ({ ...x, seen: !!old.get(x.id)?.seen, ignored: !!old.get(x.id)?.ignored,
        favorite: !!old.get(x.id)?.favorite, completed: !!old.get(x.id)?.completed,
        completed_at: old.get(x.id)?.completed_at || null }));
      for (const x of old.values()) if (x.completed && !ids.has(x.id)) state.items.push({ ...x, archived: true });
    }
    function save() { localStorage.setItem('sign-checker-pwa-v6', JSON.stringify(state)); }
  `, ctx);
  vm.runInContext(fs.readFileSync('feed-state.js', 'utf8'), ctx, { filename: 'feed-state.js' });
  vm.runInContext("mergeFeed([{ id: 'new', title: 'New' }]); save()", ctx);
  assert.equal(state.items.find(x => x.id === 'followed')?.favorite, true, 'Favorite survives disappearing from feed');
  assert.equal(state.items.find(x => x.id === 'done')?.completed, true, 'Completed survives disappearing from feed');
  vm.runInContext("mergeFeed([{ id: 'ignored', title: 'Back again' }, { id: 'new', title: 'New' }]); save()", ctx);
  assert.equal(state.items.find(x => x.id === 'ignored')?.ignored, true, 'Ignored action survives item disappearance and return');
  console.log('PASS: fresh feed, offline snapshot, empty-feed protection and action persistence');
})().catch(err => { console.error(err); process.exitCode = 1; });
