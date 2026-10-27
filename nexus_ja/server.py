"""MCPサーバー(標準入出力・JSON-RPC 2.0)。Python標準ライブラリのみ、外部通信なし。

起動: python -m nexus_ja.server
AI(Claude Desktop など)の設定に登録すると、AIがこの道具を呼べるようになる。
"""
import json
import sys

from . import __version__, dedupe as D, normalize as N

PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]
KINDS = [k for k in N.TYPES if k != "keep"]

TOOLS = [
    {
        "name": "ja_normalize_value",
        "title": "日本語の値をそろえる",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "description": ("日本語のビジネスデータ1つを、種類に合った正しい表記にそろえ、比較用の鍵も返す。"
                        "会社名の(株)/㈱/株式会社/半角カナ、電話の区切り、郵便番号、メール、住所の丁目番地、"
                        "和暦(令和/平成/R6.3.15)の日付などに対応。AIが自分で推測して直すより正確で再現性がある。"
                        " Normalize one Japanese business value (company, phone, postal code, address, Japanese era date, etc.)."),
        "inputSchema": {"type": "object", "properties": {
            "value": {"type": "string", "description": "直したい値"},
            "kind": {"type": "string", "enum": KINDS, "description": "値の種類"}},
            "required": ["value", "kind"]},
    },
    {
        "name": "ja_same_company",
        "title": "同じ会社かを判定",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "description": ("2つの会社名が同じ会社を指すかを判定する(法人格の有無・位置、全角半角、ひらがな/カタカナの違いを吸収)。"
                        "似ているだけの別会社(さくら商事/さくら商会)は same=false で similarity を返す。"
                        " Check whether two Japanese company names refer to the same company."),
        "inputSchema": {"type": "object", "properties": {
            "a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a", "b"]},
    },
    {
        "name": "ja_detect_column_types",
        "title": "列の種類を推定",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "description": "表の列名と値の例から、列の種類(company/person/phone/email/postal/address/date/kana/text)を推定する。",
        "inputSchema": {"type": "object", "properties": {
            "headers": {"type": "array", "items": {"type": "string"}},
            "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}},
                     "description": "値の例(最大50行で十分)"}},
            "required": ["headers"]},
    },
    {
        "name": "ja_clean_and_dedupe_records",
        "title": "名簿の名寄せ",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "description": ("日本語の顧客名簿・取引先リストを正規化し、同じ相手の重複を見つけて1件にまとめる(名寄せ)。"
                        "メール・電話・会社名+担当者などで判定し、空欄どうしは一致にしない。似ている会社名は自動でまとめず review に出す。"
                        "返り値: summary(件数)、merged(まとめた結果)、groups、review、changes(直した箇所)。"
                        " Clean and deduplicate Japanese customer records (name matching / 名寄せ)."),
        "inputSchema": {"type": "object", "properties": {
            "records": {"type": "array", "items": {"type": "object"},
                        "description": "1件=1つのオブジェクト。キーが列名"},
            "types": {"type": "object", "description": "列名→種類 の指定(省略時は自動推定)"},
            "fill_blanks": {"type": "boolean", "default": True},
            "report_similar_companies": {"type": "boolean", "default": True}},
            "required": ["records"]},
    },
]


def _tool_normalize(args):
    kind = args.get("kind", "text")
    if kind not in KINDS:
        raise ValueError(f"kind は {', '.join(KINDS)} のどれかにしてください。迷ったら ja_detect_column_types で列の種類を先に調べられます")
    v = args.get("value", "")
    out = N.norm(kind, v)
    return {"input": v, "kind": kind, "normalized": out, "match_key": N.key(kind, v), "changed": out != v}


def _tool_same_company(args):
    a, b = args.get("a", ""), args.get("b", "")
    ka, kb = N.company_key(a), N.company_key(b)
    same = bool(ka) and ka == kb
    return {"same": same, "a_normalized": N.company(a), "b_normalized": N.company(b),
            "similarity": round(N.similarity(ka, kb), 2) if ka and kb else 0.0,
            "note": "同じ会社とみなせる表記の違いです" if same else
            ("似ていますが別の会社の可能性があります。住所や電話も確認してください" if ka and kb and N.similarity(ka, kb) >= 0.72 else "別の会社です")}


def _tool_detect(args):
    headers = [str(h) for h in args.get("headers", [])]
    rows = args.get("rows") or []
    return {"types": {h: N.guess_type(h, [r[i] for r in rows if i < len(r)]) for i, h in enumerate(headers)}}


def _tool_dedupe(args):
    recs = args.get("records") or []
    if not isinstance(recs, list) or not all(isinstance(r, dict) for r in recs):
        raise ValueError('records はオブジェクトの配列にしてください。例: [{"会社名": "(株)さくら印刷", "電話": "03-1234-5678"}]')
    headers = []
    for r in recs:
        for k in r:
            if k not in headers:
                headers.append(str(k))
    raw = [["" if r.get(h) is None else str(r.get(h)) for h in headers] for r in recs]
    given = args.get("types") or {}
    types = [given.get(h) or N.guess_type(h, [x[i] for x in raw[:60]]) for i, h in enumerate(headers)]
    rows, changes = D.normalize_table(headers, raw, types)
    res = D.dedupe(headers, rows, types, fill=args.get("fill_blanks", True),
                   fuzzy=args.get("report_similar_companies", True))
    res["column_types"] = dict(zip(headers, types))
    res["changes"] = changes[:500]
    res["changes_total"] = len(changes)
    return res


HANDLERS = {"ja_normalize_value": _tool_normalize, "ja_same_company": _tool_same_company,
            "ja_detect_column_types": _tool_detect, "ja_clean_and_dedupe_records": _tool_dedupe}


def handle(msg):
    """1通のJSON-RPCメッセージを処理。通知なら None を返す"""
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:
        return None
    try:
        if method == "initialize":
            want = params.get("protocolVersion")
            result = {"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0],
                      "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": "nexus-ja-data", "version": __version__},
                      "instructions": "日本語のビジネスデータ(会社名・電話・住所・和暦など)を扱うときは、推測で直さずこの道具を使うと正確です。"}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            name = params.get("name")
            if name not in HANDLERS:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"不明な道具: {name}"}}
            try:
                out = HANDLERS[name](params.get("arguments") or {})
                result = {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
                          "structuredContent": out, "isError": False}
            except ValueError as e:
                result = {"content": [{"type": "text", "text": str(e)}], "isError": True}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"未対応: {method}"}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    except Exception as e:  # 想定外でもサーバーは落とさない
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": f"内部エラー: {e}"}}


def main():
    for enc_stream in (sys.stdin, sys.stdout):
        if hasattr(enc_stream, "reconfigure"):
            enc_stream.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSONとして読めません"}}) + "\n")
            sys.stdout.flush()
            continue
        resp = handle(msg) if isinstance(msg, dict) else None
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
