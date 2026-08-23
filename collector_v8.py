from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import collector_v7 as prior

base = prior.base
core = prior.core
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "items.json"

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Linux; Android 16; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5",
})

SIGNALS = (
    "サイン会", "webサイン会", "オンラインサイン会", "ネットサイン会", "お渡し会",
    "サイン本", "直筆サイン", "直筆色紙", "サイン色紙", "署名本",
    "原画", "生原画", "直筆イラスト", "一点物", "一点もの", "在廊",
)
EXHIBITION_WORDS = (
    "個展", "原画展", "展示会", "作品展", "artworks展", "artworks 展", "exhibition",
    "pop up", "popup", "pop-up", "ポップアップ", "ポップアップストア",
)
EXHIBITION_VALUE = (
    "サイン", "直筆", "原画販売", "原画", "一点物", "一点もの", "在廊", "描き下ろし",
    "サイン本", "展示販売", "販売予定", "先着", "抽選",
)
LOW_VALUE_POPUP = (
    "グッズ販売のみ", "物販のみ", "購入特典", "ノベルティ", "等身大パネル",
)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def get(url: str) -> str:
    r = S.get(url, timeout=25)
    r.raise_for_status()
    return r.text


def clean_body(soup: BeautifulSoup) -> str:
    root = soup.find("article") or soup.find("main") or soup.find(attrs={"role": "main"}) or soup
    clone = BeautifulSoup(str(root), "html.parser")
    for bad in clone.find_all(["nav", "footer", "aside", "script", "style", "form"]):
        bad.decompose()
    return norm(clone.get_text(" ", strip=True))


def has_signal(text: str) -> bool:
    x = (text or "").lower()
    return any(k.lower() in x for k in SIGNALS)


def is_exhibition(text: str) -> bool:
    x = (text or "").lower()
    return any(k.lower() in x for k in EXHIBITION_WORDS)


def exhibition_score(title: str, body: str, location: str) -> tuple[int, str]:
    x = (title + " " + body[:4000]).lower()
    score = 12
    reasons = ["個展/POP UP +12"]

    if "サイン会" in x or "webサイン会" in x or "お渡し会" in x:
        score += 45; reasons.append("サイン会併催 +45")
    if "在廊" in x:
        score += 18; reasons.append("在廊 +18")
    if any(k in x for k in ("一点物", "一点もの", "生原画")):
        score += 30; reasons.append("一点物/生原画 +30")
    elif "原画" in x:
        score += 20; reasons.append("原画 +20")
    if "直筆" in x:
        score += 20; reasons.append("直筆 +20")
    if "サイン本" in x or "署名本" in x:
        score += 20; reasons.append("サイン本 +20")
    if any(k in x for k in ("先着", "数量限定", "なくなり次第")):
        score += 12; reasons.append("先着/限定 +12")
    if location in ("秋葉原", "池袋", "新宿", "神保町", "東京"):
        score += 10; reasons.append("東京 +10")
    if any(k in x for k in ("成人向け", "成年コミック", "18禁", "r18")):
        score += 15; reasons.append("成人向け +15")
    if any(k in x for k in ("ゲーム原画", "原画家", "イラストレーター", "キャラクターデザイン")):
        score += 15; reasons.append("ゲーム/イラスト系 +15")
    if any(k in x for k in ("na-ga", "na‐ga", "na–ga")):
        score += 40; reasons.append("Na-Ga +40")
    if any(k in x for k in LOW_VALUE_POPUP) and not any(k in x for k in ("サイン", "直筆", "原画", "一点物", "在廊")):
        score = min(score, 15)
        reasons.append("通常物販のみ")
    return min(score, 140), " / ".join(reasons)


