const STORAGE='sign-checker-pwa-v2';
const labels={autograph_event:'サイン会',original_art:'原画・一点物',signed_book:'サイン本',other:'その他'};
const methods={first_come:'先着',lottery:'抽選',unknown:'方式不明'};
const $=s=>document.querySelector(s);
let installPrompt=null;
const demo=[
{id:'1',title:'Na-Ga 直筆サイン会 先着受付',source:'X',creator:'Na-Ga',location:'秋葉原',category:'autograph_event',method:'first_come',score:122,reasons:'サイン会 +50 / 先着 +25 / 関東 +15 / Na-Ga +40',url:'https://example.com',seen:false,ignored:false,favorite:true},
{id:'2',title:'村田蓮爾 複製原画 予約開始',source:'BOOTH',creator:'村田蓮爾',location:'通販',category:'original_art',method:'first_come',score:94,reasons:'原画・一点物 +35 / 先着 +25 / 注目作家 +15',url:'https://example.com',seen:false,ignored:false,favorite:true},
{id:'3',title:'あるぷ先生 サイン本 抽選販売',source:'書泉',creator:'あるぷ',location:'神保町',category:'signed_book',method:'lottery',score:72,reasons:'サイン本 +20 / 関東 +15 / 注目作家 +15',url:'https://example.com',seen:false,ignored:false,favorite:false}
];
function defaults(){return{items:structuredClone(demo),settings:{apiBase:'',watchlist:'Na-Ga, 村田蓮爾, あるぷ',demoMode:true},ui:{tab:'all',q:'',score:'0'}}}
function load(){try{return{...defaults(),...JSON.parse(localStorage.getItem(STORAGE)||'{}')}}catch{return defaults()}}
let state=load();
function save(){localStorage.setItem(STORAGE,JSON.stringify(state))}
function toast(t){const e=document.createElement('div');e.className='toast';e.textContent=t;document.body.appendChild(e);setTimeout(()=>e.remove(),1800)}
function filtered(){const q=($('#q').value||'').toLowerCase().trim(),min=Number($('#scoreFilter').value||0),tab=state.ui.tab;return state.items.filter(x=>!x.ignored&&x.score>=min).filter(x=>tab==='all'||(tab==='urgent'&&x.score>=85)||(tab==='favorites'&&x.favorite)||x.category===tab).filter(x=>!q||[x.title,x.creator,x.location,x.source,x.reasons].join(' ').toLowerCase().includes(q)).sort((a,b)=>b.score-a.score)}
function render(){
$('#q').value=state.ui.q||'';$('#scoreFilter').value=state.ui.score||'0';$('#apiBase').value=state.settings.apiBase||'';$('#watchlist').value=state.settings.watchlist||'';$('#demoMode').checked=!!state.settings.demoMode;
document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===state.ui.tab));
const all=state.items.filter(x=>!x.ignored);$('#statUnseen').textContent=all.filter(x=>!x.seen).length;$('#statUrgent').textContent=all.filter(x=>x.score>=85).length;$('#statTotal').textContent=all.length;
const list=$('#list');list.innerHTML='';const items=filtered();if(!items.length){list.innerHTML='<div class="card empty">該当案件なし</div>';return}
for(const x of items){const n=$('#itemTpl').content.firstElementChild.cloneNode(true);n.classList.toggle('urgent',x.score>=85);n.classList.toggle('seen',x.seen);n.querySelector('h3').textContent=x.title;n.querySelector('.meta').textContent=`${x.source} · ${x.creator||'作家未抽出'} · ${x.location||'場所未抽出'}`;n.querySelector('.score').textContent=x.score;n.querySelector('.reason').textContent=x.reasons||'';n.querySelector('.badges').innerHTML=[labels[x.category]||x.category,methods[x.method]||x.method,x.favorite?'お気に入り':'',x.seen?'既読':''].filter(Boolean).map(v=>`<span class="badge">${v}</span>`).join('');n.querySelector('.item-actions').innerHTML=`<a href="${x.url||'#'}" target="_blank" rel="noopener">元ページ</a><button class="secondary" data-act="seen" data-id="${x.id}">${x.seen?'未読へ':'既読'}</button><button class="secondary" data-act="favorite" data-id="${x.id}">${x.favorite?'★解除':'★'}</button><button class="secondary" data-act="ignore" data-id="${x.id}">除外</button>`;list.appendChild(n)}
}
function boost(items){const names=(state.settings.watchlist||'').split(',').map(s=>s.trim()).filter(Boolean);return items.map(x=>{let add=0,rs='';for(const n of names){if(`${x.title} ${x.creator}`.includes(n)){const b=n==='Na-Ga'?40:15;add+=b;rs+=` / ウォッチ:${n} +${b}`}}return add?{...x,score:Math.min(140,Number(x.score||0)+add),reasons:(x.reasons||'')+rs}:x})}
async function apiItems(){const base=(state.settings.apiBase||'').replace(/\/$/,'');if(!base)throw new Error('APIベースURL未設定');const r=await fetch(`${base}/api/items`);if(!r.ok)throw new Error('API接続失敗');const a=await r.json();return boost(a.map((x,i)=>({...x,id:String(x.id??x.url??i),score:Number(x.score||0),seen:!!x.seen,ignored:!!x.ignored,favorite:!!x.favorite})))}
function upsert(items){const m=new Map(state.items.map(x=>[x.id,x]));items.forEach(x=>m.set(x.id,{...(m.get(x.id)||{}),...x}));state.items=[...m.values()]}
document.addEventListener('click',async e=>{const tab=e.target.closest('[data-tab]');if(tab){state.ui.tab=tab.dataset.tab;save();render();return}const a=e.target.closest('[data-act]');if(a){const x=state.items.find(v=>v.id===a.dataset.id);if(!x)return;if(a.dataset.act==='seen')x.seen=!x.seen;if(a.dataset.act==='favorite')x.favorite=!x.favorite;if(a.dataset.act==='ignore')x.ignored=true;save();render()}});
$('#q').addEventListener('input',e=>{state.ui.q=e.target.value;save();render()});$('#scoreFilter').addEventListener('change',e=>{state.ui.score=e.target.value;save();render()});
$('#saveSettingsBtn').addEventListener('click',()=>{state.settings.apiBase=$('#apiBase').value.trim();state.settings.watchlist=$('#watchlist').value.trim();state.settings.demoMode=$('#demoMode').checked;save();toast('保存しました')});
$('#seedBtn').addEventListener('click',()=>{state.items=structuredClone(demo);save();render();toast('デモ初期化')});
$('#syncBtn').addEventListener('click',async()=>{const b=$('#syncBtn');b.disabled=true;b.textContent='同期中…';try{if(state.settings.demoMode){upsert(boost([{id:`d-${Date.now()}`,title:'新着デモ: サイン会情報を検知',source:'デモ巡回',creator:'注目作家',location:'池袋',category:'autograph_event',method:'first_come',score:97,reasons:'サイン会 +50 / 先着 +25 / 関東 +15',url:'https://example.com',seen:false,ignored:false,favorite:false}]))}else{const base=(state.settings.apiBase||'').replace(/\/$/,'');await fetch(`${base}/api/collect`,{method:'POST'});upsert(await apiItems())}save();render();toast('同期しました')}catch(err){toast(err.message||'同期失敗')}finally{b.disabled=false;b.textContent='同期'}});
if('serviceWorker'in navigator)window.addEventListener('load',()=>navigator.serviceWorker.register('./sw.js').catch(()=>{}));
window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();installPrompt=e;$('#installBtn').classList.remove('hidden')});$('#installBtn').addEventListener('click',async()=>{if(!installPrompt)return toast('Chromeメニューの「ホーム画面に追加」も利用できます');installPrompt.prompt();await installPrompt.userChoice;installPrompt=null;$('#installBtn').classList.add('hidden')});
render();