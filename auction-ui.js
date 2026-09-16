/* Presentation-only extension for the daily-auction opportunity type. */
(() => {
  oppLabels.auction = 'オークション';
  acquisitions.auction = 'オークション入札';

  const previousActionLane = isActionLane;
  isActionLane = function (item) {
    if (item.opportunity_type === 'auction' && !item.completed) return true;
    return previousActionLane(item);
  };

  const previousRender = render;
  render = function () {
    previousRender();
    const auctionItems = filtered();
    const cards = document.querySelectorAll('#list > .opportunity');
    cards.forEach((card, index) => {
      const item = auctionItems[index];
      if (!item || item.opportunity_type !== 'auction') return;
      const caption = card.querySelector('.deadline-panel small');
      if (caption) caption.textContent = '入札終了';
      const deadline = card.querySelector('.deadline-main');
      if (deadline && !item.apply_end) deadline.textContent = '終了時刻は商品ページで確認';
      const date = card.querySelector('.event-date');
      if (date) date.style.display = 'none';
      const price = Number(item.auction_price_yen);
      if (price > 0) {
        const meta = card.querySelector('.card-meta');
        if (meta) {
          const el = document.createElement('span');
          el.textContent = `掲載価格 ${new Intl.NumberFormat('ja-JP').format(price)}円（取得時点）`;
          el.className = 'auction-price';
          meta.appendChild(el);
        }
      }
      const completed = card.querySelector('[data-act="completed"]');
      if (completed && !item.completed) completed.textContent = '入札対応完了';
    });
  };
  render();
})();