def make_item(source: str, url: str, title: str, body: str, forced_location: str = "") -> dict | None:
    title = norm(title); body = norm(body)
    head = title + " " + body[:3500]
    exhibition = is_exhibition(head)
    signal = has_signal(head)
    if not signal and not exhibition:
        return None

    location = forced_location or base.location_generic(head)
    if exhibition and not any(k.lower() in head.lower() for k in EXHIBITION_VALUE):
        # Keep ordinary exhibitions for visibility, but very low priority.
        category = "exhibition"
        method = "unknown"
        score, reasons = exhibition_score(title, body, location)
    elif exhibition:
        category = "exhibition"
        method = base.method_better(head)
        score, reasons = exhibition_score(title, body, location)
    else:
        category = base.classify_source(title, body)
        method = base.method_better(head)
        score, reasons = core.score_item(category, method, title, body, location)

    item = {
        "id": core.stable_id(source, url, title),
        "title": title,
        "source": source,
        "creator": base.creator_generic(title, ""),
        "location": location,
        "category": category,
        "method": method,
        "score": score,
        "reasons": reasons,
        "url": url,
        "status": core.status_of(body[:6000]),
        "dates": core.extract_dates(title + " " + body[:6000]),
    }
    item.update(prior.prior.extract_timeline(title, body) if hasattr(prior, "prior") else prior.extract_timeline(title, body))
    return item


# ---------- Animate ----------
ANIMATE_LISTS = [
    "https://www.animate-onlineshop.jp/contents/fair_event/?lmode=event&mode=search",
    "https://www.animate-onlineshop.jp/contents/fair_event/?lmode=fair&mode=search",
]
ANIMATE_DETAIL = re.compile(r"/contents/fair_event/detail\.php$")


def collect_animate() -> tuple[list[dict], bool]:
    links: dict[str, str] = {}
    ok = False
    for base_url in ANIMATE_LISTS:
        for page in range(1, 5):
            url = base_url + f"&pageno={page}"
            try:
                soup = BeautifulSoup(get(url), "html.parser"); ok = True
            except Exception as e:
                print("[animate:list]", url, e); continue
            for a in soup.find_all("a", href=True):
                href = urljoin(url, a.get("href", "")); p = urlparse(href)
                if p.netloc not in ("www.animate-onlineshop.jp", "animate-onlineshop.jp") or not ANIMATE_DETAIL.search(p.path) or "id=" not in p.query:
                    continue
                title = norm(a.get_text(" ", strip=True))
                if not title:
                    img = a.find("img"); title = norm(img.get("alt", "") if img else "")
                links[href] = title
    out = []
    for i, (url, lt) in enumerate(list(links.items())[:220]):
        if i: time.sleep(.05)
        try:
            soup = BeautifulSoup(get(url), "html.parser")
        except Exception as e:
            print("[animate:detail]", url, e); continue
        h1 = soup.find("h1"); title = norm(h1.get_text(" ", strip=True) if h1 else lt); body = clean_body(soup)
        # Anime/voice-actor release events without any signing are noise here.
        if not has_signal(title + " " + body[:2800]) and not is_exhibition(title + " " + body[:2800]):
            continue
        item = make_item("アニメイト", url, title, body)
        if item: out.append(item)
    print("animate matched", len(out))
    return out, ok


# ---------- Gamers ----------
GAMERS_LISTS = [
    "https://www.gamers.co.jp/contents/event_fair/list.php?category=1",
    "https://www.gamers.co.jp/contents/event_fair/list.php?category=0",
]
GAMERS_DETAIL = re.compile(r"/contents/event_fair/detail\.php$")


def collect_gamers() -> tuple[list[dict], bool]:
    links: dict[str, str] = {}; ok = False
    for base_url in GAMERS_LISTS:
        for page in range(1, 6):
            sep = "&" if "?" in base_url else "?"; url = base_url + f"{sep}pageno={page}"
            try:
                soup = BeautifulSoup(get(url), "html.parser"); ok = True
            except Exception as e:
                print("[gamers:list]", url, e); continue
            for a in soup.find_all("a", href=True):
                href = urljoin(url, a.get("href", "")); p = urlparse(href)
                if p.netloc not in ("www.gamers.co.jp", "gamers.co.jp") or not GAMERS_DETAIL.search(p.path) or "id=" not in p.query:
                    continue
                title = norm(a.get_text(" ", strip=True))
                if not title:
                    img = a.find("img"); title = norm(img.get("alt", "") if img else "")
                links[href] = title
    out = []
    for i, (url, lt) in enumerate(list(links.items())[:250]):
        if i: time.sleep(.05)
        try: soup = BeautifulSoup(get(url), "html.parser")
        except Exception as e: print("[gamers:detail]", url, e); continue
        h1=soup.find("h1"); title=norm(h1.get_text(" ",strip=True) if h1 else lt); body=clean_body(soup)
        if not has_signal(title+" "+body[:3000]) and not is_exhibition(title+" "+body[:3000]): continue
        item=make_item("ゲーマーズ",url,title,body)
        if item: out.append(item)
    print("gamers matched",len(out)); return out,ok


