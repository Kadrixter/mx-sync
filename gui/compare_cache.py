"""Porównania bibliotek liczone tylko wtedy, gdy coś się zmieniło (moja albo jego biblioteka)."""
from core.compare import Comparison, missing_from_all


class CompareCache:
    def __init__(self, node):
        self.node = node
        self._cache = {}            # id gracza -> (klucz wersji, Comparison)
        self._all = (None, [])

    def get(self, player):
        if not player.mods:
            return None
        key = (self.node.library.rev, player.rev)
        hit = self._cache.get(player.id)
        if hit and hit[0] == key:
            return hit[1]
        c = Comparison(self.node.library.snapshot(), player.mods)
        self._cache[player.id] = (key, c)
        return c

    def missing_all(self):
        """[(mod, ilu graczy ma, inna_wersja)] – brakujące od wszystkich graczy online."""
        online = [p for p in self.node.players.online() if p.mods]
        key = (self.node.library.rev, tuple(sorted((p.id, p.rev) for p in online)))
        if self._all[0] != key:
            self._all = (key, missing_from_all(self.node.library.snapshot(), online))
        return self._all[1]

    def holders_count(self):
        """{infohash: ilu graczy online ma tę wersję} – do kolumny „ma X graczy”."""
        counts = {}
        for p in self.node.players.online():
            for m in p.mods.values():
                counts[m.ih] = counts.get(m.ih, 0) + 1
        return counts
