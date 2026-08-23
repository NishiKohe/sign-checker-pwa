from __future__ import annotations
import hashlib,json,os,re,time
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parent; OUT=ROOT/'data'/'items.json'
UA='SignChecker/0.3 (+https://github.com/NishiKohe/sign-checker-pwa)'
S=requests.Session(); S.headers.update({'User-Agent':UA,'Accept-Language':'ja,en;q=0.7'})

# 「サイン会」カテゴリだけではサイン本販売を落とすため、販売会・お渡し会・特典・フェアも巡回。
LISTS=[
    'https://www.shosen.co.jp/event/search/type%3A57/',  # サイン会
    'https://www.shosen.co.jp/event/search/type%3A66/',  # WEBサイン会
    'https://www.shosen.co.jp/event/search/type%3A67/',  # 販売会（サイン本販売が出る）
    'https://www.shosen.co.jp/event/search/type%3A58/',  # お渡し会
    'https://www.shosen.co.jp/event/',                    # 全イベント
    'https://www.shosen.co.jp/privilege/',                # 特典
    'https://www.shosen.co.jp/fair/',                     # フェア
]

SIGN_WORDS=('サイン','直筆','署名')
EVENT_WORDS=('サイン会','webサイン会','リアルサイン会','お渡し会','トーク＆サイン','トーク&サイン','サインイベント')
BOOK_SIGN_WORDS=('サイン本','直筆サイン本','サイン入り','サイン付き','サイン付','著者サイン','直筆サイン入り','署名本')
BOOK_CONTEXT=('本','書籍','コミック','コミックス','単行本','写真集','画集','文庫','新刊','刊行','発売','著書','書籍化')
ART_WORDS=('原画','色紙','直筆色紙','一点物','直筆イラスト','イラストボード','キャンバス')
ACTION_WORDS=('販売','予約','受付','抽選','先着','応募','申込','申し込み','購入','発売','頒布','開催')
CREATOR_WORDS=('先生','著者','漫画家','イラストレーター','原画家','作家','クリエイター')
STRONG_WORDS=EVENT_WORDS+BOOK_SIGN_WORDS+ART_WORDS


def n(s): return re.sub(r'\s+',' ',s or '').strip()
def sid(src,url,title): return hashlib.sha1(f'{src}|{url}|{title}'.encode()).hexdigest()[:16]

def has_sign_context(t):
    x=t.lower()
    if not any(k in x for k in SIGN_WORDS): return False
    context=BOOK_CONTEXT+ART_WORDS+ACTION_WORDS+CREATOR_WORDS+('イベント','オンライン','限定','特典')
    return any(k.lower() in x for k in context)

def signed_book_context(t):
    x=t.lower()
    if any(k.lower() in x for k in BOOK_SIGN_WORDS): return True
    if not any(k in x for k in SIGN_WORDS): return False
    book='|'.join(map(re.escape,BOOK_CONTEXT)); sign='|'.join(map(re.escape,SIGN_WORDS))
    return bool(re.search(rf'(?:{sign}).{{0,28}}(?:{book})|(?:{book}).{{0,28}}(?:{sign})',x,re.I))

def cat(t):
    x=t.lower()
    if any(k.lower() in x for k in EVENT_WORDS): return 'autograph_event'
    if any(k.lower() in x for k in ART_WORDS) and any(k in x for k in SIGN_WORDS+('直筆',)): return 'original_art'
    if signed_book_context(x): return 'signed_book'
    if any(k.lower() in x for k in ART_WORDS): return 'original_art'
    if has_sign_context(x): return 'other'
    return 'other'

def relevant(t):
    x=t.lower()
    if any(k.lower() in x for k in STRONG_WORDS): return True
    return has_sign_context(x)

def method(t):
    x=t.lower()
    if any(k in x for k in ('先着','先着順','なくなり次第','予定数に達し次第')):return 'first_come'
    if any(k in x for k in ('抽選','当落','当選','落選')):return 'lottery'
    return 'unknown'
