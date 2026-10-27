"""日本語ビジネスデータの正規化ルール(名寄せ赤ペン p004 と同じ結果になるように作っている)

各種類に2つの関数がある:
  norm(値) -> 表示用にそろえた値(人が読む形)
  key(値)  -> 同じものかどうかを比べるための鍵(空文字は「比べない」)
"""
import re
import unicodedata

# ---------------------------------------------------------------- 共通

_ZW = re.compile("[​-‍﻿]")
_WS = re.compile(r"\s+")


def base(s) -> str:
    """NFKC(全角英数→半角、半角カナ→全角、㈱→(株))+ 空白の整理"""
    if s is None:
        return ""
    v = unicodedata.normalize("NFKC", str(s))
    v = _ZW.sub("", v)
    return _WS.sub(" ", v).strip()


HYPHENS = re.compile("[‐‑‒–—―−ｰー－﹣⁃]")


def _hira_to_kata(s: str) -> str:
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in s)


# ---------------------------------------------------------------- 会社名

_CORP_FULL = ["株式会社", "有限会社", "合同会社", "合資会社", "合名会社", "一般社団法人", "一般財団法人",
              "公益社団法人", "公益財団法人", "特定非営利活動法人", "医療法人社団", "医療法人財団", "医療法人",
              "社会福祉法人", "学校法人"]
_CORP = [
    ("株式会社", [r"株式会社", r"\(株\)", r"\(カ\)", r"^カ\)", r"\(カ$"]),
    ("有限会社", [r"有限会社", r"\(有\)", r"\(ユ\)", r"^ユ\)", r"\(ユ$"]),
    ("合同会社", [r"合同会社", r"\(同\)", r"\(合\)", r"\(ド\)", r"^ド\)"]),
    ("合資会社", [r"合資会社", r"\(資\)", r"\(シ\)"]),
    ("合名会社", [r"合名会社", r"\(名\)", r"\(メ\)"]),
    ("一般社団法人", [r"一般社団法人", r"\(一社\)", r"\(一般社団\)"]),
    ("一般財団法人", [r"一般財団法人", r"\(一財\)", r"\(一般財団\)"]),
    ("公益社団法人", [r"公益社団法人", r"\(公社\)"]),
    ("公益財団法人", [r"公益財団法人", r"\(公財\)"]),
    ("特定非営利活動法人", [r"特定非営利活動法人", r"NPO法人", r"\(特非\)"]),
    ("医療法人", [r"医療法人社団", r"医療法人財団", r"医療法人", r"\(医\)"]),
    ("社会福祉法人", [r"社会福祉法人", r"\(福\)"]),
    ("学校法人", [r"学校法人", r"\(学\)"]),
]
_CORP_RE = [(full, re.compile("(" + "|".join(p) + ")")) for full, p in _CORP]
_ABBR = re.compile(r"[\(（]\s*(株|有|同|合|資|名|一社|一財|公社|公財|特非|医|福|学|カ|ユ|ド|シ|メ)\s*[\)）]")
_CORP_SPACE = re.compile(r"\s*(" + "|".join(sorted(_CORP_FULL, key=len, reverse=True)) + r")\s*")
_CORP_ANY = re.compile("|".join(sorted(_CORP_FULL, key=len, reverse=True)))
_KEY_STRIP = re.compile(r"[\s・･.,、。'\"’”\-‐－&＆()（）]")


def company(s) -> str:
    v = base(s)
    if not v:
        return ""
    v = _ABBR.sub(r"(\1)", v)
    for full, rx in _CORP_RE:
        v = rx.sub(lambda m, f=full: m.group(0) if re.fullmatch(r"医療法人(社団|財団)", m.group(0)) else f, v)
    return _CORP_SPACE.sub(r"\1", v).strip()


def company_key(s) -> str:
    v = company(s)
    if not v:
        return ""
    v = _CORP_ANY.sub("", v)
    return _KEY_STRIP.sub("", _hira_to_kata(v.lower()))


# ---------------------------------------------------------------- 人名・フリガナ

def person(s) -> str:
    v = base(s)
    return re.sub("　+", "　", v.replace(" ", "　"))


def person_key(s) -> str:
    return re.sub(r"\s", "", base(s))


def kana(s) -> str:
    return _hira_to_kata(base(s))


def kana_key(s) -> str:
    return re.sub(r"\s", "", kana(s))


# ---------------------------------------------------------------- 電話・郵便・メール

def phone_digits(s) -> str:
    d = re.sub(r"[^\d+]", "", base(s))
    if d.startswith("+81"):
        d = "0" + re.sub(r"^0", "", d[3:])
    return re.sub(r"\D", "", d)


def phone(s) -> str:
    raw = base(s)
    if not raw:
        return ""
    if re.search("[a-zA-Z]", re.sub(r"(ext|内線)", "", raw, flags=re.I)):
        return raw
    v = re.sub(r"^\+81[\s\-]*\(?0?\)?", "0", raw)
    v = HYPHENS.sub("-", v)
    v = re.sub(r"[()（）]", "-", v)
    v = re.sub(r"\s+", "-", v)
    v = re.sub(r"-+", "-", v).strip("-")
    d = re.sub(r"\D", "", v)
    if "-" in v and len(d) >= 10:
        return v
    if re.fullmatch(r"0[789]0\d{8}", d) or re.fullmatch(r"050\d{8}", d):
        return f"{d[:3]}-{d[3:7]}-{d[7:]}"
    if re.fullmatch(r"0(120|800)\d{6}", d):
        return f"{d[:4]}-{d[4:7]}-{d[7:]}"
    if re.fullmatch(r"0[36]\d{8}", d):
        return f"{d[:2]}-{d[2:6]}-{d[6:]}"
    return d if len(d) >= 10 else v


