"""Porównanie mojej biblioteki z biblioteką innego gracza (i ze wszystkimi naraz)."""
from core.mods import KIND_ORDER


class Comparison:
    """same – identyczne mody; missing – ma on, nie mam ja; different – ten sam mod, inna wersja;
    only_mine – mam tylko ja. Listy zawierają Mod gracza (missing/different/same) albo mój (only_mine)."""

    def __init__(self, mine, theirs):
        self.same, self.missing, self.different, self.only_mine = [], [], [], []
        for key, m in theirs.items():
            my = mine.get(key)
            if my is None:
                self.missing.append(m)
            elif my.ih == m.ih:
                self.same.append(m)
            else:
                self.different.append(m)
        self.only_mine = [m for k, m in mine.items() if k not in theirs]
        for lst in (self.same, self.missing, self.different, self.only_mine):
            lst.sort(key=sort_key)
        union = len(self.same) + len(self.missing) + len(self.different) + len(self.only_mine)
        self.percent = round(100 * len(self.same) / union) if union else 100
        self.missing_size = sum(m.size for m in self.missing)
        self.different_size = sum(m.size for m in self.different)


def sort_key(m):
    return KIND_ORDER.get(m.kind, 99), m.name.lower()


def missing_from_all(mine, players):
    """Mody, które ma ktokolwiek online, a ja nie (albo mam inną wersję).

    -> [(mod, ilu graczy ma tę wersję, różna_wersja)] – przy kilku wersjach tego samego modu
    wybierana jest najpopularniejsza.
    """
    by_key = {}
    for p in players:
        for key, m in p.mods.items():
            my = mine.get(key)
            if my is not None and my.ih == m.ih:
                continue
            versions = by_key.setdefault(key, {})
            if m.ih in versions:
                versions[m.ih][1] += 1
            else:
                versions[m.ih] = [m, 1]
    out = []
    for key, versions in by_key.items():
        m, n = max(versions.values(), key=lambda v: v[1])
        out.append((m, n, key in mine))
    out.sort(key=lambda x: sort_key(x[0]))
    return out


def holders(ih, players):
    """Gracze online, którzy mają dokładnie tę wersję modu."""
    return [p for p in players if any(m.ih == ih for m in p.mods.values())]


def conflicts(mine, players, ignored=None):
    """Mody, które mam pod tą samą nazwą co inni gracze, ale z inną zawartością.

    -> [(mój Mod, ich Mod (najpopularniejsza inna wersja), ilu graczy ma tę wersję, pominięty)]
    """
    ignored = ignored or {}
    by_key = {}
    for p in players:
        for key, m in p.mods.items():
            my = mine.get(key)
            if my is None or my.ih == m.ih:
                continue
            versions = by_key.setdefault(key, {})
            if m.ih in versions:
                versions[m.ih][1] += 1
            else:
                versions[m.ih] = [m, 1]
    out = []
    for key, versions in by_key.items():
        m, n = max(versions.values(), key=lambda v: v[1])
        out.append((mine[key], m, n, ignored.get(key) == m.ih))
    out.sort(key=lambda x: sort_key(x[0]))
    return out
