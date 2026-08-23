const STORAGE='sign-checker-pwa-v5';
const labels={autograph_event:'サイン会',original_art:'原画・色紙・一点物',signed_book:'サイン本',exhibition:'個展・POP UP',campaign:'応募企画',other:'その他'};
const methods={first_come:'先着',lottery:'抽選',unknown:'方式不明'};
const acquisitions={first_come:'先着',lottery_free:'購入不要抽選',lottery_open:'抽選',lottery_purchase:'購入条件付き抽選',direct_sale:'直接販売',unknown:'方式未判定'};
const $=s=>document.querySelector(s);
let installPrompt=null;

const demo=[
  {id:'1',title:'Na-Ga 直筆サイン会 先着受付',source:'X',creator:'Na-Ga',location:'秋葉原',category:'autograph_event',method:'first_come',acquisition:'first_come',score:130,reasons:'サイン会 / 先着で獲得 / 著名クリエイター',url:'https://example.com',seen:false,ignored:false,favorite:true,completed:false,status:'open',tags:['X','サイン会','先着','Na-Ga','秋葉原','著名クリエイター'],event_start:'2026-09-01T13:00+09:00',apply_start:'2026-08-24T12:00+09:00',apply_end:'2026-08-28T23:59+09:00'},
  {id:'2',title:'村田蓮爾 直筆原画 先着販売',source:'BOOTH',creator:'村田蓮爾',location:'オンライン',category:'original_art',method:'first_come',acquisition:'first_come',score:125,reasons:'原画・直筆 / 先着で獲得 / 著名クリエイター',url:'https://example.com',seen:false,ignored:false,favorite:true,completed:false,status:'open',tags:['BOOTH','原画・色紙・一点物','先着','村田蓮爾','オンライン','一点物・直筆'],event_start:null,apply_start:'2026-08-25T20:00+09:00',apply_end:null},
  {id:'3',title:'あるぷ先生 サイン本 抽選販売',source:'書泉',creator:'あるぷ',location:'神保町',category:'signed_book',method:'lottery',acquisition:'lottery_open',score:88,reasons:'サイン本重点 / 抽選',url:'https://example.com',seen:false,ignored:false,favorite:false,completed:false,status:'open',tags:['書泉','サイン本','抽選','あるぷ','神保町'],event_start:null,apply_start:'2026-08-26T10:00+09:00',apply_end:'2026-09-02T23:59+09:00'}
];

function defaults(){
  return {
    items:[],
    settings:{apiBase:'',watchlist:'Na-Ga, 村田蓮爾, あるぷ',demoMode:false,showExpired:false},
    ui:{tab:'all',q:'',score:'0',sort:'score',source:'all',acquisition:'all',tagFilter:''},
    feed:{generatedAt:null,sources:{}}
  };
}
function load(){
  try{
    const raw=JSON.parse(localStorage.getItem(STORAGE)||'{}');
    return {...defaults(),...raw,settings:{...defaults().settings,...(raw.settings||{})},ui:{...defaults().ui,...(raw.ui||{})},feed:{...defaults().feed,...(raw.feed||{})}};
  }catch{return defaults()}
}
let state=load();
function save(){localStorage.setItem(STORAGE,JSON.stringify(state))}
function toast(t){const e=document.createElement('div');e.className='toast';e.textContent=t;document.body.appendChild(e);setTimeout(()=>e.remove(),2200)}
function safeUrl(v){try{const u=new URL(v,location.href);return ['http:','https:'].includes(u.protocol)?u.href:'#'}catch{return '#'}}
function statusLabel(v){return v==='open'?'受付中':v==='closed'?'終了':'状況未判定'}

