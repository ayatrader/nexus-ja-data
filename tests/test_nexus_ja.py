"""nexus-ja-data のテスト

1. 正規化ルールの期待値(名寄せ赤ペン p004 のテストと同じ値)
2. 名寄せ
3. MCPサーバーとして本当に呼べるか(別プロセスで起動してJSON-RPCで会話)
4. 名寄せ赤ペン(JavaScript版)と結果が同じか(Playwrightがある環境だけ)
"""
import json
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nexus_ja import dedupe as D, normalize as N  # noqa: E402

P004 = ROOT.parent / "p004" / "nayose.html"

VECTORS = {
    "company": {"(株)さくら印刷": "株式会社さくら印刷", "ﾐﾄﾞﾘ物産㈱": "ミドリ物産株式会社", "さくら印刷（株）": "さくら印刷株式会社",
                "株式会社　さくら印刷": "株式会社さくら印刷", "(有)青空工務店": "有限会社青空工務店", "ｶ)ｻｸﾗｲﾝｻﾂ": "株式会社サクラインサツ",
                "医療法人社団 健康会": "医療法人社団健康会", "NPO法人 みらい": "特定非営利活動法人みらい", "カラオケ館": "カラオケ館", "": ""},
    "phone": {"03(1234)5678": "03-1234-5678", "0312345678": "03-1234-5678", "０９０－１１１１－２２２２": "090-1111-2222",
              "09011112222": "090-1111-2222", "+81 90-1111-2222": "090-1111-2222", "0120123456": "0120-123-456",
              "045-123-4567": "045-123-4567", "0451234567": "0451234567"},
    "postal": {"〒1500001": "150-0001", "１５０－０００１": "150-0001"},
    "email": {" Yamada@Sakura.EXAMPLE ": "yamada@sakura.example", "ｙａｍａｄａ＠ｅｘａｍｐｌｅ．ｃｏｍ": "yamada@example.com"},
    "person": {"山田  太郎": "山田　太郎"},
    "kana": {"やまだ たろう": "ヤマダ タロウ"},
    "address": {"梅田2ー4ー9": "梅田2-4-9"},
    "date": {"令和6年4月1日": "2024-04-01", "R6.3.15": "2024-03-15", "平成31年4月30日": "2019-04-30", "令和元年5月1日": "2019-05-01",
             "昭和64年1月7日": "1989-01-07", "2024/2/20": "2024-02-20", "2023年12月5日": "2023-12-05", "20240110": "2024-01-10",
             "2024-05-20 10:30": "2024-05-20", "2024/2/30": "2024/2/30", "未定": "未定"},
}
KEY_GROUPS = {
    "company": [["(株)さくら印刷", "さくら印刷株式会社", "株式会社 サクラ印刷", "ｻｸﾗ印刷㈱"]],
    "address": [["東京都渋谷区神宮前一丁目2番3号", "渋谷区神宮前1-2-3", "渋谷区神宮前１－２－３"],
                ["名古屋市中区栄三丁目5番1号", "愛知県名古屋市中区栄3-5-1"]],
    "person": [["山田　太郎", "山田太郎"]],
}


class TestNormalize(unittest.TestCase):
    def test_vectors(self):
        for kind, cases in VECTORS.items():
            for src, want in cases.items():
                self.assertEqual(N.norm(kind, src), want, f"{kind}: {src}")

    def test_keys_group_variants(self):
        for kind, groups in KEY_GROUPS.items():
            for g in groups:
                self.assertEqual(len({N.key(kind, v) for v in g}), 1, g)
        self.assertNotEqual(N.company_key("さくら商事"), N.company_key("さくら商会"))
        self.assertEqual(N.phone_digits("+81 90-1111-2222"), "09011112222")

    def test_guess_type(self):
        cases = {"会社名": "company", "TEL": "phone", "E-mail": "email", "フリガナ": "kana", "所在地": "address",
                 "生年月日": "date", "担当者": "person"}
        for h, t in cases.items():
            self.assertEqual(N.guess_type(h), t, h)
        self.assertEqual(N.guess_type("列3", ["a@b.jp", "c@d.jp"]), "email")


