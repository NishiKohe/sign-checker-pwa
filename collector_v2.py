from __future__ import annotations
import hashlib,json,os,re,time
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parent; OUT=ROOT/'data'/'items.json'
UA='SignChecker/0.4 (+https://github.com/NishiKohe/sign-checker-pwa)'
S=requests.Session(); S.headers.update({'User-Agent':UA,'Accept-Language':'ja,en;q=0.7'})

LISTS=[
    'https://www.shosen.co.jp/event/',
    'https://www.shosen.co.jp/event/search/type%3A57/',
    'https://www.shosen.co.jp/event/search/type%3A66/',
    'https://www.shosen.co.jp/event/search/type%3A67/',
    'https://www.shosen.co.jp/event/search/type%3A58/',
    'https://www.shosen.co.jp/privilege/',
    'https://www.shosen.co.jp/fair/',
    'https://www.shosen.co.jp/pickup/',
]

SIGN_WORDS=('サイン','直筆','署名')
EVENT_WORDS=('サイン会','webサイン会','リアルサイン会','お渡し会','トーク＆サイン','トーク&サイン','サインイベント')
BOOK_SIGN_WORDS=('サイン本','直筆サイン本','サイン入り','サイン付き','サイン付','著者サイン','直筆サイン入り','署名本')
BOOK_CONTEXT=('本','書籍','コミック','コミックス','単行本','写真集','画集','文庫','新書','新刊','刊行','発売','著書','書籍化','作品集','ムック','雑誌')
ART_WORDS=('原画','色紙','直筆色紙','一点物','一点もの','直筆イラスト','イラストボード','キャンバス')
ACTION_WORDS=('販売','予約','受付','抽選','先着','応募','申込','申し込み','購入','発売','頒布','開催')

def n(s): return re.sub(r'\s+',' ',s or '').strip()
def sid(src,url,title): return hashlib.sha1(f'{src}|{url}|{title}'.encode()).hexdigest()[:16]

def signed_book_context(x:str)->bool:
    low=x.lower()
    if any(k.lower() in low for k in BOOK_SIGN_WORDS): return True
    if not any(k in low for k in SIGN_WORDS): return False
    book='|'.join(map(re.escape,BOOK_CONTEXT)); sign='|'.join(map(re.escape,SIGN_WORDS))
    return bool(re.search(rf'(?:{sign}).{{0,32}}(?:{book})|(?:{book}).{{0,32}}(?:{sign})',low,re.I))

def classify(title:str, scoped:str='')->str:
    t=title.lower(); head=scoped.lower()[:3000]
    if any(k.lower() in t for k in EVENT_WORDS): return 'autograph_event'
    if signed_book_context(t): return 'signed_book'
    if any(k.lower() in t for k in ART_WORDS): return 'original_art'
    if any(k.lower() in head for k in EVENT_WORDS): return 'autograph_event'
    if signed_book_context(head): return 'signed_book'
    if any(k.lower() in head for k in ART_WORDS) and any(k in head for k in SIGN_WORDS+ACTION_WORDS): return 'original_art'
    return 'other'

def relevant(title:str, scoped:str)->bool:
    c=classify(title,scoped)
    if c!='other': return True
    x=(title+' '+scoped[:2500]).lower()
    return any(k in x for k in SIGN_WORDS) and any(k.lower() in x for k in BOOK_CONTEXT+ART_WORDS+ACTION_WORDS)

def method(t):
    x=t.lower()
    if any(k in x for k in ('先着','先着順','なくなり次第','予定数に達し次第','数量限定')):return 'first_come'
    if any(k in x for k in ('抽選受付','抽選販売','抽選','当落','当選','落選')):return 'lottery'
    return 'unknown'

def creator(t):
    for p in [r'([一-龥ぁ-んァ-ヶーA-Za-z0-9・_.\-]{1,30})先生(?:リアル|WEB|web|サイン|直筆|お渡し)',r'([一-龥ぁ-んァ-ヶーA-Za-z0-9・_.\-]{1,30})先生']:
        m=re.search(p,t)
        if m:return n(m.group(1))[-30:]
    return ''

def loc(t):
    for k in ('秋葉原','神保町','池袋','新宿'):
        if k in t:return k
    if any(k in t for k in ('オンラインショップ','WEBサイン会','webサイン会','通販','オンライン販売')):return 'オンライン'
    return ''

def dates(t):
    out=[]
    for p in [r'20\d{2}年\s*\d{1,2}月\s*\d{1,2}日(?:\([^)]*\))?(?:\s*\d{1,2}:\d{2})?',r'20\d{2}/\d{1,2}/\d{1,2}(?:[^0-9]{0,8}\d{1,2}:\d{2})?',r'\d{1,2}月\s*\d{1,2}日(?:\([^)]*\))?(?:\s*\d{1,2}:\d{2})?']:
        for m in re.findall(p,t):
            v=n(m)
            if v not in out:out.append(v)
            if len(out)>=6:return out
    return out