function fmtDate(v){
  if(!v)return '未取得';
  const d=new Date(v);if(Number.isNaN(d.getTime()))return String(v);
  const dateOnly=/T00:00(?::00)?(?:\.000)?(?:\+09:00|Z|[+-]\d\d:\d\d)?$/.test(String(v));
  const opts=dateOnly?{year:'numeric',month:'numeric',day:'numeric'}:{year:'numeric',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false};
  return new Intl.DateTimeFormat('ja-JP',{...opts,timeZone:'Asia/Tokyo'}).format(d);
}
function normalizedExpiry(v){
  if(!v)return NaN;let ms=Date.parse(v);if(!Number.isFinite(ms))return NaN;
  if(/T00:00(?::00)?(?:\.000)?(?:\+09:00|Z|[+-]\d\d:\d\d)?$/.test(String(v)))ms+=24*60*60*1000-1;
  return ms;
}
function isExpired(x,now=Date.now()){
  if(x.expired===true||x.status==='closed')return true;
  const deadline=normalizedExpiry(x.apply_end);if(Number.isFinite(deadline))return deadline<now;
  const eventEnd=normalizedExpiry(x.event_end||x.event_start);if(Number.isFinite(eventEnd))return eventEnd<now;
  return false;
}
function visibleBase(){return state.items.filter(x=>!x.ignored&&(state.settings.showExpired||!isExpired(x)))}

function acquisitionOf(x){
  if(x.acquisition)return x.acquisition;
  if(x.method==='first_come')return 'first_come';
  if(x.method==='lottery')return 'lottery_open';
  return 'unknown';
}
function tagsFor(x){
  const vals=[];const add=v=>{v=String(v||'').trim();if(v&&!vals.includes(v))vals.push(v)};
  (x.tags||[]).forEach(add);
  add(x.source);add(labels[x.category]||x.category);add(acquisitions[acquisitionOf(x)]);add(x.creator);add(x.location);
  if(x.subject_type==='performer')add('声優・出演者');
  if(x.subject_type==='performer_exception')add('著名出演者');
  if(x.completed)add('応募・購入完了');
  return vals;
}
function searchText(x){return [x.title,x.creator,x.location,x.source,x.reasons,statusLabel(x.status),acquisitions[acquisitionOf(x)],...(x.dates||[]),...tagsFor(x),x.event_start,x.apply_start,x.apply_end].filter(Boolean).join(' ').toLowerCase()}

const LEARN_EXCLUDED_TAGS=new Set(['受付前','締切間近','受付中','販売中候補','日時未取得','有効','応募・購入完了','オンライン']);
function inc(map,key,n=1){key=String(key||'').trim();if(key)map.set(key,(map.get(key)||0)+n)}
function learningProfile(){
  const p={count:0,creator:new Map(),category:new Map(),acquisition:new Map(),source:new Map(),tag:new Map()};
  for(const x of state.items.filter(v=>v.completed)){
    p.count++;
    inc(p.creator,x.creator,1);inc(p.category,x.category,1);inc(p.acquisition,acquisitionOf(x),1);inc(p.source,x.source,1);
    const generic=new Set([x.source,labels[x.category]||x.category,acquisitions[acquisitionOf(x)],x.creator,x.location]);
    for(const t of (x.tags||[])){if(!generic.has(t)&&!LEARN_EXCLUDED_TAGS.has(t))inc(p.tag,t,1)}
  }
  return p;
}
function personalizationBoost(x,p=learningProfile()){
  if(!p.count)return 0;
  let b=0;
  if(x.creator)b+=Math.min(18,(p.creator.get(x.creator)||0)*6);
  b+=Math.min(8,(p.category.get(x.category)||0)*2);
  b+=Math.min(6,(p.acquisition.get(acquisitionOf(x))||0)*1.5);
  b+=Math.min(4,(p.source.get(x.source)||0));
  let tagBoost=0;
  for(const t of (x.tags||[]))tagBoost+=(p.tag.get(t)||0)*0.75;
  b+=Math.min(12,tagBoost);
  return Math.min(30,Math.round(b));
}
function effectiveScore(x,p=learningProfile()){return Math.min(170,Number(x.score||0)+personalizationBoost(x,p))}

