from __future__ import annotations
import hashlib, json, re, unicodedata
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

DATE=r"(?:(?P<{p}y>20\d{{2}})\s*[年./-]\s*)?(?P<{p}m>\d{{1,2}})\s*[月./-]\s*(?P<{p}d>\d{{1,2}})\s*日?"
RANGE=re.compile(DATE.format(p="a")+r"\s*(?:\([^)]*\))?\s*[～〜~–—－-]\s*"+DATE.format(p="b"))
EXCLUDED=re.compile(r"コレクション|常設展|名品ギャラリー|講演会|ワークショップ|公募展")

class Node:
    def __init__(self,tag="",attrs=None,parent=None): self.tag,self.attrs,self.parent,self.children=tag,dict(attrs or []),parent,[]
    def text(self): return " ".join(c if isinstance(c,str) else c.text() for c in self.children if isinstance(c,str) or c.tag not in ("script","style","nav","header","footer"))
    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child,Node): yield from child.walk()

class Tree(HTMLParser):
    VOID={"area","base","br","col","embed","hr","img","input","link","meta","param","source","track","wbr"}
    def __init__(self,html): super().__init__(convert_charrefs=True); self.root=self.current=Node("root"); self.feed(html)
    def handle_starttag(self,tag,attrs):
        node=Node(tag,attrs,self.current); self.current.children.append(node)
        if tag not in self.VOID: self.current=node
    def handle_endtag(self,tag):
        node=self.current
        while node.parent:
            if node.tag==tag: self.current=node.parent; return
            node=node.parent
    def handle_data(self,text): self.current.children.append(text)

class SameHostRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        new=urljoin(req.full_url,newurl)
        if urlsplit(new).scheme!="https" or urlsplit(new).netloc!=urlsplit(req.full_url).netloc: raise ValueError("redirect outside official host")
        return super().redirect_request(req,fp,code,msg,headers,new)

def fetch(url):
    if urlsplit(url).scheme!="https": raise ValueError("HTTPS required")
    req=Request(url,headers={"User-Agent":"KansaiMuseumFeed/1.0 (+personal exhibition index)","Accept":"text/html"})
    with build_opener(SameHostRedirect()).open(req,timeout=20) as response:
        raw=response.read(2*1024*1024+1)
        if len(raw)>2*1024*1024: raise ValueError("page too large")
        return raw.decode(response.headers.get_content_charset() or "utf-8")

def _range(text):
    match=RANGE.search(unicodedata.normalize("NFKC",text))
    if not match or not match["ay"]: return None
    start=date(int(match["ay"]),int(match["am"]),int(match["ad"]))
    end_year=int(match["by"]) if match["by"] else start.year+(int(match["bm"])<start.month)
    end=date(end_year,int(match["bm"]),int(match["bd"]))
    return (start.isoformat(),end.isoformat()) if start<=end and (end-start).days<730 else None

def extract(html,source):
    tree,origin,found=Tree(html),urlsplit(source["url"]),{}
    path_re=re.compile(source["path"])
    for anchor in tree.root.walk():
        if anchor.tag!="a": continue
        url=urljoin(source["url"],anchor.attrs.get("href","")); parsed=urlsplit(url)
        if parsed.scheme!="https" or parsed.netloc!=origin.netloc or not path_re.search(parsed.path): continue
        node=anchor
        for _ in range(5):
            if not node or node.tag in ("body","html","root"): break
            text=" ".join(node.text().split()); period=_range(text)
            links={n.attrs.get("href") for n in node.walk() if n.tag=="a" and path_re.search(urlsplit(urljoin(source["url"],n.attrs.get("href",""))).path)}
            if period and len(text)<700 and len(links)<=1:
                if (source.get("require") and not re.search(source["require"],text)) or EXCLUDED.search(text): break
                headings=[n.text() for n in node.walk() if n.tag in ("h2","h3","h4")]
                title=" ".join(headings) if headings else anchor.text()
                title=RANGE.sub("",unicodedata.normalize("NFKC",title))
                title=re.sub(r"開催中|開催予定|終了まで\d+日|チケット購入|\([^)]*\)\s*$","",title)
                title=" ".join(title.split()).strip(" ·|-")
                if len(title)>=3:
                    start,end=period; key=hashlib.sha256(f'{source["id"]}|{title}|{start}'.encode()).hexdigest()[:16]
                    found[key]={"id":key,"museumId":source["id"],"title":title,"start":start,"end":end,"url":url}
                break
            node=node.parent
    return list(found.values())

def load_sources(path):
    sources=json.loads(path.read_text(encoding="utf-8")); ids=[row["id"] for row in sources]
    if len(ids)!=len(set(ids)): raise ValueError("duplicate source id")
    return sources