def status(t):
    if any(k in t for k in ('受付終了','販売終了','申込終了','受付は終了','販売は終了')):return 'closed'
    if any(k in t for k in ('受付中','販売中','申込受付','予約受付','受付期間','販売期間')):return 'open'
    return 'unknown'

def score(c,m,title,text,l):
    s=0;r=[]
    def add(v,w):
        nonlocal s;s+=v;r.append(f'{w} +{v}')
    if c=='autograph_event':add(50,'サイン会')
    elif c=='original_art':add(35,'原画・一点物')
    elif c=='signed_book':add(20,'サイン本')
    if m=='first_come':add(25,'先着')
    elif m=='lottery':add(5,'抽選')
    if l in ('秋葉原','神保町','池袋','新宿') or '東京' in title:add(15,'関東')
    low=(title+' '+text[:3000]).lower()
    if any(k in low for k in ('成年コミック','成人向け','18禁','r18','18歳以上')):add(20,'成人向け')
    if any(k in low for k in ('ゲーム原画','原画家','イラストレーター','キャラクターデザイン')):add(15,'ゲーム/イラスト系')
    if 'na-ga' in low or 'na‐ga' in low or 'na–ga' in low:add(40,'Na-Ga')
    return min(s,140),' / '.join(r)

def get(u):
    r=S.get(u,timeout=20);r.raise_for_status();return r.text

def scoped_text(soup:BeautifulSoup)->str:
    root=soup.find('main') or soup.find('article') or soup.find(attrs={'role':'main'}) or soup
    clone=BeautifulSoup(str(root),'html.parser')
    for bad in clone.find_all(['nav','footer','aside','script','style']): bad.decompose()
    return n(clone.get_text(' ',strip=True))

def shosen():
    links={}
    detail_re=re.compile(r'/(?:event|privilege|fair|pickup)/\d+/?(?:\?.*)?$')
    for lu in LISTS:
        try:soup=BeautifulSoup(get(lu),'html.parser')
        except Exception as e: print('[shosen:list]',lu,e);continue
        for a in soup.find_all('a',href=True):
            href=a.get('href','')
            if not detail_re.search(href):continue
            title=n(a.get_text(' ',strip=True))
            if not title:
                img=a.find('img');title=n(img.get('alt','') if img else '')
            links[urljoin(lu,href)]=title
    print('discovered detail links',len(links))
    items=[]
    for i,(url,lt) in enumerate(list(links.items())[:220]):
        if i:time.sleep(.10)
        try:
            soup=BeautifulSoup(get(url),'html.parser');h=soup.find('h1');title=n(h.get_text(' ',strip=True) if h else lt);text=scoped_text(soup)
        except Exception as e: print('[shosen:detail]',url,e);continue
        if not relevant(title,text):continue
        c=classify(title,text);m=method(text);l=loc(title+' '+text[:3000]);sc,rs=score(c,m,title,text,l)
        items.append({'id':sid('書泉',url,title),'title':title,'source':'書泉','creator':creator(title),'location':l,'category':c,'method':m,'score':sc,'reasons':rs,'url':url,'status':status(text[:5000]),'dates':dates(text[:5000])})
    return items

def xitems():
    token=os.getenv('X_BEARER_TOKEN','').strip()
    if not token:return []
    q='((サイン OR 直筆 OR 署名) (本 OR 書籍 OR コミック OR 漫画 OR 写真集 OR 画集 OR 新刊 OR 販売 OR 受付 OR 抽選 OR 先着)) OR サイン会 OR WEBサイン会 OR 原画販売 OR 直筆色紙 -is:retweet lang:ja'
    try:
        r=requests.get('https://api.x.com/2/tweets/search/recent',params={'query':q,'max_results':100,'tweet.fields':'created_at'},headers={'Authorization':f'Bearer {token}','User-Agent':UA},timeout=20);r.raise_for_status();data=r.json().get('data',[])
    except Exception as e:print('[x]',e);return []
    out=[]
    for t in data:
        text=n(t.get('text',''))
        if not relevant(text,text):continue
        c=classify(text,text);m=method(text);l=loc(text);sc,rs=score(c,m,text,text,l);url=f"https://x.com/i/web/status/{t.get('id','')}"
        out.append({'id':sid('X',url,text[:100]),'title':text[:140],'source':'X','creator':'','location':l,'category':c,'method':m,'score':sc,'reasons':rs,'url':url,'status':'unknown','dates':dates(text),'published_at':t.get('created_at')})
    return out

def main():
    now=datetime.now(timezone.utc).isoformat();merged={}
    for x in shosen()+xitems():
        k=x.get('url') or x['id']
        if k not in merged or x['score']>merged[k]['score']:merged[k]=x
    items=sorted(merged.values(),key=lambda x:(-x['score'],x['title']))
    for x in items:x['fetched_at']=now
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({'generated_at':now,'count':len(items),'sources':{'shosen':True,'x':bool(os.getenv('X_BEARER_TOKEN','').strip())},'items':items},ensure_ascii=False,indent=2),encoding='utf-8')
    print('wrote',len(items),'items')
if __name__=='__main__':main()