function sortItems(items,mode,p){
  const copy=[...items];
  if(mode==='score')return copy.sort((a,b)=>effectiveScore(b,p)-effectiveScore(a,p));
  return copy.sort((a,b)=>{
    const av=a[mode]?Date.parse(a[mode]):Number.POSITIVE_INFINITY;
    const bv=b[mode]?Date.parse(b[mode]):Number.POSITIVE_INFINITY;
    if(av!==bv)return av-bv;
    return effectiveScore(b,p)-effectiveScore(a,p);
  });
}
function filtered(){
  const q=(state.ui.q||'').toLowerCase().trim();
  const min=Number(state.ui.score||0),tab=state.ui.tab,mode=state.ui.sort||'score';
  const source=state.ui.source||'all',acq=state.ui.acquisition||'all',tag=state.ui.tagFilter||'';
  const p=learningProfile();
  const base=tab==='completed'?state.items.filter(x=>x.completed&&!x.ignored):visibleBase();
  const items=base
    .filter(x=>effectiveScore(x,p)>=min)
    .filter(x=>source==='all'||x.source===source)
    .filter(x=>acq==='all'||acquisitionOf(x)===acq)
    .filter(x=>tab==='all'||tab==='completed'||(tab==='urgent'&&effectiveScore(x,p)>=85)||(tab==='favorites'&&x.favorite)||x.category===tab)
    .filter(x=>!tag||tagsFor(x).includes(tag))
    .filter(x=>!q||searchText(x).includes(q));
  return sortItems(items,mode,p);
}

function renderSourceControls(all){
  const sources=[...new Set(all.map(x=>x.source).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'ja'));
  const sel=$('#sourceFilter');sel.textContent='';
  const any=document.createElement('option');any.value='all';any.textContent='すべての情報元';sel.appendChild(any);
  sources.forEach(s=>{const o=document.createElement('option');o.value=s;o.textContent=s;sel.appendChild(o)});
  if(state.ui.source!=='all'&&!sources.includes(state.ui.source))state.ui.source='all';
  sel.value=state.ui.source||'all';

  const counts=new Map();all.forEach(x=>{if(x.source)counts.set(x.source,(counts.get(x.source)||0)+1)});
  const box=$('#sourceChips');box.textContent='';
  [...counts.entries()].sort((a,b)=>b[1]-a[1]).forEach(([s,n])=>{
    const b=document.createElement('button');b.className='source-chip'+(state.ui.source===s?' active':'');b.dataset.source=s;b.textContent=`${s} ${n}`;box.appendChild(b);
  });
}
function renderActiveTag(){
  const box=$('#activeTag');box.textContent='';
  if(!state.ui.tagFilter){box.classList.add('hidden');return}
  box.classList.remove('hidden');
  const span=document.createElement('span');span.textContent=`タグ: ${state.ui.tagFilter}`;box.appendChild(span);
  const b=document.createElement('button');b.dataset.clearTag='1';b.textContent='解除';box.appendChild(b);
}
function setDateBox(card,field,value){const e=card.querySelector(`[data-date="${field}"] .date-value`);if(e)e.textContent=fmtDate(value)}
function addAction(container,label,act,id,extraClass=''){const b=document.createElement('button');b.className=('secondary '+extraClass).trim();b.dataset.act=act;b.dataset.id=id;b.textContent=label;container.appendChild(b)}
function addTag(container,text,x){
  if(!text)return;
  const b=document.createElement('button');b.className='item-tag';b.textContent=text;
  if(text===x.source){b.classList.add('source-tag');b.dataset.source=x.source}else b.dataset.filterTag=text;
  container.appendChild(b);
}

