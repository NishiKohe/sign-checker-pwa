const STORAGE='sign-checker-pwa-v6';
const $=s=>document.querySelector(s);
const labels={autograph_event:'サイン会',original_art:'原画・色紙',signed_book:'サイン本',exhibition:'展示・POP UP',campaign:'応募企画',other:'その他'};
const acquisitions={first_come:'先着',lottery_free:'購入不要抽選',lottery_open:'抽選',lottery_purchase:'購入条件付き抽選',direct_sale:'直接販売',unknown:'方式未判定'};
const oppLabels={lottery:'抽選',sale:'販売',event:'イベント',campaign:'応募企画'};
const laneInfo={
  action:['ACTION','今日やる','受付中・販売中・締切間近を、価値と期限で並べます。'],
  new:['NEW','新着','初めて検出してから48時間以内の案件です。'],
  critical:['HIGH VALUE','高価値','Sランクを最優先、続いてAランクを表示します。'],
  watching:['WATCH','追う','★を付けた案件だけをまとめます。'],
  completed:['HISTORY','応募・購入完了','完了履歴はあなた向け順位の学習データになります。'],
  all:['ALL','すべて','現在有効な案件を横断表示します。'],
};
let installPrompt=null;

const demo=[
  {id:'demo1',title:'成年コミックフェア サイン本販売',source:'書泉',creator:'',location:'神保町',category:'signed_book',acquisition:'lottery_open',opportunity_type:'lottery',primary_action:'apply',action_label:'応募する',score:112,value_score:128,value_tier:'S',alert_candidate:true,alert_event:true,reasons:'大量サイン本 / 成人向け / 抽選',url:'https://example.com',apply_url:'https://example.com/apply',status:'open',tags:['新着','書泉','サイン本','成人向け','大量サイン本','抽選','価値S'],event_start:'2026-09-21T13:00+09:00',apply_end:'2026-09-12T23:59+09:00'},
  {id:'demo2',title:'村田蓮爾 直筆原画 先着販売',source:'space caiman',creator:'村田蓮爾',location:'神田',category:'original_art',acquisition:'first_come',opportunity_type:'sale',primary_action:'buy',action_label:'購入する',score:130,value_score:140,value_tier:'S',alert_candidate:true,alert_event:true,reasons:'直筆原画 / 一点物 / 優先作家 / 先着',url:'https://example.com',status:'open',tags:['新着','space caiman','原画・色紙','一点物','村田蓮爾','先着','価値S'],event_start:null,apply_end:null},
  {id:'demo3',title:'イラストレーター新刊 サイン本販売',source:'大垣書店',creator:'あるぷ',location:'オンライン',category:'signed_book',acquisition:'direct_sale',opportunity_type:'sale',primary_action:'buy',action_label:'購入する',score:90,value_score:82,value_tier:'A',alert_candidate:false,alert_event:false,reasons:'サイン本 / 直接販売',url:'https://example.com',status:'open',tags:['大垣書店','サイン本','直接販売','価値A'],event_start:null,apply_end:null},
];