# ---------- Toranoana ----------
TORA_LISTS = [
    "https://news.toranoana.jp/notifications",
    "https://news.toranoana.jp/?s=%E3%82%B5%E3%82%A4%E3%83%B3",
    "https://news.toranoana.jp/?s=%E7%9B%B4%E7%AD%86",
    "https://news.toranoana.jp/?s=%E5%8E%9F%E7%94%BB",
    "https://news.toranoana.jp/?s=%E3%83%9D%E3%83%83%E3%83%97%E3%82%A2%E3%83%83%E3%83%97",
]
TORA_DETAIL = re.compile(r"^/notification/\d+/?$")


def collect_toranoana() -> tuple[list[dict], bool]:
    links: dict[str,str]={}; ok=False
    for url in TORA_LISTS:
        try: soup=BeautifulSoup(get(url),"html.parser");ok=True
        except Exception as e: print("[tora:list]",url,e);continue
        for a in soup.find_all("a",href=True):
            href=urljoin(url,a.get("href",""));p=urlparse(href)
            if p.netloc!="news.toranoana.jp" or not TORA_DETAIL.match(p.path):continue
            title=norm(a.get_text(" ",strip=True));links[href]=title
    out=[]
    for i,(url,lt) in enumerate(list(links.items())[:180]):
        if i:time.sleep(.05)
        try:soup=BeautifulSoup(get(url),"html.parser")
        except Exception as e:print("[tora:detail]",url,e);continue
        h1=soup.find("h1");title=norm(h1.get_text(" ",strip=True) if h1 else lt);body=clean_body(soup)
        if not has_signal(title+" "+body[:3000]) and not is_exhibition(title+" "+body[:3000]):continue
        item=make_item("とらのあな",url,title,body)
        if item:out.append(item)
    print("toranoana matched",len(out));return out,ok


# ---------- space caiman / Déesse ----------
CAIMAN_LISTS = [
    ("space caiman", "https://space-caiman.com/schedule", re.compile(r"^/schedule/[^/]+/?$")),
    ("Déesse space caiman", "https://dscaiman.com/", re.compile(r"^/exhibition/[^/]+/?$")),
]


def collect_caiman() -> tuple[list[dict], bool]:
    links: dict[str,tuple[str,str]]={};ok=False
    for source,url,pat in CAIMAN_LISTS:
        try:soup=BeautifulSoup(get(url),"html.parser");ok=True
        except Exception as e:print("[caiman:list]",url,e);continue
        for a in soup.find_all("a",href=True):
            href=urljoin(url,a.get("href",""));p=urlparse(href)
            if p.netloc not in ("space-caiman.com","www.space-caiman.com","dscaiman.com","www.dscaiman.com") or not pat.match(p.path):continue
            title=norm(a.get_text(" ",strip=True));links[href]=(source,title)
    out=[]
    for i,(url,(source,lt)) in enumerate(list(links.items())[:120]):
        if i:time.sleep(.05)
        try:soup=BeautifulSoup(get(url),"html.parser")
        except Exception as e:print("[caiman:detail]",url,e);continue
        h1=soup.find("h1");title=norm(h1.get_text(" ",strip=True) if h1 else lt);body=clean_body(soup)
        # Caiman is high-signal for this project; retain exhibitions even before sign details are announced.
        item=make_item(source,url,title,body,"東京")
        if item:out.append(item)
    print("caiman matched",len(out));return out,ok


