import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/"scripts"))
from collector import extract
from update_feed import clean_title, publish, validate

def seed():
    return {"schemaVersion":1,"updatedAt":"2026-09-02","museums":[{"id":"minpaku","url":"https://www.minpaku.ac.jp/","state":"manual"}],"exhibitions":[{"id":"old","museumId":"minpaku","title":"旧題","start":"2026-09-10","end":"2026-12-15","url":"https://www.minpaku.ac.jp/ai1ec_event/69812","verifiedAt":"2026-09-02"}]}
class FeedTests(unittest.TestCase):
    def test_minpaku_extract(self):
        html='<section><h2>企画展 新しい展示</h2><p>2026年9月10日～2026年12月15日</p><a href="/ai1ec_event/69812">企画展 新しい展示</a></section>'
        rows=extract(html,{"id":"minpaku","url":"https://www.minpaku.ac.jp/","path":r"/ai1ec_event/[0-9]+","require":"特別展|企画展"})
        self.assertEqual(1,len(rows)); self.assertEqual("2026-12-15",rows[0]["end"])
    def test_preview_does_not_publish(self):
        old=seed(); out,changed=publish(old,{"minpaku":[]},set(),"2026-09-11"); self.assertFalse(changed); self.assertEqual(old,out)
    def test_content_change_publishes(self):
        old=seed(); new=[{**old["exhibitions"][0],"title":"新題"}]; out,changed=publish(old,{"minpaku":new},{"minpaku"},"2026-09-11"); self.assertTrue(changed); self.assertEqual("新題",out["exhibitions"][0]["title"])
    def test_unchanged_content_does_not_commit(self):
        old=seed(); out,changed=publish(old,{"minpaku":[dict(old["exhibitions"][0])]},{"minpaku"},"2026-09-11"); self.assertFalse(changed); self.assertEqual(old["updatedAt"],out["updatedAt"])
    def test_date_change_keeps_stable_id(self):
        old=seed(); new=[{**old["exhibitions"][0],"start":"2026-09-11","id":"generated"}]
        out,changed=publish(old,{"minpaku":new},{"minpaku"},"2026-09-11")
        self.assertTrue(changed); self.assertEqual("old",out["exhibitions"][0]["id"]); self.assertEqual(1,len(out["exhibitions"]))
    def test_output_order_is_deterministic(self):
        old=seed(); old["museums"].append({"id":"other","url":"https://example.com/","state":"ok"})
        old["exhibitions"].insert(0,{"id":"z","museumId":"other","title":"Z","start":"2026-10-01","end":"2026-10-02","url":"https://example.com/z","verifiedAt":"2026-09-02"})
        out,_=publish(old,{"minpaku":[dict(old["exhibitions"][1])]},{"minpaku"},"2026-09-11")
        self.assertEqual(["old","z"],[e["id"] for e in out["exhibitions"]])
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
    def test_rejects_mass_result(self):
        old=seed()
        with self.assertRaises(ValueError): publish(old,{"minpaku":[dict(old["exhibitions"][0])]*51},{"minpaku"},"2026-09-11")
    def test_current_feed_is_valid(self):
        import json
        validate(json.loads((Path(__file__).parents[1]/"exhibitions.json").read_text(encoding="utf-8")))
if __name__=="__main__": unittest.main()