SAMPLE_H = ["元ファイル", "会社名", "担当者", "電話番号", "メール", "住所", "最終取引日"]
SAMPLE = [
    ["a", "(株)さくら印刷", "山田 太郎", "03(1234)5678", "Yamada@Sakura.example", "東京都渋谷区神宮前一丁目2番3号", "令和6年4月1日"],
    ["b", "株式会社 さくら印刷", "山田太郎", "0312345678", "", "渋谷区神宮前1-2-3", "2024-05-20"],
    ["a", "ﾐﾄﾞﾘ物産㈱", "鈴木 花子", "090-1111-2222", "", "", ""],
    ["b", "みどり物産株式会社", "鈴木花子", "０９０１１１１２２２２", "suzuki@midori.example", "", ""],
    ["a", "さくら商会", "伊藤", "06-9876-5432", "", "", ""],
    ["b", "さくら商事株式会社", "中村", "092-333-4444", "", "", ""],
    ["a", "", "", "", "", "", ""],
    ["b", "", "", "", "", "", ""],
]
SAMPLE_T = ["keep", "company", "person", "phone", "email", "address", "date"]


class TestDedupe(unittest.TestCase):
    def run_it(self, **kw):
        rows, _ = D.normalize_table(SAMPLE_H, SAMPLE, SAMPLE_T)
        return D.dedupe(SAMPLE_H, rows, SAMPLE_T, **kw)

    def test_groups_and_summary(self):
        r = self.run_it()
        members = [g["members"] for g in r["groups"]]
        for m in ([0, 1], [2, 3], [4], [5], [6], [7]):
            self.assertIn(m, members)
        self.assertEqual(r["summary"]["removed"], 2)

    def test_representative_fill_and_richer_value(self):
        r = self.run_it()
        g = next(g for g in r["groups"] if g["members"] == [0, 1])
        self.assertEqual(g["representative"], 1)
        rec = r["merged"][0]["record"]
        self.assertEqual(rec["メール"], "yamada@sakura.example")
        self.assertEqual(rec["住所"], "東京都渋谷区神宮前一丁目2番3号")
        self.assertEqual(rec["最終取引日"], "2024-05-20")
        self.assertFalse(any("最終取引日" in n for n in r["merged"][0]["notes"]))

    def test_review_and_manual(self):
        r = self.run_it()
        self.assertTrue(any({x["row_a"], x["row_b"]} == {4, 5} for x in r["review"]))
        self.assertEqual(self.run_it(fuzzy=False)["review"], [])
        linked = self.run_it(links=[(4, 5)])
        self.assertIn([4, 5], [g["members"] for g in linked["groups"]])
        self.assertEqual(self.run_it(ignore=[(4, 5)])["review"], [])

    def test_edition_limit(self):
        rows = [["x", f"会社{i}"] for i in range(D.FREE_LIMIT + 1)]
        # 公開版(open)は行数制限なし
        self.assertEqual(D.EDITION, "open")
        self.assertEqual(D.dedupe(["f", "会社名"], rows, ["keep", "company"])["summary"]["rows"], D.FREE_LIMIT + 1)
        old = D.EDITION
        try:
            D.EDITION = "free"
            with self.assertRaises(ValueError):
                D.dedupe(["f", "会社名"], rows, ["keep", "company"])
        finally:
            D.EDITION = old


