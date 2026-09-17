const CACHE='sign-checker-pwa-v23';
const ASSETS=['./','./index.html','./styles.css?v=20','./feed-guard.js?v=23','./app.js?v=20','./feed-state.js?v=23','./auction-ui.js?v=22','./manual-refresh.js?v=23','./manifest.webmanifest','./icon.svg'];
self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)));self.skipWaiting()});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('sign-checker-pwa-')&&k!==CACHE).map(k=>caches.delete(k)))));self.clients.claim()});
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET')return;
  const u=new URL(e.request.url);
  if(u.origin!==self.location.origin)return;
  e.respondWith(fetch(e.request,{cache:'no-store'}).then(r=>{
    if(r.ok){const copy=r.clone();caches.open(CACHE).then(c=>c.put(e.request,copy)).catch(()=>{});}
    return r;
  }).catch(async()=>{
    const hit=await caches.match(e.request);
    if(hit)return hit;
    if(e.request.mode==='navigate')return caches.match('./index.html');
    throw new Error('offline');
  }));
});