function defaults(){return{
  items:[],
  settings:{apiBase:'',watchlist:'Na-Ga, 村田蓮爾, あるぷ',demoMode:false,showExpired:false},
  ui:{lane:'action',q:'',source:'all',tier:'all',acquisition:'all',type:'all',sort:'smart',tagFilter:''},
  feed:{generatedAt:null,sources:{},schemaVersion:null,policy:'',newCount:0,opportunityCounts:{},tierCounts:{}}
}}
function load(){
  try{
    const raw=JSON.parse(localStorage.getItem(STORAGE)||'{}');
    const d=defaults();
    const oldUi=raw.ui||{};
    const lane=oldUi.lane||(['completed','favorites'].includes(oldUi.tab)?(oldUi.tab==='favorites'?'watching':'completed'):'action');
    return {...d,...raw,settings:{...d.settings,...(raw.settings||{})},ui:{...d.ui,...oldUi,lane},feed:{...d.feed,...(raw.feed||{})}};
  }catch{return defaults()}
}
let state=load();
function save(){localStorage.setItem(STORAGE,JSON.stringify(state))}
function toast(t){const e=document.createElement('div');e.className='toast';e.textContent=t;document.body.appendChild(e);setTimeout(()=>e.remove(),2400)}
function safeUrl(v){try{const u=new URL(v,location.href);return ['http:','https:'].includes(u.protocol)?u.href:'#'}catch{return '#'}}
function esc(v){return String(v??'')}
function fmtDate(v){
  if(!v)return '未取得';const d=new Date(v);if(Number.isNaN(d.getTime()))return String(v);
  const dateOnly=/T00:00(?::00)?(?:\.000)?(?:\+09:00|Z|[+-]\d\d:\d\d)?$/.test(String(v));
  const opt=dateOnly?{month:'numeric',day:'numeric',weekday:'short'}:{month:'numeric',day:'numeric',weekday:'short',hour:'2-digit',minute:'2-digit',hour12:false};
  return new Intl.DateTimeFormat('ja-JP',{...opt,timeZone:'Asia/Tokyo'}).format(d);
}
function fmtFeed(v){if(!v)return '--';const d=new Date(v);if(Number.isNaN(d.getTime()))return '--';return new Intl.DateTimeFormat('ja-JP',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Asia/Tokyo'}).format(d)}
function normalizedExpiry(v){if(!v)return NaN;let ms=Date.parse(v);if(!Number.isFinite(ms))return NaN;if(/T00:00(?::00)?(?:\.000)?(?:\+09:00|Z|[+-]\d\d:\d\d)?$/.test(String(v)))ms+=86400000-1;return ms}
function isExpired(x,now=Date.now()){
  if(x.expired===true||x.lifecycle==='expired'||x.status==='closed')return true;
  const end=normalizedExpiry(x.apply_end);if(Number.isFinite(end)&&end<now)return true;
  if(['autograph_event','campaign','exhibition','original_art'].includes(x.category)){
    const ev=normalizedExpiry(x.event_end||x.event_start);if(Number.isFinite(ev)&&ev<now)return true;
  }
  return false;
}
function acquisitionOf(x){if(x.acquisition)return x.acquisition;if(x.method==='first_come')return'first_come';if(x.method==='lottery')return'lottery_open';return'unknown'}
function oppType(x){
  if(x.opportunity_type)return x.opportunity_type;const a=acquisitionOf(x);
  if(a.startsWith('lottery'))return'lottery';
  if(['signed_book','original_art'].includes(x.category))return'sale';
  if(x.category==='campaign')return'campaign';return'event';
}
function serverValue(x){if(Number.isFinite(Number(x.value_score)))return Number(x.value_score);return Math.min(140,Math.round(Number(x.score||0)*.85))}
function tierOf(x){if(x.value_tier)return x.value_tier;const v=serverValue(x);return v>=100?'S':v>=80?'A':v>=60?'B':'C'}
function isNew(x){
  if((x.tags||[]).includes('新着'))return true;
  const ms=Date.parse(x.first_seen_at||'');return Number.isFinite(ms)&&Date.now()-ms>=0&&Date.now()-ms<=48*3600000;
}
function deadlineHours(x){const ms=Date.parse(x.apply_end||'');return Number.isFinite(ms)?(ms-Date.now())/3600000:null}
function eventHours(x){const ms=Date.parse(x.event_start||'');return Number.isFinite(ms)?(ms-Date.now())/3600000:null}
function countdown(x){
  const h=deadlineHours(x);if(h===null)return'';if(h<0)return'締切済み';if(h<1)return`あと${Math.max(1,Math.round(h*60))}分`;if(h<48)return`あと${Math.ceil(h)}時間`;return`あと${Math.ceil(h/24)}日`;
}
function tagsFor(x){
  const vals=[];const add=v=>{v=String(v||'').trim();if(v&&!vals.includes(v))vals.push(v)};
  (x.tags||[]).forEach(add);add(x.source);add(labels[x.category]||x.category);add(oppLabels[oppType(x)]);add(acquisitions[acquisitionOf(x)]);add(x.creator);add(x.location);add(`価値${tierOf(x)}`);if(x.completed)add('応募・購入完了');return vals;
}
function searchText(x){return[x.title,x.creator,x.location,x.source,x.reasons,x.alert_reason,x.action_label,oppLabels[oppType(x)],acquisitions[acquisitionOf(x)],...tagsFor(x),...(x.dates||[])].filter(Boolean).join(' ').toLowerCase()}
function visibleBase(){return state.items.filter(x=>!x.ignored&&(state.settings.showExpired||!isExpired(x)))}

const LEARN_EXCLUDED=new Set(['受付前','締切間近','受付中','販売中候補','日時未取得','有効','応募・購入完了','新着','更新あり','オンライン','価値S','価値A','価値B','価値C']);
function inc(map,k,n=1){k=String(k||'').trim();if(k)map.set(k,(map.get(k)||0)+n)}
function learningProfile(){
  const p={count:0,creator:new Map(),type:new Map(),acq:new Map(),source:new Map(),tag:new Map()};
  for(const x of state.items.filter(v=>v.completed)){
    p.count++;inc(p.creator,x.creator);inc(p.type,oppType(x));inc(p.acq,acquisitionOf(x));inc(p.source,x.source);
    const generic=new Set([x.source,x.creator,x.location,oppLabels[oppType(x)],acquisitions[acquisitionOf(x)]]);
    for(const t of(x.tags||[]))if(!generic.has(t)&&!LEARN_EXCLUDED.has(t))inc(p.tag,t);
  }return p;
}
function personalizationBoost(x,p=learningProfile()){
  if(!p.count)return 0;let b=0;
  if(x.creator)b+=Math.min(18,(p.creator.get(x.creator)||0)*6);
  b+=Math.min(8,(p.type.get(oppType(x))||0)*2);
  b+=Math.min(6,(p.acq.get(acquisitionOf(x))||0)*1.5);
  b+=Math.min(4,p.source.get(x.source)||0);
  let tb=0;for(const t of(x.tags||[]))tb+=(p.tag.get(t)||0)*.7;b+=Math.min(10,tb);
  return Math.min(28,Math.round(b));
}
function rankScore(x,p){return serverValue(x)+personalizationBoost(x,p)}

function isActionLane(x){
  if(x.completed)return false;
  const action=x.primary_action||'';const h=deadlineHours(x);const eh=eventHours(x);
  if(['apply','buy'].includes(action))return true;
  if(h!==null&&h>=0&&h<=168)return true;
  if(['accepting','upcoming','on_sale_candidate','closing_soon'].includes(x.action_state))return true;
  if(oppType(x)==='event'&&eh!==null&&eh>=0&&eh<=14*24)return true;
  return false;
}
function laneMatch(x,lane){
  if(lane==='completed')return!!x.completed;
  if(x.completed)return false;
  if(lane==='new')return isNew(x);
  if(lane==='critical')return['S','A'].includes(tierOf(x));
  if(lane==='watching')return!!x.favorite;
  if(lane==='all')return true;
  return isActionLane(x);
}
function sortItems(items,mode,p){
  const arr=[...items];
  if(mode==='deadline')return arr.sort((a,b)=>{const ah=deadlineHours(a),bh=deadlineHours(b);return(ah===null?1e9:Math.max(ah,0))-(bh===null?1e9:Math.max(bh,0))||rankScore(b,p)-rankScore(a,p)});
  if(mode==='newest')return arr.sort((a,b)=>(Date.parse(b.first_seen_at||0)||0)-(Date.parse(a.first_seen_at||0)||0)||rankScore(b,p)-rankScore(a,p));
  if(mode==='value')return arr.sort((a,b)=>serverValue(b)-serverValue(a)||rankScore(b,p)-rankScore(a,p));
  return arr.sort((a,b)=>{
    const aDue=deadlineHours(a),bDue=deadlineHours(b);
    const au=aDue!==null&&aDue>=0&&aDue<=72?25-Math.min(24,aDue/3):0;
    const bu=bDue!==null&&bDue>=0&&bDue<=72?25-Math.min(24,bDue/3):0;
    return(rankScore(b,p)+bu)-(rankScore(a,p)+au);
  });
}
function filtered(){
  const p=learningProfile(),q=(state.ui.q||'').trim().toLowerCase();
  const items=visibleBase().filter(x=>laneMatch(x,state.ui.lane||'action'))
    .filter(x=>state.ui.type==='all'||oppType(x)===state.ui.type)
    .filter(x=>state.ui.source==='all'||x.source===state.ui.source)
    .filter(x=>state.ui.tier==='all'||tierOf(x)===state.ui.tier)
    .filter(x=>state.ui.acquisition==='all'||acquisitionOf(x)===state.ui.acquisition)
    .filter(x=>!state.ui.tagFilter||tagsFor(x).includes(state.ui.tagFilter))
    .filter(x=>!q||searchText(x).includes(q));
  return sortItems(items,state.ui.sort||'smart',p);
}

function renderSourceFilter(items){
  const sources=[...new Set(items.map(x=>x.source).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'ja'));
  const sel=$('#sourceFilter');sel.textContent='';const any=document.createElement('option');any.value='all';any.textContent='すべての情報元';sel.appendChild(any);
  for(const s of sources){const o=document.createElement('option');o.value=s;o.textContent=s;sel.appendChild(o)}
  if(state.ui.source!=='all'&&!sources.includes(state.ui.source))state.ui.source='all';sel.value=state.ui.source||'all';
}
function renderTagFilter(){const box=$('#activeTag');box.textContent='';if(!state.ui.tagFilter){box.classList.add('hidden');return}box.classList.remove('hidden');const s=document.createElement('span');s.textContent=`タグ: ${state.ui.tagFilter}`;const b=document.createElement('button');b.className='ghost';b.dataset.clearTag='1';b.textContent='解除';box.append(s,b)}
function addTag(box,text,x){if(!text)return;const b=document.createElement('button');b.className='item-tag';b.textContent=text;if(text===x.source)b.dataset.source=text;else b.dataset.filterTag=text;box.appendChild(b)}
function addManage(box,label,act,id,cls=''){const b=document.createElement('button');b.className=('manage '+cls).trim();b.dataset.act=act;b.dataset.id=id;b.textContent=label;box.appendChild(b)}
function addLink(box,label,url,primary=false){const a=document.createElement('a');a.href=safeUrl(url);a.target='_blank';a.rel='noopener';a.textContent=label;a.className=primary?'primary-link':'secondary-link';box.appendChild(a)}

function renderHealth(){
  const box=$('#sourceHealth');box.textContent='';const sources=state.feed.sources||{};let bad=0,total=0;
  for(const [key,m0] of Object.entries(sources)){
    if(!m0||typeof m0!=='object')continue;total++;const m=m0;const stale=Number(m.stale_fallback_count||0)>0;const disabled=m.enabled===false;const empty=m.enabled===true&&Number(m.active_count??m.count??0)===0;const stateName=stale?'前回値':disabled?'停止':empty?'0件':'正常';if(stale||disabled||empty)bad++;
    const row=document.createElement('div');row.className='health-row '+(stale||disabled||empty?'warn':'ok');
    const name=document.createElement('strong');name.textContent=key;const st=document.createElement('span');st.textContent=stateName;const count=document.createElement('small');count.textContent=`${Number(m.active_count??m.count??0)}件`;row.append(name,st,count);box.appendChild(row);
  }
  $('#healthSummary').textContent=bad?`· 要確認 ${bad}`:`· ${total}系統`;
}
function renderLaneHead(){const info=laneInfo[state.ui.lane]||laneInfo.action;$('#laneKicker').textContent=info[0];$('#laneTitle').textContent=info[1];$('#laneHelp').textContent=info[2]}

function render(){
  const all=visibleBase(),p=learningProfile();
  $('#q').value=state.ui.q||'';$('#tierFilter').value=state.ui.tier||'all';$('#acquisitionFilter').value=state.ui.acquisition||'all';$('#sortMode').value=state.ui.sort||'smart';
  $('#watchlist').value=state.settings.watchlist||'';$('#showExpired').checked=!!state.settings.showExpired;$('#demoMode').checked=!!state.settings.demoMode;$('#apiBase').value=state.settings.apiBase||'';
  renderSourceFilter(all);renderTagFilter();renderHealth();renderLaneHead();
  document.querySelectorAll('[data-lane]').forEach(b=>b.classList.toggle('active',b.dataset.lane===state.ui.lane));
  document.querySelectorAll('[data-type]').forEach(b=>b.classList.toggle('active',b.dataset.type===state.ui.type));
  $('#feedTime').textContent=fmtFeed(state.feed.generatedAt);$('#feedPolicy').textContent=state.feed.schemaVersion?`schema v${state.feed.schemaVersion} · 自動収集`:'自動収集';
  $('#statNew').textContent=all.filter(isNew).length;$('#statCritical').textContent=all.filter(x=>tierOf(x)==='S'&&!x.completed).length;
  $('#statDue').textContent=all.filter(x=>{const h=deadlineHours(x);return!x.completed&&h!==null&&h>=0&&h<=72}).length;
  $('#statCompleted').textContent=state.items.filter(x=>x.completed&&!x.ignored).length;

  const list=$('#list');list.textContent='';const items=filtered();$('#resultCount').textContent=`${items.length}件`;
  if(!items.length){const e=document.createElement('div');e.className='empty card';e.textContent='この条件で今すぐ見る案件はありません。';list.appendChild(e);return}

  for(const x of items){
    const n=$('#itemTpl').content.firstElementChild.cloneNode(true);const tier=tierOf(x),boost=personalizationBoost(x,p),value=serverValue(x);
    n.classList.toggle('tier-s',tier==='S');n.classList.toggle('tier-a',tier==='A');n.classList.toggle('seen',!!x.seen);n.classList.toggle('completed',!!x.completed);n.classList.toggle('fresh',isNew(x));
    n.querySelector('.tier-badge').textContent=`${tier} TIER`;n.querySelector('.tier-badge').classList.add(`tier-${tier.toLowerCase()}`);
    n.querySelector('.action-badge').textContent=oppLabels[oppType(x)]||oppType(x);n.querySelector('.value-score').textContent=value;
    if(isNew(x))n.querySelector('.new-badge').classList.remove('hidden');
    n.querySelector('h3').textContent=x.title||'(タイトル未取得)';n.querySelector('.source').textContent=x.source||'情報元不明';n.querySelector('.creator').textContent=x.creator||labels[x.category]||'作家未抽出';n.querySelector('.location').textContent=x.location||'場所未取得';
    n.querySelector('.deadline-main').textContent=fmtDate(x.apply_end);const cd=n.querySelector('.countdown');cd.textContent=countdown(x);if((deadlineHours(x)??999)<=72)cd.classList.add('hot');
    n.querySelector('.event-date strong').textContent=fmtDate(x.event_start);
    const tagBox=n.querySelector('.item-tags');tagsFor(x).filter(t=>!String(t).startsWith('価値')).slice(0,9).forEach(t=>addTag(tagBox,t,x));
    const why=x.alert_reason||String(x.reasons||'').split(' / ').slice(0,3).join(' / ');n.querySelector('.why-line').textContent=why||'詳細を確認';
    n.querySelector('.reason').textContent=(x.reasons||'判定根拠未取得')+(boost?` / あなたの完了傾向 +${boost}`:'')+(x.source_stale?' / 前回取得情報':'' );

    const primary=n.querySelector('.primary-actions');const target=x.apply_url||x.url;addLink(primary,x.action_label||({'lottery':'応募する','sale':'購入・販売情報','event':'イベント詳細','campaign':'応募する'}[oppType(x)]||'詳細を見る'),target,true);if(x.apply_url&&x.url)addLink(primary,'情報元',x.url,false);
    const manage=n.querySelector('.manage-actions');addManage(manage,x.completed?'完了解除':'応募・購入完了','completed',x.id,x.completed?'done active':'done');addManage(manage,x.favorite?'★ 追跡中':'☆ 追う','favorite',x.id,x.favorite?'active':'');addManage(manage,x.seen?'未読へ':'既読','seen',x.id);addManage(manage,'除外','ignore',x.id);
    list.appendChild(n);
  }
}

function boostWatchlist(items){
  const names=(state.settings.watchlist||'').split(',').map(s=>s.trim()).filter(Boolean);
  return items.map(x=>{let add=0,rs='';for(const name of names){if(`${x.title||''} ${x.creator||''}`.includes(name)){const b=name==='Na-Ga'?25:12;add+=b;rs+=` / ウォッチ:${name} +${b}`}}return add?{...x,value_score:Math.min(140,serverValue(x)+add),reasons:(x.reasons||'')+rs}:x});
}
function mergeFeed(items){
  const old=new Map(state.items.map(x=>[x.id,x]));const incoming=boostWatchlist(items);const ids=new Set(incoming.map(x=>x.id));
  const merged=incoming.map(x=>{const p=old.get(x.id)||{};return{...x,seen:!!p.seen,ignored:!!p.ignored,favorite:!!p.favorite,completed:!!p.completed,completed_at:p.completed_at||null}});
  for(const p of state.items)if(p.completed&&!ids.has(p.id))merged.push({...p,archived:true});state.items=merged;
}
async function loadStaticFeed(){
  const r=await fetch(`./data/items.json?t=${Date.now()}`,{cache:'no-store'});if(!r.ok)throw new Error('収集データ取得失敗');const payload=await r.json();mergeFeed(Array.isArray(payload.items)?payload.items:[]);
  state.feed={generatedAt:payload.generated_at||null,sources:payload.sources||{},schemaVersion:payload.schema_version||null,policy:payload.feed_policy||'',newCount:payload.new_count||0,opportunityCounts:payload.opportunity_counts||{},tierCounts:payload.value_tier_counts||{}};save();render();return visibleBase().length;
}

function bindSelect(id,key){$(id).addEventListener('change',e=>{state.ui[key]=e.target.value;save();render()})}
$('#q').addEventListener('input',e=>{state.ui.q=e.target.value;save();render()});bindSelect('#sourceFilter','source');bindSelect('#tierFilter','tier');bindSelect('#acquisitionFilter','acquisition');bindSelect('#sortMode','sort');
document.addEventListener('click',e=>{
  const lane=e.target.closest('[data-lane]');if(lane){state.ui.lane=lane.dataset.lane;save();render();return}
  const type=e.target.closest('[data-type]');if(type){state.ui.type=type.dataset.type;save();render();return}
  const source=e.target.closest('[data-source]');if(source){state.ui.source=source.dataset.source;save();render();return}
  const tag=e.target.closest('[data-filter-tag]');if(tag){state.ui.tagFilter=tag.dataset.filterTag;save();render();return}
  if(e.target.closest('[data-clear-tag]')){state.ui.tagFilter='';save();render();return}
  const a=e.target.closest('[data-act]');if(!a)return;const x=state.items.find(v=>v.id===a.dataset.id);if(!x)return;
  if(a.dataset.act==='seen')x.seen=!x.seen;if(a.dataset.act==='favorite')x.favorite=!x.favorite;if(a.dataset.act==='ignore')x.ignored=true;
  if(a.dataset.act==='completed'){x.completed=!x.completed;x.completed_at=x.completed?new Date().toISOString():null;if(x.completed)x.seen=true;toast(x.completed?'応募・購入完了として学習しました':'完了を解除しました')}
  save();render();
});
$('#saveSettingsBtn').addEventListener('click',async()=>{state.settings.watchlist=$('#watchlist').value.trim();state.settings.showExpired=$('#showExpired').checked;state.settings.demoMode=$('#demoMode').checked;state.settings.apiBase=$('#apiBase').value.trim();save();if(!state.settings.demoMode){try{await loadStaticFeed()}catch{}}render();toast('設定を保存しました')});
$('#seedBtn').addEventListener('click',()=>{state.items=structuredClone(demo);state.settings.demoMode=true;save();render();toast('デモデータを読み込みました')});
$('#syncBtn').addEventListener('click',async()=>{const b=$('#syncBtn');b.disabled=true;b.textContent='更新中…';try{if(state.settings.demoMode){state.items=structuredClone(demo);save();render();toast('デモ更新')}else{const n=await loadStaticFeed();toast(`${n}件を最新化`)}}catch(err){toast(err.message||'更新失敗')}finally{b.disabled=false;b.textContent='更新'}});
if('serviceWorker'in navigator)window.addEventListener('load',()=>navigator.serviceWorker.register('./sw.js?v=20').catch(()=>{}));
window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();installPrompt=e;$('#installBtn').classList.remove('hidden')});
$('#installBtn').addEventListener('click',async()=>{if(!installPrompt)return;installPrompt.prompt();await installPrompt.userChoice;installPrompt=null;$('#installBtn').classList.add('hidden')});
render();if(!state.settings.demoMode)loadStaticFeed().catch(()=>{});