class TestMcpServer(unittest.TestCase):
    """本物のMCPクライアントと同じように、別プロセスで起動して標準入出力で会話する"""

    def talk(self, messages):
        p = subprocess.run([sys.executable, "-m", "nexus_ja.server"], cwd=ROOT, input="\n".join(json.dumps(m) for m in messages) + "\n",
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        return [json.loads(l) for l in p.stdout.splitlines() if l.strip()]

    def test_handshake_list_and_calls(self):
        recs = [dict(zip(SAMPLE_H, r)) for r in SAMPLE]
        out = self.talk([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "ja_same_company", "arguments": {"a": "(株)さくら印刷", "b": "ｻｸﾗ印刷㈱"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "ja_normalize_value", "arguments": {"value": "R6.3.15", "kind": "date"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "ja_clean_and_dedupe_records", "arguments": {"records": recs}}},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "ja_normalize_value", "arguments": {"value": "x", "kind": "bad"}}},
        ])
        by = {m["id"]: m for m in out}
        self.assertEqual(len(out), 7)                                     # 通知には返事をしない
        self.assertEqual(by[1]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual({t["name"] for t in by[2]["result"]["tools"]},
                         {"ja_normalize_value", "ja_same_company", "ja_detect_column_types", "ja_clean_and_dedupe_records"})
        self.assertTrue(by[3]["result"]["structuredContent"]["same"])
        self.assertEqual(by[4]["result"]["structuredContent"]["normalized"], "2024-03-15")
        s = by[5]["result"]["structuredContent"]
        self.assertEqual(s["summary"]["after"], 6)
        self.assertEqual(s["column_types"]["会社名"], "company")
        self.assertEqual(json.loads(by[5]["result"]["content"][0]["text"])["summary"]["removed"], 2)
        self.assertEqual(by[6]["error"]["code"], -32602)
        self.assertTrue(by[7]["result"]["isError"])

    def test_bad_json_does_not_crash(self):
        p = subprocess.run([sys.executable, "-m", "nexus_ja.server"], cwd=ROOT,
                           input="{bad json\n" + json.dumps({"jsonrpc": "2.0", "id": 9, "method": "ping"}) + "\n",
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        lines = [json.loads(l) for l in p.stdout.splitlines()]
        self.assertEqual(lines[0]["error"]["code"], -32700)
        self.assertEqual(lines[1]["result"], {})

    def test_no_network_code(self):
        src = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "nexus_ja").glob("*.py"))
        for w in ("urllib", "http.client", "socket", "requests", "subprocess", "os.system", "eval(", "exec("):
            self.assertNotIn(w, src, w)


try:
    from playwright.sync_api import sync_playwright
    HAS_PW = P004.exists()
except ImportError:
    HAS_PW = False


@unittest.skipUnless(HAS_PW, "Playwright か p004 がないため JavaScript 版との一致テストは省略")
class TestSameAsJavaScript(unittest.TestCase):
    def test_every_vector_matches_nayose_html(self):
        inputs = [(k, v) for k, cases in VECTORS.items() for v in cases] + \
                 [(k, v) for k, gs in KEY_GROUPS.items() for g in gs for v in g] + \
                 [("company", x) for x in ("合同会社テスト", "(同)テスト", "一般社団法人 日本協会", "(一社)日本協会", "学校法人 山田学園")] + \
                 [("address", x) for x in ("大阪府大阪市北区梅田2丁目4番9号", "京都府京都市1-2", "梅田2の4の9")] + \
                 [("phone", x) for x in ("050-1234-5678", "(03)1234-5678", "ext.12 03-1234-5678")]
        names = {"company": ("company", "companyKey"), "phone": ("phone", "phoneDigits"), "postal": ("postal", None),
                 "email": ("email", None), "person": ("personName", "personKey"), "kana": ("kana", None),
                 "address": ("address", "addressKey"), "date": ("date", None)}
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.goto(P004.as_uri())
            for kind, v in inputs:
                fn, kfn = names[kind]
                self.assertEqual(pg.evaluate(f"v => Nayose.{fn}(v)", v), N.norm(kind, v), f"{kind}: {v}")
                if kfn:
                    self.assertEqual(pg.evaluate(f"v => Nayose.{kfn}(v)", v), N.key(kind, v), f"key {kind}: {v}")
            b.close()


if __name__ == "__main__":
    unittest.main()


class ToolDesignTest(unittest.TestCase):
    """mcp-builder の作法: 名前に共通の頭文字、注釈(読むだけ・何度呼んでも同じ・外部通信なし)"""
    def test_names_and_annotations(self):
        from nexus_ja import server as S
        for t in S.TOOLS:
            self.assertTrue(t["name"].startswith("ja_"), t["name"])
            self.assertTrue(t["title"])
            a = t["annotations"]
            self.assertEqual((a["readOnlyHint"], a["destructiveHint"], a["idempotentHint"], a["openWorldHint"]), (True, False, True, False))
