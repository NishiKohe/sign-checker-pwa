/* Date presentation and a conservative client guard for previously cached old items. */
(() => {
  'use strict';
  const previousExpired = isExpired;
  const previousRender = render;
  const FIELDS = [
    ['published_at', 'ページ掲載'],
    ['updated_at', 'ページ更新'],
    ['release_at', '商品発売'],
    ['apply_start', '応募・販売開始'],
    ['apply_end', '応募・販売終了'],
    ['event_start', '開催開始'],
    ['event_end', '開催終了']
  ];
  const toMs = value => {
    const ms = Date.parse(value || '');
    return Number.isFinite(ms) ? ms : null;
  };
  isExpired = function(item, now = Date.now()) {
    if (previousExpired(item, now)) return true;
    if (item.auction_kind === 'daily') return false;
    // A new registration or event can refer to a book originally published years ago.
    if (['apply_start', 'apply_end', 'event_start', 'event_end'].some(key => {
      const ms = toMs(item[key]);
      return ms !== null && ms >= now;
    })) return false;
    const publication = toMs(item.published_at);
    const updated = toMs(item.updated_at);
    const oldPublication = publication !== null && publication < now - 540 * 86400000 &&
      !(updated !== null && updated >= now - 90 * 86400000);
    if (oldPublication) return true;
    const title = String(item.title || '');
    const year = new Date(now).getFullYear();
    const titleYears = [...title.matchAll(/(?<!\d)(20\d{2})(?=\s*(?:年|[/.\-]\d{1,2}|\s*(?:フェア|開催|サイン会)))/g)]
      .map(match => Number(match[1]));
    if (titleYears.length && Math.max(...titleYears) < year - 1 &&
      !(publication !== null && publication >= now - 365 * 86400000)) return true;
    return false;
  };

  function renderDatePanel(card, item) {
    const panel = document.createElement('div');
    panel.className = 'source-timeline';
    let count = 0;
    for (const [key, label] of FIELDS) {
      if (!item[key] || (key === 'apply_end' && card.querySelector('.deadline-panel')) ||
          (key === 'event_start' && card.querySelector('.event-date')?.style.display !== 'none')) continue;
      const block = document.createElement('div');
      block.className = 'source-timeline-date';
      const heading = document.createElement('small');
      heading.textContent = label;
      const value = document.createElement('strong');
      value.textContent = fmtDate(item[key]);
      const evidence = item.date_evidence?.[key];
      if (evidence) block.title = `日付の根拠: ${evidence}`;
      block.append(heading, value);
      panel.appendChild(block);
      count++;
    }
    if (count) {
      const anchor = card.querySelector('.event-date') || card.querySelector('.deadline-panel');
      anchor?.insertAdjacentElement('afterend', panel);
    }
    if (item.source === 'LivePocket' && item.livepocket_detail_verified === false) {
      const flag = document.createElement('p');
      flag.className = 'source-date-warning';
      flag.textContent = '主催者サイトの申込リンクから発見 · LivePocket本文は未確認';
      (card.querySelector('.why-line') || card).insertAdjacentElement('afterend', flag);
    }
  }

  render = function() {
    previousRender();
    const items = filtered();
    document.querySelectorAll('#list > .opportunity').forEach((card, index) => {
      const item = items[index];
      if (item) renderDatePanel(card, item);
    });
  };
  render();
})();