def postal(s) -> str:
    d = re.sub(r"\D", "", base(s).replace("〒", ""))
    if len(d) == 7:
        return f"{d[:3]}-{d[3:]}"
    return re.sub(r"〒\s*", "", base(s))


def postal_key(s) -> str:
    return re.sub(r"\D", "", base(s))


def email(s) -> str:
    return re.sub(r"\s", "", base(s)).replace("＠", "@").lower()


# ---------------------------------------------------------------- 住所

_KNUM = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _kanji_to_num(k: str) -> str:
    if not re.fullmatch("[一二三四五六七八九十〇]+", k):
        return k
    if "十" not in k:
        n = 0
        for c in k:
            n = n * 10 + _KNUM[c]
        return str(n)
    t, o = k.split("十", 1)
    return str((_KNUM[t] if t else 1) * 10 + (_KNUM[o] if o else 0))


def address(s) -> str:
    v = HYPHENS.sub("-", base(s))
    v = re.sub(r"(\d)\s*の\s*(\d)", r"\1-\2", v)
    return re.sub(r"\s*-\s*", "-", v)


_PREF = re.compile(r"^(北海道|東京都|京都府|大阪府|.{2,3}県)")


def address_key(s) -> str:
    v = re.sub(r"\s", "", address(s))
    v = re.sub("([一二三四五六七八九十〇]+)(丁目)", lambda m: _kanji_to_num(m.group(1)) + "丁目", v)
    v = re.sub(r"(\d+)丁目", r"\1-", v)
    v = re.sub(r"(\d+)番地?", r"\1-", v)
    v = re.sub(r"(\d+)号", r"\1", v)
    v = re.sub("-+", "-", v)
    v = re.sub("-$", "", v)
    return _PREF.sub("", v).lower()


# ---------------------------------------------------------------- 日付

_ERAS = [("令和", "R", 2018), ("平成", "H", 1988), ("昭和", "S", 1925), ("大正", "T", 1911), ("明治", "M", 1867)]


def _valid(y, m, d) -> bool:
    import datetime
    try:
        datetime.date(y, m, d)
        return True
    except ValueError:
        return False


def date(s) -> str:
    v = base(s)
    if not v:
        return ""

    def fmt(y, m, d):
        return f"{y:04d}-{m:02d}-{d:02d}" if _valid(y, m, d) else v

    for jp, ab, off in _ERAS:
        m = re.fullmatch(rf"(?:{jp}|{ab})\s*(\d{{1,2}}|元)\s*[年./-]\s*(\d{{1,2}})\s*[月./-]\s*(\d{{1,2}})\s*日?", v, flags=re.I)
        if m:
            return fmt(off + (1 if m.group(1) == "元" else int(m.group(1))), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"(\d{4})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})\s*日?(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?", v)
    if m:
        return fmt(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", v)
    if m:
        return fmt(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return v


# ---------------------------------------------------------------- 種類の一覧

TYPES = {
    "text": ("そのまま(空白などだけ整える)", base, lambda s: base(s).lower()),
    "company": ("会社名・団体名", company, company_key),
    "person": ("氏名", person, person_key),
    "kana": ("フリガナ", kana, kana_key),
    "phone": ("電話・FAX", phone, phone_digits),
    "postal": ("郵便番号", postal, postal_key),
    "email": ("メールアドレス", email, email),
    "address": ("住所", address, address_key),
    "date": ("日付", date, date),
    "keep": ("触らない", lambda s: "" if s is None else str(s), lambda s: "" if s is None else str(s)),
}


def norm(kind: str, value) -> str:
    return TYPES.get(kind, TYPES["text"])[1](value)


def key(kind: str, value) -> str:
    return TYPES.get(kind, TYPES["text"])[2](value)


def guess_type(header: str, samples=()) -> str:
    h = base(header).lower()
    rules = [
        (r"(フリガナ|ふりがな|カナ|かな|ヨミ|よみ)", "kana"),
        (r"(会社|社名|法人|取引先|企業|団体|屋号|勤務先|所属)", "company"),
        (r"(メール|mail|e-mail)", "email"),
        (r"(電話|tel|携帯|fax|ファックス|連絡先)", "phone"),
        (r"(郵便|〒|zip|postal)", "postal"),
        (r"(住所|所在地|address)", "address"),
        (r"(日付|年月日|生年月日|日$|date|登録日|更新日)", "date"),
        (r"(氏名|名前|お名前|担当者|代表者|name)", "person"),
        (r"(元ファイル|id|番号|no\.?$|コード|code)", "keep"),
    ]
    for rx, t in rules:
        if re.search(rx, h):
            return t
    vals = [v for v in (base(x) for x in samples) if v][:50]
    if not vals:
        return "text"

    def share(rx):
        return sum(1 for v in vals if re.search(rx, v)) / len(vals)

    if share(r"^[^@\s]+@[^@\s]+\.[^@\s]+$") > .6:
        return "email"
    if share(r"^〒?\d{3}-?\d{4}$") > .6:
        return "postal"
    if share(r"^\+?[\d\-() ]{10,16}$") > .6:
        return "phone"
    if share(r"(株式会社|有限会社|\(株\)|合同会社)") > .3:
        return "company"
    return "text"


def similarity(a: str, b: str) -> float:
    """文字の2つ組(bigram)の重なり。0〜1"""
    if a == b:
        return 1.0
    if len(a) < 2 or len(b) < 2:
        return 0.0
    from collections import Counter
    A = Counter(a[i:i + 2] for i in range(len(a) - 1))
    B = Counter(b[i:i + 2] for i in range(len(b) - 1))
    inter = sum(min(n, B[g]) for g, n in A.items())
    return 2 * inter / (len(a) - 1 + len(b) - 1)
