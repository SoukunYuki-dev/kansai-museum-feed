import hashlib, json, ssl, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/"scripts"))
import collector
from collector import extract
import update_feed
from update_feed import clean_title, publish, validate

def seed():
    return {"schemaVersion":1,"updatedAt":"2026-09-02","museums":[{"id":"minpaku","name":"国立民族学博物館","region":"大阪","genre":"民族学","priority":90,"url":"https://www.minpaku.ac.jp/","state":"manual"}],"exhibitions":[{"id":"old","museumId":"minpaku","title":"旧題","start":"2026-09-10","end":"2026-12-15","url":"https://www.minpaku.ac.jp/ai1ec_event/69812","verifiedAt":"2026-09-02"}]}
class FeedTests(unittest.TestCase):
    def test_custom_ca_context_keeps_verification_enabled(self):
        cert=Path(__file__).parents[1]/"certs"/"nii-odca4g8rsa-pem.cer"
        make_context=getattr(collector,"tls_context",lambda _cert: None)
        context=make_context(cert)
        self.assertIsInstance(context,ssl.SSLContext)
        self.assertEqual(ssl.CERT_REQUIRED,context.verify_mode)
        self.assertTrue(context.check_hostname)
        self.assertTrue(context.verify_flags & ssl.VERIFY_X509_PARTIAL_CHAIN)
        fingerprints={
            hashlib.sha256(der).hexdigest().upper()
            for der in context.get_ca_certs(binary_form=True)
        }
        self.assertIn(
            "7A4AD9E1BA2DFB08F752A124032F7058868062E9841785623EB4136783A53FFC",
            fingerprints,
        )

    def test_source_ca_file_is_used_for_collection(self):
        html='<section><h2>企画展 新しい展示</h2><p>2026年9月10日～2026年12月15日</p><a href="/ai1ec_event/69812">企画展 新しい展示</a></section>'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); feed=root/"feed.json"; sources=root/"sources.json"; report=root/"report.json"
            cert=Path(__file__).parents[1]/"certs"/"nii-odca4g8rsa-pem.cer"
            feed.write_text(json.dumps(seed(),ensure_ascii=False),encoding="utf-8")
            sources.write_text(json.dumps([{
                "id":"minpaku",
                "url":"https://www.minpaku.ac.jp/",
                "path":"/ai1ec_event/[0-9]+",
                "require":"特別展|企画展",
                "caFile":str(cert),
                "autoPublish":False,
            }]),encoding="utf-8")
            def protected_fetch(_url,cafile=None):
                if cafile!=str(cert): raise ValueError("custom CA not forwarded")
                return html
            argv=["update_feed.py","--feed",str(feed),"--sources",str(sources),"--report",str(report)]
            with patch.object(sys,"argv",argv), patch.object(update_feed,"fetch",side_effect=protected_fetch), patch.object(update_feed.time,"sleep"):
                update_feed.main()
            result=json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual("obtained",result[0]["status"])
            self.assertEqual(1,result[0]["count"])

    def test_minpaku_extract(self):
        html='<section><h2>企画展 新しい展示</h2><p>2026年9月10日～2026年12月15日</p><a href="/ai1ec_event/69812">企画展 新しい展示</a></section>'
        rows=extract(html,{"id":"minpaku","url":"https://www.minpaku.ac.jp/","path":r"/ai1ec_event/[0-9]+","require":"特別展|企画展"})
        self.assertEqual(1,len(rows)); self.assertEqual("2026-12-15",rows[0]["end"])
    def test_preview_does_not_publish(self):
        old=seed(); out,changed=publish(old,{"minpaku":[]},set(),"2026-09-11"); self.assertFalse(changed); self.assertEqual(old,out)
    def test_content_change_publishes(self):
        old=seed(); new=[{**old["exhibitions"][0],"title":"新題"}]; out,changed=publish(old,{"minpaku":new},{"minpaku"},"2026-09-11"); self.assertTrue(changed); self.assertEqual("新題",out["exhibitions"][0]["title"])
    def test_unchanged_content_does_not_commit(self):
        old=seed(); old["museums"][0]["state"]="ok"
        out,changed=publish(old,{"minpaku":[dict(old["exhibitions"][0])]},{"minpaku"},"2026-09-11"); self.assertFalse(changed); self.assertEqual(old["updatedAt"],out["updatedAt"])
    def test_date_change_keeps_stable_id(self):
        old=seed(); new=[{**old["exhibitions"][0],"start":"2026-09-11","id":"generated"}]
        out,changed=publish(old,{"minpaku":new},{"minpaku"},"2026-09-11")
        self.assertTrue(changed); self.assertEqual("old",out["exhibitions"][0]["id"]); self.assertEqual(1,len(out["exhibitions"]))
    def test_url_change_keeps_stable_id(self):
        old=seed(); new=[{**old["exhibitions"][0],"url":"https://www.minpaku.ac.jp/ai1ec_event/69812-new","id":"generated"}]
        out,changed=publish(old,{"minpaku":new},{"minpaku"},"2026-09-11")
        self.assertTrue(changed); self.assertEqual(["old"],[e["id"] for e in out["exhibitions"]])
    def test_shared_url_date_change_matches_by_title(self):
        old=seed(); shared="https://www.minpaku.ac.jp/exhibitions/2026"
        old["exhibitions"]=[
            {**old["exhibitions"][0],"id":"first","title":"企画展 A","url":shared},
            {**old["exhibitions"][0],"id":"second","title":"企画展 B","url":shared},
        ]
        new=[
            {**old["exhibitions"][0],"id":"new-a","start":"2026-09-11"},
            {**old["exhibitions"][1],"id":"new-b","start":"2026-09-12"},
        ]
        out,_=publish(old,{"minpaku":new},{"minpaku"},"2026-09-11")
        self.assertEqual(["first","second"],[e["id"] for e in out["exhibitions"]])
    def test_new_shared_url_sibling_cannot_steal_stable_id(self):
        old=seed(); shared="https://www.minpaku.ac.jp/exhibitions/2026"
        old["exhibitions"][0].update({"id":"stable-a","title":"企画展 A","url":shared})
        sibling={**old["exhibitions"][0],"id":"new-b","title":"企画展 B"}
        current={**old["exhibitions"][0],"id":"generated-a"}
        out,_=publish(old,{"minpaku":[sibling,current]},{"minpaku"},"2026-09-11")
        by_title={e["title"]:e["id"] for e in out["exhibitions"]}
        self.assertEqual("stable-a",by_title["企画展 A"])
        self.assertEqual("new-b",by_title["企画展 B"])
    def test_existing_order_is_preserved(self):
        old=seed(); old["museums"].append({"id":"other","name":"他館","region":"大阪","genre":"美術","priority":1,"url":"https://example.com/","state":"ok"})
        old["exhibitions"].insert(0,{"id":"z","museumId":"other","title":"Z","start":"2026-10-01","end":"2026-10-02","url":"https://example.com/z","verifiedAt":"2026-09-02"})
        out,_=publish(old,{"minpaku":[dict(old["exhibitions"][1])]},{"minpaku"},"2026-09-11")
        self.assertEqual(["z","old"],[e["id"] for e in out["exhibitions"]])
    def test_title_cleanup(self):
        self.assertEqual("禅とジブリ",clean_title("禅とジブリ 会場[ 新館 東山キューブ ]","kyocera"))
        self.assertEqual("円山応挙",clean_title("円山応挙 特別展","osakaart"))
        self.assertEqual("寛永 太平",clean_title("寛永 太平 (日) 4・3階展示室","bunpaku"))
    def test_rejects_invalid_date(self):
        old=seed(); bad={**old["exhibitions"][0],"end":"2026-01-01"}
        with self.assertRaises(ValueError): publish(old,{"minpaku":[bad]},{"minpaku"},"2026-09-11")
    def test_rejects_unknown_enabled_museum(self):
        with self.assertRaises(ValueError): publish(seed(),{"unknown":[]},{"unknown"},"2026-09-11")
    def test_rejects_http_url(self):
        old=seed(); bad={**old["exhibitions"][0],"url":"http://example.com"}
        with self.assertRaises(ValueError): publish(old,{"minpaku":[bad]},{"minpaku"},"2026-09-11")
    def test_rejects_duplicate_museum_ids(self):
        old=seed(); old["museums"].append(dict(old["museums"][0]))
        with self.assertRaises(ValueError): validate(old)
    def test_rejects_invalid_museum_url(self):
        old=seed(); old["museums"][0]["url"]="http://example.com"
        with self.assertRaises(ValueError): validate(old)
    def test_rejects_blank_title(self):
        old=seed(); old["exhibitions"][0]["title"]="  "
        with self.assertRaises(ValueError): validate(old)
    def test_rejects_invalid_feed_dates(self):
        for field,value in (("updatedAt","not-a-date"),("verifiedAt","not-a-date")):
            with self.subTest(field=field):
                old=seed()
                if field=="updatedAt": old[field]=value
                else: old["exhibitions"][0][field]=value
                with self.assertRaises(ValueError): validate(old)
    def test_multiple_date_ranges_are_not_published(self):
        html='<section><h2>企画展 A</h2><p>2026年9月10日～2026年12月15日</p><p>2027年1月1日～2027年2月1日</p><a href="/ai1ec_event/69812">企画展 A</a></section>'
        rows=extract(html,{"id":"minpaku","url":"https://www.minpaku.ac.jp/","path":r"/ai1ec_event/[0-9]+","require":"特別展|企画展"})
        self.assertEqual([],rows)
    def test_report_is_saved_when_publish_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); feed=root/"feed.json"; sources=root/"sources.json"; report=root/"report.json"
            feed.write_text(json.dumps(seed(),ensure_ascii=False),encoding="utf-8")
            sources.write_text(json.dumps([{"id":"minpaku","url":"https://www.minpaku.ac.jp/","path":"/event/","autoPublish":True}]),encoding="utf-8")
            argv=["update_feed.py","--feed",str(feed),"--sources",str(sources),"--report",str(report)]
            with patch.object(sys,"argv",argv), patch.object(update_feed,"fetch",return_value=""), patch.object(update_feed,"extract",return_value=[]), patch.object(update_feed,"publish",side_effect=ValueError("boom")):
                with self.assertRaisesRegex(ValueError,"boom"): update_feed.main()
            self.assertTrue(report.exists())
    def test_rejects_mass_result(self):
        old=seed()
        with self.assertRaises(ValueError): publish(old,{"minpaku":[dict(old["exhibitions"][0])]*51},{"minpaku"},"2026-09-11")
    def test_current_feed_is_valid(self):
        import json
        validate(json.loads((Path(__file__).parents[1]/"exhibitions.json").read_text(encoding="utf-8")))
if __name__=="__main__": unittest.main()