# ---------- Extended X ----------
def collect_x_extended() -> tuple[list[dict], bool]:
    token=os.getenv("X_BEARER_TOKEN","").strip()
    if not token:return [],False
    queries=[
        '((サイン OR 直筆 OR 署名) (本 OR 書籍 OR コミック OR 漫画 OR 写真集 OR 画集 OR 新刊 OR 販売 OR 受付 OR 抽選 OR 先着)) OR サイン会 OR WEBサイン会 OR 原画販売 OR 直筆色紙 -is:retweet lang:ja',
        '((個展 OR 原画展 OR 展示会 OR "POP UP" OR ポップアップ) (サイン OR 直筆 OR 原画 OR 一点物 OR 在廊 OR サイン本 OR 販売)) -is:retweet lang:ja',
    ]
    out=[]
    for q in queries:
        try:
            r=requests.get("https://api.x.com/2/tweets/search/recent",params={"query":q,"max_results":100,"tweet.fields":"created_at"},headers={"Authorization":f"Bearer {token}","User-Agent":S.headers["User-Agent"]},timeout=25);r.raise_for_status();data=r.json().get("data",[])
        except Exception as e:print("[x-extended]",e);continue
        for t in data:
            text=norm(t.get("text","")); url=f"https://x.com/i/web/status/{t.get('id','')}"
            item=make_item("X",url,text[:180],text)
            if item:
                item["published_at"]=t.get("created_at");out.append(item)
    # dedupe tweet ids
    ded={x["url"]:x for x in out};return list(ded.values()),True


def main() -> None:
    now=datetime.now(timezone.utc).isoformat()
    shosen=core.collect_shosen()
    ogaki,ogaki_ok=prior.prior.collect_ogaki_strict()
    melon,melon_ok=base.collect_melon()
    prtimes,prtimes_ok=prior.collect_prtimes()
    animate,animate_ok=collect_animate()
    gamers,gamers_ok=collect_gamers()
    tora,tora_ok=collect_toranoana()
    caiman,caiman_ok=collect_caiman()
    xitems,x_ok=collect_x_extended()

    all_items=shosen+ogaki+melon+prtimes+animate+gamers+tora+caiman+xitems
    prior.prior.add_timeline_to_existing(all_items)
    live_discovered,live_fetched=prior.prior.enrich_livepocket(all_items)

    merged={}
    for item in all_items:
        key=item.get("url") or item.get("id")
        prev=merged.get(key)
        if prev is None or int(item.get("score",0))>int(prev.get("score",0)):merged[key]=item
    items=sorted(merged.values(),key=lambda x:(-int(x.get("score",0)),x.get("title","")))
    for item in items:item["fetched_at"]=now

    counts={};categories={}
    for item in items:
        counts[item["source"]]=counts.get(item["source"],0)+1
        categories[item["category"]]=categories.get(item["category"],0)+1

    payload={
        "generated_at":now,"count":len(items),
        "sources":{
            "shosen":{"enabled":True,"count":counts.get("書泉",0)},
            "ogaki":{"enabled":ogaki_ok,"count":counts.get("大垣書店",0)},
            "melonbooks":{"enabled":melon_ok,"count":counts.get("メロンブックス",0)},
            "prtimes":{"enabled":prtimes_ok,"count":counts.get("PR TIMES",0)},
            "animate":{"enabled":animate_ok,"count":counts.get("アニメイト",0)},
            "gamers":{"enabled":gamers_ok,"count":counts.get("ゲーマーズ",0)},
            "toranoana":{"enabled":tora_ok,"count":counts.get("とらのあな",0)},
            "caiman":{"enabled":caiman_ok,"count":counts.get("space caiman",0)+counts.get("Déesse space caiman",0)},
            "livepocket":{"enabled":live_discovered>0,"discovered":live_discovered,"fetched":live_fetched},
            "x":{"enabled":x_ok,"count":counts.get("X",0)},
        },
        "category_counts":categories,
        "sort_fields":["score","event_start","apply_start","apply_end"],
        "items":items,
    }
    OUT.write_text(__import__("json").dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print("wrote",len(items),counts,categories)


if __name__=="__main__":main()