def creator(t):
    for p in [r'([一-龥ぁ-んァ-ヶーA-Za-z0-9・_.\-]{1,30})先生(?:リアル|WEB|web|サイン|直筆|お渡し)',r'([一-龥ぁ-んァ-ヶーA-Za-z0-9・_.\-]{1,30})先生']:
        m=re.search(p,t)
        if m:return n(m.group(1))[-30:]
    return ''
def loc(t):
    for k in ('秋葉原','神保町','池袋','新宿'):
        if k in t:return k
    if any(k in t for k in ('オンラインショップ','WEBサイン会','webサイン会','通販')):return 'オンライン'
    return ''
def dates(t):
    out=[]
    for p in [r'20\d{2}年\s*\d{1,2}月\s*\d{1,2}日(?:\([^)]*\))?(?:\s*\d{1,2}:\d{2})?',r'\d{1,2}月\s*\d{1,2}日(?:\([^)]*\))?(?:\s*\d{1,2}:\d{2})?']:
        for m in re.findall(p,t):
            v=n(m)
            if v not in out:out.append(v)
            if len(out)>=6:return out
    return out
def status(t):
    if any(k in t for k in ('受付終了','販売終了','申込終了','終了しました')):return 'closed'
    if any(k in t for k in ('受付中','販売中','申込受付','お申込み','予約受付')):return 'open'
    return 'unknown'
def score(c,m,title,text,l):
    s=0;r=[]
    def add(v,w):
        nonlocal s;s+=v;r.append(f'{w} +{v}')
    if c=='autograph_event':add(50,'サイン会')
    elif c=='original_art':add(35,'原画・一点物')
    elif c=='signed_book':add(20,'サイン本')
    elif has_sign_context(title):add(8,'サイン関連')
    if m=='first_come':add(25,'先着')
    elif m=='lottery':add(5,'抽選')
    if l in ('秋葉原','神保町','池袋','新宿') or '東京' in text:add(15,'関東')
    low=(title+' '+text).lower()
    if any(k in low for k in ('成年','成人向け','18禁','r18')):add(20,'成人向け')
    if 'na-ga' in low:add(40,'Na-Ga')
    return min(s,140),' / '.join(r)
def get(u):
    r=S.get(u,timeout=20);r.raise_for_status();return r.text

def shosen():
    links={}
    detail_re=re.compile(r'/(?:event|privilege|fair)/\d+/?(?:\?.*)?$')
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
    for i,(url,lt) in enumerate(list(links.items())[:140]):
        if i:time.sleep(.12)
        try:
            soup=BeautifulSoup(get(url),'html.parser');h=soup.find('h1');title=n(h.get_text(' ',strip=True) if h else lt);text=n(soup.get_text(' ',strip=True))
        except Exception as e: print('[shosen:detail]',url,e);continue
        joined=title+' '+text
        if not relevant(joined):continue
        c=cat(joined);m=method(text);l=loc(text);sc,rs=score(c,m,title,text,l)
        items.append({'id':sid('書泉',url,title),'title':title,'source':'書泉','creator':creator(title),'location':l,'category':c,'method':m,'score':sc,'reasons':rs,'url':url,'status':status(text),'dates':dates(text)})
    return items

def xitems():
    token=os.getenv('X_BEARER_TOKEN','').strip()
    if not token:return []
    q='(サイン OR 直筆 OR 署名 OR "サイン本" OR "サイン入り" OR "直筆色紙" OR "原画販売") -is:retweet lang:ja'
    try:
        r=requests.get('https://api.x.com/2/tweets/search/recent',params={'query':q,'max_results':100,'tweet.fields':'created_at'},headers={'Authorization':f'Bearer {token}','User-Agent':UA},timeout=20);r.raise_for_status();data=r.json().get('data',[])
    except Exception as e:print('[x]',e);return []
    out=[]
    for t in data:
        text=n(t.get('text',''))
        if not relevant(text):continue
        c=cat(text);m=method(text);l=loc(text);sc,rs=score(c,m,text,text,l);url=f"https://x.com/i/web/status/{t.get('id','')}"
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
