from __future__ import annotations
import argparse, copy, json, re, time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from collector import extract, fetch, load_sources

MAX_BYTES=2*1024*1024
def validate(feed):
    if feed.get("schemaVersion")!=1: raise ValueError("unsupported schema")
    museum_ids={m["id"] for m in feed["museums"]}
    if not 1<=len(museum_ids)<=300 or not 1<=len(feed["exhibitions"])<=3000: raise ValueError("invalid feed size")
    seen=set()
    for entry in feed["exhibitions"]:
        if entry["id"] in seen or entry["museumId"] not in museum_ids: raise ValueError("invalid exhibition identity")
        seen.add(entry["id"]); start,end=date.fromisoformat(entry["start"]),date.fromisoformat(entry["end"])
        if start>end or (end-start).days>=730: raise ValueError("invalid date range")
        parsed=urlsplit(entry["url"])
        if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password: raise ValueError("invalid URL")
    if len(json.dumps(feed,ensure_ascii=False).encode())>MAX_BYTES: raise ValueError("feed too large")

def _identity(entry): return entry["museumId"],entry["url"],entry["start"]
def clean_title(title,museum_id):
    if museum_id=="kyocera": title=re.sub(r"\s+会場\[.*\]\s*$","",title)
    if museum_id=="bunpaku": title=re.sub(r"\s+\([月火水木金土日・祝休]+\)\s+[0-9・]+階展示室\s*$","",title)
    if museum_id=="osakaart": title=re.sub(r"\s+特別展\s*$","",title)
    return " ".join(title.split())
def _match(prior_entries,entry):
    exact=[old for old in prior_entries if _identity(old)==_identity(entry)]
    if len(exact)==1: return exact[0]
    same_url=[old for old in prior_entries if old["url"]==entry["url"]]
    return same_url[0] if len(same_url)==1 else None
def publish(previous,results,enabled,checked,retention_days=30):
    output=copy.deepcopy(previous); museums={m["id"]:m for m in output["museums"]}; existing=output["exhibitions"]; changed=False
    if set(enabled)-set(museums): raise ValueError("unknown enabled museum")
    museum_order={m["id"]:index for index,m in enumerate(output["museums"])}
    for museum_id in sorted(enabled,key=lambda mid:museum_order[mid]):
        entries=results.get(museum_id)
        if not entries: continue
        if len(entries)>50 or any(e["museumId"]!=museum_id for e in entries): raise ValueError("suspicious source result")
        old=[e for e in existing if e["museumId"]==museum_id]; merged=[]
        for entry in entries:
            entry={**entry,"title":clean_title(entry["title"],museum_id)}
            prior=_match(old,entry)
            if prior:
                candidate={**prior,**entry}; candidate["id"]=prior["id"]
                if any(candidate.get(k)!=prior.get(k) for k in ("title","start","end","url")): candidate["verifiedAt"]=checked
                merged.append(candidate)
            else: merged.append({**entry,"verifiedAt":checked}); changed=True
        cutoff=date.fromisoformat(checked)-timedelta(days=retention_days); retained_ids={e["id"] for e in merged}
        retained=[e for e in old if date.fromisoformat(e["end"])>=cutoff and e["id"] not in retained_ids]
        replacement=merged+retained
        if replacement!=old: changed=True
        existing=[e for e in existing if e["museumId"]!=museum_id]+replacement; museums[museum_id]["state"]="ok"
    output["exhibitions"]=sorted(existing,key=lambda e:(museum_order[e["museumId"]],e["start"],e["id"]))
    if changed: output["updatedAt"]=checked
    validate(output); return output,changed

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--feed",default="exhibitions.json"); parser.add_argument("--sources",default="config/sources.json"); parser.add_argument("--report",default="report/collection-report.json"); args=parser.parse_args()
    feed_path=Path(args.feed); previous=json.loads(feed_path.read_text(encoding="utf-8")); validate(previous)
    checked=datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat(); sources=load_sources(Path(args.sources)); results,report,enabled={},[],set()
    for source in sources:
        if source.get("autoPublish"): enabled.add(source["id"])
        try:
            entries=[e for e in extract(fetch(source["url"]),source) if e["end"]>=checked]; results[source["id"]]=entries
            report.append({"museumId":source["id"],"status":"obtained" if entries else "needs_review","count":len(entries),"autoPublish":bool(source.get("autoPublish")),"entries":entries})
        except Exception as error:
            results[source["id"]]=[]; report.append({"museumId":source["id"],"status":"error","error":type(error).__name__,"errorDetail":str(error)[:240],"count":0,"autoPublish":bool(source.get("autoPublish"))})
        time.sleep(1)
    output,changed=publish(previous,results,enabled,checked)
    report_path=Path(args.report); report_path.parent.mkdir(parents=True,exist_ok=True); report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if changed: feed_path.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if enabled and not any(results.get(mid) for mid in enabled): raise RuntimeError("all enabled sources failed; feed retained")
if __name__=="__main__": main()
