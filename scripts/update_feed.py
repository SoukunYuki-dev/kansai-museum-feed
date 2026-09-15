from __future__ import annotations
import argparse, copy, json, re, time, unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from collector import extract, fetch, load_sources

MAX_BYTES=2*1024*1024
def _required_text(record,fields):
    if not isinstance(record,dict) or any(not isinstance(record.get(field),str) or not record[field].strip() for field in fields):
        raise ValueError("missing required text")
def _https_url(value):
    parsed=urlsplit(value)
    if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password or any(char.isspace() for char in value):
        raise ValueError("invalid URL")
def validate(feed):
    if not isinstance(feed,dict) or feed.get("schemaVersion")!=1: raise ValueError("unsupported schema")
    museums,exhibitions=feed.get("museums"),feed.get("exhibitions")
    if not isinstance(museums,list) or not 1<=len(museums)<=300 or not isinstance(exhibitions,list) or not 1<=len(exhibitions)<=3000: raise ValueError("invalid feed size")
    try: date.fromisoformat(feed["updatedAt"])
    except (KeyError,TypeError,ValueError) as error: raise ValueError("invalid updatedAt") from error
    museum_ids=[]
    for museum in museums:
        _required_text(museum,("id","name","region","genre","url","state")); _https_url(museum["url"]); museum_ids.append(museum["id"])
        if not isinstance(museum.get("priority"),int): raise ValueError("invalid museum priority")
    if len(museum_ids)!=len(set(museum_ids)): raise ValueError("duplicate museum id")
    museum_ids=set(museum_ids)
    seen=set()
    for entry in exhibitions:
        _required_text(entry,("id","museumId","title","start","end","url","verifiedAt"))
        if entry["id"] in seen or entry["museumId"] not in museum_ids: raise ValueError("invalid exhibition identity")
        seen.add(entry["id"]); start,end=date.fromisoformat(entry["start"]),date.fromisoformat(entry["end"])
        if start>end or (end-start).days>=730: raise ValueError("invalid date range")
        _https_url(entry["url"]); date.fromisoformat(entry["verifiedAt"])
    if len(json.dumps(feed,ensure_ascii=False).encode())>MAX_BYTES: raise ValueError("feed too large")

def _identity(entry): return entry["museumId"],entry["url"],entry["start"]
def _title_key(title): return " ".join(unicodedata.normalize("NFKC",title).casefold().split())
def clean_title(title,museum_id):
    if museum_id=="kyocera": title=re.sub(r"\s+会場\[.*\]\s*$","",title)
    if museum_id=="bunpaku": title=re.sub(r"\s+\([月火水木金土日・祝休]+\)\s+[0-9・]+階展示室\s*$","",title)
    if museum_id=="osakaart": title=re.sub(r"\s+特別展\s*$","",title)
    return " ".join(title.split())
def _match_all(prior_entries,entries):
    matches={}; consumed=set()
    def assign_unique(key):
        old_groups={}; new_groups={}
        for old in prior_entries:
            if old["id"] not in consumed: old_groups.setdefault(key(old),[]).append(old)
        for index,entry in enumerate(entries):
            if index not in matches: new_groups.setdefault(key(entry),[]).append(index)
        for value,indexes in new_groups.items():
            candidates=old_groups.get(value,[])
            if len(indexes)==1 and len(candidates)==1:
                matches[indexes[0]]=candidates[0]; consumed.add(candidates[0]["id"])
    assign_unique(_identity)
    assign_unique(lambda entry:(entry["url"],_title_key(entry["title"])))
    assign_unique(lambda entry:entry["url"])
    assign_unique(lambda entry:(_title_key(entry["title"]),entry["start"]))
    return matches
def publish(previous,results,enabled,checked,retention_days=30):
    output=copy.deepcopy(previous); museums={m["id"]:m for m in output["museums"]}; existing=output["exhibitions"]; changed=False
    if set(enabled)-set(museums): raise ValueError("unknown enabled museum")
    museum_order={m["id"]:index for index,m in enumerate(output["museums"])}
    for museum_id in sorted(enabled,key=lambda mid:museum_order[mid]):
        entries=results.get(museum_id)
        if not entries: continue
        if len(entries)>50 or any(e["museumId"]!=museum_id for e in entries): raise ValueError("suspicious source result")
        old=[e for e in existing if e["museumId"]==museum_id]; replacements={}; additions=[]
        prepared=[{**entry,"title":clean_title(entry["title"],museum_id)} for entry in entries]
        matches=_match_all(old,prepared)
        for index,entry in enumerate(prepared):
            prior=matches.get(index)
            if prior:
                candidate={**prior,**entry}; candidate["id"]=prior["id"]
                if any(candidate.get(k)!=prior.get(k) for k in ("title","start","end","url")): candidate["verifiedAt"]=checked
                replacements[prior["id"]]=candidate
            else: additions.append({**entry,"verifiedAt":checked})
        cutoff=date.fromisoformat(checked)-timedelta(days=retention_days); rebuilt=[]; last_position=None
        for old_entry in existing:
            if old_entry["museumId"]!=museum_id:
                rebuilt.append(old_entry); continue
            replacement=replacements.get(old_entry["id"])
            if replacement is not None: rebuilt.append(replacement)
            elif date.fromisoformat(old_entry["end"])>=cutoff: rebuilt.append(old_entry)
            last_position=len(rebuilt)
        if additions:
            at=last_position if last_position is not None else len(rebuilt)
            rebuilt[at:at]=sorted(additions,key=lambda e:(e["start"],e["id"]))
        existing=rebuilt; museums[museum_id]["state"]="ok"
    output["exhibitions"]=existing
    changed=output["exhibitions"]!=previous["exhibitions"] or output["museums"]!=previous["museums"]
    if changed: output["updatedAt"]=checked
    validate(output); return output,changed

def _write_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True); temporary=path.with_name(path.name+".tmp")
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); temporary.replace(path)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--feed",default="exhibitions.json"); parser.add_argument("--sources",default="config/sources.json"); parser.add_argument("--report",default="report/collection-report.json"); args=parser.parse_args()
    feed_path=Path(args.feed); previous=json.loads(feed_path.read_text(encoding="utf-8")); validate(previous)
    checked=datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat(); sources=load_sources(Path(args.sources)); results,report,enabled={},[],set()
    for source in sources:
        if source.get("autoPublish"): enabled.add(source["id"])
        try:
            entries=[e for e in extract(fetch(source["url"],source.get("caFile")),source) if e["end"]>=checked]; results[source["id"]]=entries
            report.append({"museumId":source["id"],"status":"obtained" if entries else "needs_review","count":len(entries),"autoPublish":bool(source.get("autoPublish")),"entries":entries})
        except Exception as error:
            results[source["id"]]=[]; report.append({"museumId":source["id"],"status":"error","error":type(error).__name__,"errorDetail":str(error)[:240],"count":0,"autoPublish":bool(source.get("autoPublish"))})
        time.sleep(1)
    report_path=Path(args.report); _write_json(report_path,report)
    output,changed=publish(previous,results,enabled,checked)
    if changed: _write_json(feed_path,output)
    if enabled and not any(results.get(mid) for mid in enabled): raise RuntimeError("all enabled sources failed; feed retained")
if __name__=="__main__": main()
