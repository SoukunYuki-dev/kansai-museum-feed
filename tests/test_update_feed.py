import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/"scripts"))
from collector import extract
from update_feed import publish

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
if __name__=="__main__": unittest.main()
