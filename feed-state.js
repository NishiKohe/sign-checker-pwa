/* Install after app.js, before manual-refresh.js. Keep action history separately from the live feed. */
(() => {
  'use strict';
  const KEY = 'sign-checker-item-actions-v1';
  if (typeof mergeFeed !== 'function' || typeof save !== 'function' || !state) return;
  function read() {
    try {
      const value = JSON.parse(localStorage.getItem(KEY) || '{}');
      return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    } catch { return {}; }
  }
  const actions = read();
  function record(items) {
    for (const x of items || []) {
      if (!x?.id) continue;
      const previous = actions[x.id] || {};
      actions[x.id] = {
        seen: !!x.seen,
        ignored: !!x.ignored,
        favorite: !!x.favorite,
        completed: !!x.completed,
        completed_at: x.completed_at || previous.completed_at || null
      };
    }
  }
  function persist() {
    try { localStorage.setItem(KEY, JSON.stringify(actions)); }
    catch (err) { console.warn('Action history storage unavailable', err); }
  }
  // Migrate existing preferences without requiring the user to re-mark any items.
  // An already-stored action has priority over feed fields and previous UI migrations.
  for (const x of state.items || []) {
    if (!x?.id) continue;
    if (actions[x.id]) Object.assign(x, actions[x.id]);
    else record([x]);
  }
  persist();
  const previousMerge = mergeFeed;
  mergeFeed = function(incoming) {
    record(state.items);
    const followed = state.items.filter(x => x && (x.favorite || x.completed));
    previousMerge(incoming);
    const ids = new Set();
    for (const x of state.items) {
      ids.add(x.id);
      if (actions[x.id]) Object.assign(x, actions[x.id]);
    }
    for (const x of followed) {
      if (ids.has(x.id)) continue;
      const copy = { ...x, archived: true };
      if (actions[x.id]) Object.assign(copy, actions[x.id]);
      state.items.push(copy);
      ids.add(x.id);
    }
    record(state.items);
    persist();
  };
  const previousSave = save;
  save = function() {
    record(state.items);
    persist();
    return previousSave();
  };
})();