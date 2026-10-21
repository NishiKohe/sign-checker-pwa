/* Progressive report cards + source diagnostics; does not mutate user actions. */
(() => {
'use strict';
const $ = s => document.querySelector(s);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const gallery = x => /在廊|個展|原画展|作品展|展示販売|ギャラリー|サイン対応|作家来場/.test([x.title,x.reasons,...(x.tags||[])].join(' '));
const yen = x => {
  const raw = x.price ?? x.price_text ?? x.cost ?? x.amount;
  if(raw !== undefined && raw !== null && raw !== '') return typeof raw === 'number' ? raw.toLocaleString('ja-JP')+'円' : String(raw);
  const match = String(x.title||'').match(/(?:¥|￥)\s*[\d,]+|[\d,]+\s*円/);
  return match ? match[0] : '公式で確認';
};
const format = x => x ? (typeof fmtDate === 'function' ? fmtDate(x) : String(x)) : '未確認';
function health(){
 const host=$('#sourceDiagnostics');if(!host || typeof state === 'undefined')return;
 const feed=state.feed||{}, sources=feed.sources||{},generated=feed.generatedAt;
 const age=generated ? (Date.now()-Date.parse(generated))/3600000 : Infinity;
 const entries=Object.entries(sources);
 const disabled=entries.filter(([,v])=>v.enabled===false);
 const asErrors = v => [v.errors,v.discovery_errors,v.page_errors].flatMap(e => Array.isArray(e)?e:(e?[String(e)]:[]));
 const errors=entries.filter(([,v])=>asErrors(v).length);
 const failed=disabled.length+errors.filter(([k])=>!disabled.some(([n])=>n===k)).length;
 const label= !Number.isFinite(age)?'収集日時不明':age>24?'24時間以上更新なし':age>6?'6時間以上前に収集':'フィード更新済み';
 host.innerHTML='<div class="report-health-top"><strong>収集元の稼働状況</strong><span class="'+(failed||age>6?'report-warn':'report-ok')+'">'+escape(label)+'</span></div>'+
 '<p>最終フィード生成：'+escape(generated?format(generated):'不明')+' ／ 無効・エラー：'+failed+'件 ／ 登録ソース：'+entries.length+'件</p>'+
 '<details><summary>収集元別の状態・エラーを見る</summary><div class="report-source-grid">'+entries.map(([name,v])=>{
 const errs=asErrors(v);
 const status=v.enabled===false?'停止・代替収集':errs.length?'エラーあり':'稼働';
 const stamp=v.last_success_at||v.last_success||v.last_successful_fetch_at;
 return '<div class="report-source"><b>'+escape(name)+'</b><span>'+escape(status)+'</span><small>検出 '+escape(v.active_count??v.count??'不明')+'件 / 最終成功 '+escape(stamp?format(stamp):'未記録')+'</small>'+ (errs.length?'<small class="report-error">'+escape(errs.slice(0,2).join(' / '))+'</small>':'')+'</div>';
 }).join('')+'</div></details><p class="report-note">「最終成功 未記録」は失敗を意味しません。現行フィードにソース別成功日時が保存されていない状態です。停止した収集元の復旧には収集スクリプト側の対応が必要です。</p>';
}

// Flag possible duplicate listings without hiding distinct signup opportunities.
// A change of event date, venue or application route remains a separate opportunity.
const canonical = value => String(value || '').normalize('NFKC').toLowerCase()
  .replace(/[\\s・･_‐‑–—―「」『』()（）]/g, '');
const day = value => String(value || '').slice(0, 10);
function duplicateGroups(items) {
 const groups = new Map();
 for (const item of items || []) {
  const creator = canonical(item.creator);
  const event = day(item.event_start);
  const venue = canonical(item.location);
  const route = canonical(item.apply_url || item.url);
  if (!creator || !event || !venue || !route) continue;
  const key = [creator, event, venue, route].join('|');
  const group = groups.get(key) || [];
  group.push(item);
  groups.set(key, group);
 }
 return [...groups.values()].filter(group => group.length > 1);
}

function cards(){
 const nodes=$('#list .opportunity');const visible=typeof state!=='undefined'?state.items:[];
 const possibleDuplicates = new Set(duplicateGroups(visible).flatMap(group => group.slice(1)));

 nodes.forEach(n=>{
  const title=n.querySelector('h3')?.textContent||'';
  const x=visible.find(v=>v.title===title);
  if(!x || n.querySelector('.report-facts'))return;
  if(possibleDuplicates.has(x)) { const badge=document.createElement('span');badge.className='report-gallery-label';badge.textContent='重複候補・要確認';n.querySelector('.badges')?.appendChild(badge); }

  const isGallery=gallery(x);
  if(isGallery){n.classList.add('report-gallery');const b=document.createElement('span');b.className='report-gallery-label';b.textContent='在廊・展示候補';n.querySelector('.badges')?.appendChild(b);}
  const facts=document.createElement('div');facts.className='report-facts';
  const autograph=x.signature_details||x.autograph_details||x.signed_item||x.signature_type|| (isGallery?'サイン可否は公式で確認':'直筆内容は公式で確認');
  const conditions=x.conditions||x.participation_conditions||x.requirements||x.reasons||'公式で確認';
  const rows=[['作家',x.creator||'未抽出'],['開催',format(x.event_start)],['受付',x.apply_start?format(x.apply_start):'開始日時未確認'],['価格',yen(x)],['直筆内容',autograph],['参加条件',conditions]];
  rows.forEach(([label,value])=>{const div=document.createElement('div');div.className='report-fact';const dt=document.createElement('small');dt.textContent=label;const dd=document.createElement('span');dd.textContent=String(value);div.append(dt,dd);facts.appendChild(div)});
  const why=n.querySelector('.why-line');(why||n.querySelector('.primary-actions'))?.before(facts);
  const link=document.createElement('a');link.className='report-official';link.textContent='公式・一次情報を確認 ↗';link.target='_blank';link.rel='noopener noreferrer';try{const u=new URL(x.url);if(['https:','http:'].includes(u.protocol))link.href=u.href;else return}catch{return}
  facts.appendChild(link);
 });
}
function $$(s){return [...document.querySelectorAll(s)]}
function update(){try{health();cards()}catch(err){console.warn('Report enhancement:',err)}}
const original=render;
render=function(...args){const result=original(...args);update();return result};
update();
})();