function render(){
  $('#q').value=state.ui.q||'';$('#scoreFilter').value=state.ui.score||'0';$('#sortMode').value=state.ui.sort||'score';$('#acquisitionFilter').value=state.ui.acquisition||'all';
  $('#apiBase').value=state.settings.apiBase||'';$('#watchlist').value=state.settings.watchlist||'';$('#demoMode').checked=!!state.settings.demoMode;$('#showExpired').checked=!!state.settings.showExpired;
  document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===state.ui.tab));

  const all=visibleBase();const p=learningProfile();renderSourceControls(state.ui.tab==='completed'?state.items.filter(x=>x.completed&&!x.ignored):all);renderActiveTag();
  $('#statUnseen').textContent=all.filter(x=>!x.seen).length;$('#statUrgent').textContent=all.filter(x=>effectiveScore(x,p)>=85).length;$('#statCompleted').textContent=state.items.filter(x=>x.completed&&!x.ignored).length;$('#statTotal').textContent=all.length;
  const learn=$('#learnSummary');if(learn)learn.textContent=p.count?`${p.count}件の完了履歴から並び順を学習中`:'応募・購入完了を付けると好みを学習します';

  const list=$('#list');list.textContent='';const items=filtered();$('#resultCount').textContent=`${items.length}件`;
  if(!items.length){list.innerHTML='<div class="card empty">条件に合う案件はありません。終了済み・期限切れ案件は通常非表示です。</div>';return}

  for(const x of items){
    const boost=personalizationBoost(x,p),score=effectiveScore(x,p);
    const n=$('#itemTpl').content.firstElementChild.cloneNode(true);n.classList.toggle('urgent',score>=85);n.classList.toggle('seen',x.seen);n.classList.toggle('completed',!!x.completed);
    n.querySelector('h3').textContent=x.title||'(タイトル未取得)';
    n.querySelector('.score-value').textContent=score;
    const scoreLabel=n.querySelector('.score-box small');if(boost>0)scoreLabel.textContent=`優先度 +${boost}`;
    n.querySelector('.creator').textContent=x.creator||'作家未抽出';n.querySelector('.location').textContent=x.location||'場所未抽出';

    const tagBox=n.querySelector('.item-tags');tagsFor(x).slice(0,12).forEach(t=>addTag(tagBox,t,x));
    const status=document.createElement('span');status.className='status-text';status.textContent=x.completed?'応募・購入完了':statusLabel(x.status);n.querySelector('.card-meta').appendChild(status);

    setDateBox(n,'event_start',x.event_start);setDateBox(n,'apply_start',x.apply_start);setDateBox(n,'apply_end',x.apply_end);
    n.querySelector('.reason').textContent=(x.reasons||'判定根拠未取得')+(boost?` / あなたの完了傾向 +${boost}`:'');

    const actions=n.querySelector('.item-actions');actions.textContent='';
    const link=document.createElement('a');link.href=safeUrl(x.apply_url||x.url);link.target='_blank';link.rel='noopener';link.textContent=x.apply_url?'申込ページ':'元ページ';actions.appendChild(link);
    if(x.apply_url&&x.url){const src=document.createElement('a');src.href=safeUrl(x.url);src.target='_blank';src.rel='noopener';src.textContent='情報元';actions.appendChild(src)}
    addAction(actions,x.completed?'完了解除':'応募・購入完了','completed',x.id,x.completed?'completed-action active':'completed-action');
    addAction(actions,x.seen?'未読へ':'既読','seen',x.id);addAction(actions,x.favorite?'★解除':'★','favorite',x.id);addAction(actions,'除外','ignore',x.id);
    list.appendChild(n);
  }
}

function boost(items){
  const names=(state.settings.watchlist||'').split(',').map(s=>s.trim()).filter(Boolean);
  return items.map(x=>{
    let add=0,rs='';for(const name of names){if(`${x.title||''} ${x.creator||''}`.includes(name)){const b=name==='Na-Ga'?40:15;add+=b;rs+=` / ウォッチ:${name} +${b}`}}
    return add?{...x,score:Math.min(140,Number(x.score||0)+add),reasons:(x.reasons||'')+rs}:x;
  });
}
function mergeFeed(items){
  const old=new Map(state.items.map(x=>[x.id,x]));const incoming=boost(items);const ids=new Set(incoming.map(x=>x.id));
  const merged=incoming.map(x=>{const prev=old.get(x.id)||{};return{...x,seen:!!prev.seen,ignored:!!prev.ignored,favorite:!!prev.favorite,completed:!!prev.completed,completed_at:prev.completed_at||null}});
  for(const prev of state.items){if(prev.completed&&!ids.has(prev.id))merged.push({...prev,archived:true})}
  state.items=merged;
}
async function loadStaticFeed(){const r=await fetch(`./data/items.json?t=${Date.now()}`,{cache:'no-store'});if(!r.ok)throw new Error('収集データ取得失敗');const p=await r.json();mergeFeed(Array.isArray(p.items)?p.items:[]);state.feed={generatedAt:p.generated_at||null,sources:p.sources||{}};save();render();return visibleBase().length}
async function apiItems(){const baseUrl=(state.settings.apiBase||'').replace(/\/$/,'');if(!baseUrl)throw new Error('APIベースURL未設定');const r=await fetch(`${baseUrl}/api/items`);if(!r.ok)throw new Error('API接続失敗');const a=await r.json();return boost(a.map((x,i)=>({...x,id:String(x.id??x.url??i),score:Number(x.score||0),seen:!!x.seen,ignored:!!x.ignored,favorite:!!x.favorite,completed:!!x.completed,completed_at:x.completed_at||null})))}
function upsert(items){const m=new Map(state.items.map(x=>[x.id,x]));items.forEach(x=>m.set(x.id,{...(m.get(x.id)||{}),...x}));state.items=[...m.values()]}

