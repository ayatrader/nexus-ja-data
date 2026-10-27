"""名寄せ(重複の判定とまとめ)。名寄せ赤ペン p004 と同じ考え方。

- ルール(どれか1つに当てはまれば同じ相手): 例 メールが同じ / 電話が同じ / 会社名+担当者が同じ
- 空欄どうしは一致にしない
- 残す行: 日付が新しい → 埋まっている項目が多い → 後ろの行
- 似ている会社名は自動でまとめず review(要確認)に出す
"""
from . import normalize as N

EDITION = "open"          # "open"(公開版・制限なし) / "free"(行数制限つき。将来の有料サービス用に残す)
FREE_LIMIT = 300          # EDITION="free" のときに名寄せできる行数


def normalize_table(headers, rows, types):
    out, changes = [], []
    for ri, r in enumerate(rows):
        nr = []
        for ci, v in enumerate(r):
            v = "" if v is None else str(v)
            nv = N.norm(types[ci], v)
            if nv != v:
                changes.append({"row": ri, "column": headers[ci], "before": v, "after": nv})
            nr.append(nv)
        out.append(nr)
    return out, changes


def suggest_rules(types):
    idx = lambda t: [i for i, x in enumerate(types) if x == t]
    co, pe, ad, ka = (idx(t)[:1] for t in ("company", "person", "address", "kana"))
    rules = [[i] for i in idx("email")] + [[i] for i in idx("phone")]
    if co and pe:
        rules.append(co + pe)
    if co and ad:
        rules.append(co + ad)
    if pe and ad:
        rules.append(pe + ad)
    if co and not pe and not ad:
        rules.append(co)
    return rules


def dedupe(headers, rows, types, rules=None, fill=True, fuzzy=True, threshold=0.72, links=(), ignore=()):
    if EDITION == "free" and len(rows) > FREE_LIMIT:
        raise ValueError(f"この版で名寄せできるのは{FREE_LIMIT}行までです(今回 {len(rows)}行)。")
    rules = suggest_rules(types) if rules is None else rules
    n = len(rows)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    reasons = [set() for _ in range(n)]
    keyof = lambda ri, ci: N.key(types[ci], rows[ri][ci])
    label = lambda cols: "+".join(headers[c] for c in cols)
    for cols in rules:
        seen = {}
        for i in range(n):
            parts = [keyof(i, c) for c in cols]
            if any(not p for p in parts):
                continue
            k = "\u0001".join(parts)
            if k in seen:
                j = seen[k]
                a, b = find(i), find(j)
                if a != b:
                    parent[a] = b
                reasons[i].add(label(cols))
                reasons[j].add(label(cols))
            else:
                seen[k] = i
    for i, j in links:
        if i < n and j < n:
            a, b = find(i), find(j)
            if a != b:
                parent[a] = b
            reasons[i].add("手動")
            reasons[j].add("手動")

    groups_map = {}
    for i in range(n):
        groups_map.setdefault(find(i), []).append(i)
    date_cols = [i for i, t in enumerate(types) if t == "date"]
    import re
    latest = lambda r: max([rows[r][c] for c in date_cols if re.fullmatch(r"\d{4}-\d{2}-\d{2}", rows[r][c] or "")] or [""])
    filled = lambda r: sum(1 for ci, v in enumerate(rows[r]) if types[ci] != "keep" and str(v).strip())
    groups = []
    for members in groups_map.values():
        rep = sorted(members, key=lambda r: (latest(r), filled(r), r), reverse=True)[0]
        why = sorted(set().union(*(reasons[m] for m in members)))
        groups.append({"members": sorted(members), "representative": rep, "matched_by": why})
    groups.sort(key=lambda g: g["members"][0])
    for gi, g in enumerate(groups, 1):
        g["id"] = gi

    merged = []
    for g in groups:
        row = list(rows[g["representative"]])
        notes = []
        for ci in range(len(row)):
            if types[ci] == "keep":
                continue
            vals = list(dict.fromkeys(rows[m][ci] for m in g["members"] if str(rows[m][ci]).strip()))
            keys = {keyof(m, ci) for m in g["members"]} - {""}
            if fill:
                if not str(row[ci]).strip() and vals:
                    row[ci] = vals[0]
                elif len(keys) == 1 and len(vals) > 1 and types[ci] != "date":
                    row[ci] = max([row[ci]] + vals, key=lambda v: len(str(v)))
            if len(g["members"]) > 1 and len(keys) > 1 and types[ci] != "date":
                notes.append(f"{headers[ci]}が{len(keys)}種類")
        merged.append({"record": dict(zip(headers, row)), "merged_count": len(g["members"]),
                       "source_rows": g["members"], "notes": notes})

    review = []
    if fuzzy:
        for ci in [i for i, t in enumerate(types) if t == "company"]:
            reps = [(g, keyof(g["representative"], ci)) for g in groups]
            blocks = {}
            for g, k in reps:
                if len(k) >= 3:
                    blocks.setdefault(k[:2], []).append((g, k))
            for lst in blocks.values():
                if len(lst) > 400:
                    continue
                for a in range(len(lst)):
                    for b in range(a + 1, len(lst)):
                        (ga, ka), (gb, kb) = lst[a], lst[b]
                        if ka == kb:
                            continue
                        pair = tuple(sorted((ga["representative"], gb["representative"])))
                        if pair in {tuple(sorted(x)) for x in ignore}:
                            continue
                        sc = N.similarity(ka, kb)
                        if sc >= threshold:
                            review.append({"row_a": pair[0], "row_b": pair[1], "column": headers[ci],
                                           "value_a": rows[pair[0]][ci], "value_b": rows[pair[1]][ci],
                                           "similarity": round(sc, 2)})
        review.sort(key=lambda x: -x["similarity"])

    return {"groups": groups, "merged": merged, "review": review,
            "summary": {"rows": n, "after": len(groups), "removed": n - len(groups),
                        "duplicate_groups": sum(1 for g in groups if len(g["members"]) > 1),
                        "review_pairs": len(review)}}
