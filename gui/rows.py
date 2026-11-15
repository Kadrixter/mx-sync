"""Budowanie wierszy listy modów: grupy (foldery z paczkami) na górze, pod nimi wszystkie mody
w sekcjach według rodzaju. Wspólne dla porównania z graczem, brakujących modów i biblioteki."""
from core.mods import (KIND_GROUPS, KIND_PLURAL, group_parents, kind_in, matches, mod_dir, mod_group,
                       mod_subtitle, search_text)
from utils.fmt import fmt_size

_TEXT = {}                      # klucz modu -> tekst do wyszukiwania (liczony raz)


def _text(key):
    t = _TEXT.get(key)
    if t is None:
        t = _TEXT[key] = search_text(key)
    return t


def filter_mods(mods, query="", kind="", min_holders=0, holders=None):
    """Mody pasujące do wyszukiwania, rodzaju i minimalnej liczby graczy (holders: ih -> ilu ma)."""
    out = []
    for m in mods:
        if kind and not kind_in(m.kind, kind):
            continue
        if query and not matches(_text(m.key), query):
            continue
        if min_holders > 1 and holders is not None and holders.get(m.ih, 0) < min_holders:
            continue
        out.append(m)
    return out


def build_rows(mods, row_fn, checkable=True):
    """row_fn(mod) -> dict wiersza (bez id/kind/name/path/size – te są dokładane tutaj)."""
    rows = []
    groups = {}
    for m in mods:
        g = mod_group(m.key)
        for gid in group_parents(g) if g else ():
            groups.setdefault(gid, []).append(m)
    if groups:
        rows.append({"header": True, "kind": "Inne", "selectable": False,
                     "label": f"Grupy (foldery z mapami i modami)  ·  {len(groups)}"})
        for gid in sorted(groups, key=lambda g: g.lower()):
            members = groups[gid]
            rows.append({"group": True, "id": "g:" + gid, "kind": members[0].kind,
                         "name": gid.rsplit("/", 1)[-1], "path": mod_dir(gid) or "mods",
                         "count": len(members), "size": sum(m.size for m in members),
                         "members": [m.ih for m in members]})
    by_kind = {}
    for m in mods:
        by_kind.setdefault(m.kind, []).append(m)
    for kind, _ in KIND_GROUPS:
        g = sorted(by_kind.get(kind, []), key=lambda m: m.name.lower())
        if not g:
            continue
        rows.append({"header": True, "kind": kind, "selectable": checkable,
                     "label": f"{KIND_PLURAL[kind]}  ·  {len(g)}  ·  {fmt_size(sum(m.size for m in g))}"})
        for m in g:
            r = {"id": m.ih, "kind": m.kind, "name": m.name, "path": mod_subtitle(m.key, m.kind),
                 "size": m.size}
            r.update(row_fn(m))
            rows.append(r)
    return rows


def players_text(n):
    if n <= 0:
        return "nikt online"
    return "1 gracz" if n == 1 else f"{n} graczy"