function bindSelect(id,key){$(id).addEventListener('change',e=>{state.ui[key]=e.target.value;save();render()})}
$('#q').addEventListener('input',e=>{state.ui.q=e.target.value;save();render()});
bindSelect('#scoreFilter','score');bindSelect('#sortMode','sort');bindSelect('#sourceFilter','source');bindSelect('#acquisitionFilter','acquisition');

document.addEventListener('click',e=>{
  const tab=e.target.closest('[data-tab]');if(tab){state.ui.tab=tab.dataset.tab;save();render();return}
  const source=e.target.closest('[data-source]');if(source){state.ui.source=source.dataset.source;save();render();return}
  const tag=e.target.closest('[data-filter-tag]');if(tag){state.ui.tagFilter=tag.dataset.filterTag;save();render();return}
  if(e.target.closest('[data-clear-tag]')){state.ui.tagFilter='';save();render();return}
  const a=e.target.closest('[data-act]');if(a){
    const x=state.items.find(v=>v.id===a.dataset.id);if(!x)return;
    if(a.dataset.act==='seen')x.seen=!x.seen;
    if(a.dataset.act==='favorite')x.favorite=!x.favorite;
    if(a.dataset.act==='ignore')x.ignored=true;
    if(a.dataset.act==='completed'){
      x.completed=!x.completed;x.completed_at=x.completed?new Date().toISOString():null;if(x.completed)x.seen=true;
      toast(x.completed?'応募・購入完了として記録しました':'完了を解除しました');
    }
    save();render();
  }
});

$('#saveSettingsBtn').addEventListener('click',async()=>{state.settings.apiBase=$('#apiBase').value.trim();state.settings.watchlist=$('#watchlist').value.trim();state.settings.demoMode=$('#demoMode').checked;state.settings.showExpired=$('#showExpired').checked;save();if(state.settings.demoMode&&state.items.length===0)state.items=structuredClone(demo);else if(!state.settings.demoMode){try{await loadStaticFeed()}catch{}}render();toast('保存しました')});
$('#seedBtn').addEventListener('click',()=>{state.items=structuredClone(demo);state.settings.demoMode=true;save();render();toast('デモ初期化')});
$('#syncBtn').addEventListener('click',async()=>{const b=$('#syncBtn');b.disabled=true;b.textContent='同期中…';try{if(state.settings.demoMode){state.items=structuredClone(demo);save();render();toast('デモ同期')}else if(state.settings.apiBase){const baseUrl=(state.settings.apiBase||'').replace(/\/$/,'');await fetch(`${baseUrl}/api/collect`,{method:'POST'});upsert(await apiItems());save();render();toast('同期しました')}else{const n=await loadStaticFeed();toast(`${n}件を表示中`)}}catch(err){toast(err.message||'同期失敗')}finally{b.disabled=false;b.textContent='同期'}});

if('serviceWorker'in navigator)window.addEventListener('load',()=>navigator.serviceWorker.register('./sw.js?v=13').catch(()=>{}));
window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();installPrompt=e;$('#installBtn').classList.remove('hidden')});
$('#installBtn').addEventListener('click',async()=>{if(!installPrompt)return toast('Chromeメニューの「ホーム画面に追加」も利用できます');installPrompt.prompt();await installPrompt.userChoice;installPrompt=null;$('#installBtn').classList.add('hidden')});

render();
if(!state.settings.demoMode&&!state.settings.apiBase)loadStaticFeed().catch(()=>{});
