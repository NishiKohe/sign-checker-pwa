(() => {
  const API = location.hostname.endsWith('.vercel.app')
    ? '/api/refresh'
    : 'https://sign-checker-pwa.vercel.app/api/refresh';
  const RAW_FEED = 'https://raw.githubusercontent.com/NishiKohe/sign-checker-pwa/main/data/items.json';
  const POLL_MS = 15000;
  const MAX_POLLS = 120; // up to 30 minutes

  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const notify = msg => {
    try { if (typeof toast === 'function') return toast(msg); } catch {}
    console.log(msg);
  };
  const freshness = p => Date.parse(p?.generated_at || '') || 0;

  async function fetchLatestPayload() {
    const urls = [
      `${RAW_FEED}?t=${Date.now()}`,
      `./data/items.json?t=${Date.now()}`
    ];
    let lastError;
    let best = window.SignCheckerFeedGuard?.read() || null;
    for (const url of urls) {
      try {
        const r = await fetch(url, { cache: 'no-store' });
        if (!r.ok) throw new Error(`feed ${r.status}`);
        const payload = await r.json();
        if (!Array.isArray(payload.items) || !freshness(payload)) throw new Error('Invalid feed');
        best = window.SignCheckerFeedGuard?.choose(best, payload) || payload;
      } catch (error) {
        lastError = error;
      }
    }
    if (best) return best;
    throw lastError || new Error('最新フィードを取得できません');
  }

  function applyPayload(payload) {
    if (typeof mergeFeed !== 'function' || typeof render !== 'function') return false;
    const guard = window.SignCheckerFeedGuard;
    const chosen = guard ? guard.accept(payload) : payload;
    if (!chosen || (state.feed?.generatedAt && freshness(chosen) < Date.parse(state.feed.generatedAt))) {
      return false; // A delayed CDN response must never replace a newer collection.
    }
    mergeFeed(Array.isArray(chosen.items) ? chosen.items : []);
    state.feed = {
      generatedAt: chosen.generated_at || null,
      sources: chosen.sources || {},
      schemaVersion: chosen.schema_version || null,
      policy: chosen.feed_policy || '',
      newCount: chosen.new_count || 0,
      opportunityCounts: chosen.opportunity_counts || {},
      tierCounts: chosen.value_tier_counts || {}
    };
    save();
    render();
    return true;
  }

  async function startCollection(button) {
    const beforePayload = await fetchLatestPayload().catch(() => null);
    const beforeGenerated = beforePayload?.generated_at || state?.feed?.generatedAt || null;

    button.disabled = true;
    button.textContent = '収集開始…';
    const policy = document.querySelector('#feedPolicy');
    const oldPolicy = policy?.textContent || '';
    if (policy) policy.textContent = '手動収集を開始しています…';

    const response = await fetch(API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store'
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || !body.ok) {
      throw new Error(body.error || `収集開始に失敗しました (${response.status})`);
    }

    const already = ['already_running', 'recently_started'].includes(body.status);
    notify(already ? 'すでに収集中です。完了を待ちます' : '情報収集を開始しました');

    const started = Date.now();
    for (let i = 0; i < MAX_POLLS; i++) {
      const elapsedMin = Math.max(0, Math.floor((Date.now() - started) / 60000));
      button.textContent = elapsedMin ? `収集中 ${elapsedMin}分` : '収集中…';
      if (policy) policy.textContent = '各情報元を巡回・判定中…';
      await sleep(POLL_MS);

      try {
        const payload = await fetchLatestPayload();
        const generated = payload.generated_at || null;
        const changed = generated && generated !== beforeGenerated &&
          (!beforeGenerated || Date.parse(generated) > Date.parse(beforeGenerated));
        if (changed && applyPayload(payload)) {
          button.textContent = '更新完了';
          if (policy) policy.textContent = `手動収集完了 · ${payload.count ?? (payload.items || []).length}件`;
          notify(`収集完了：${payload.count ?? (payload.items || []).length}件を反映・保存`);
          await sleep(1200);
          return;
        }
      } catch {
        // Temporary CDN/deploy lag: keep polling.
      }
    }

    if (policy) policy.textContent = oldPolicy || '自動収集';
    throw new Error('収集は継続中です。しばらくしてから再度更新してください');
  }

  function bind() {
    const button = document.querySelector('#syncBtn');
    if (!button || button.dataset.manualRefreshBound) return;
    button.dataset.manualRefreshBound = '1';

    button.addEventListener('click', async event => {
      const demo = document.querySelector('#demoMode');
      if (demo?.checked) return;
      event.preventDefault();
      event.stopImmediatePropagation();

      try {
        await startCollection(button);
      } catch (error) {
        notify(error?.message || '更新失敗');
      } finally {
        button.disabled = false;
        if (button.textContent !== '更新完了') button.textContent = '更新';
        else setTimeout(() => { button.textContent = '更新'; }, 700);
      }
    }, true);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bind, { once: true });
  } else {
    bind();
  }
})();