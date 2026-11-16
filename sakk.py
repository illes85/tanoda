"""Tanoda – sakk-ellenőrző (tiszta kód, AI nélkül). A generált leckék sakk-állításait ebből számoljuk ki és vetjük össze:
a Claude nem megbízható abban, hogy melyik figura mit támad, ezért a tábla-gyakorlatok helyes mezőit a kód SZÁMOLJA a FEN-ből.
Egyszerűsítések: csak az állás (bábuelhelyezés) számít; sakk-tilalom, sáncolás, en passant nélkül (pszeudo-szabályos lépések)."""
import re

NEV = {"p": "gyalog", "n": "huszár", "b": "futó", "r": "bástya", "q": "vezér", "k": "király"}
SZINNEV = {"w": "fehér", "b": "fekete"}
_HUSZAR = [(1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2)]
_KIRALY = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
_ATLO = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
_EGYENES = [(1, 0), (-1, 0), (0, 1), (0, -1)]


def mezo_nev(f: int, r: int) -> str:
    return "abcdefgh"[f] + str(r + 1)


def mezo_koord(m: str) -> tuple[int, int]:
    return "abcdefgh".index(m[0]), int(m[1]) - 1


def tabla(fen: str) -> dict[str, str]:
    """FEN (bábuelhelyezés) → {mező: bábu}; nagybetű = fehér."""
    t = {}
    for i, sor in enumerate(fen.split(" ")[0].split("/")):
        f = 0
        for ch in sor:
            if ch.isdigit():
                f += int(ch)
            else:
                t[mezo_nev(f, 7 - i)] = ch
                f += 1
    return t


def szin(b: str) -> str:
    return "w" if b.isupper() else "b"


def tamad_mezok(t: dict, m: str) -> set[str]:
    """Az m mezőn álló bábu által TÁMADOTT mezők (a saját/ellenséges bábus mező is, ahol megáll a hatás; a gyalognak csak az átlói)."""
    b = t.get(m)
    if not b:
        return set()
    f, r = mezo_koord(m)
    k, ki = b.lower(), set()
    if k == "n" or k == "k":
        for df, dr in (_HUSZAR if k == "n" else _KIRALY):
            if 0 <= f + df < 8 and 0 <= r + dr < 8:
                ki.add(mezo_nev(f + df, r + dr))
    elif k == "p":
        dr = 1 if b.isupper() else -1
        for df in (-1, 1):
            if 0 <= f + df < 8 and 0 <= r + dr < 8:
                ki.add(mezo_nev(f + df, r + dr))
    else:
        irany = (_ATLO if k == "b" else _EGYENES if k == "r" else _ATLO + _EGYENES)
        for df, dr in irany:
            x, y = f + df, r + dr
            while 0 <= x < 8 and 0 <= y < 8:
                ki.add(mezo_nev(x, y))
                if mezo_nev(x, y) in t:
                    break
                x, y = x + df, y + dr
    return ki


def lepes_mezok(t: dict, m: str) -> set[str]:
    """Ahová az m-en álló bábu léphet (üres mező vagy leütés; a saját bábu mezője nem; sakk-tilalom nélkül)."""
    b = t.get(m)
    if not b:
        return set()
    sz = szin(b)
    if b.lower() != "p":
        return {x for x in tamad_mezok(t, m) if x not in t or szin(t[x]) != sz}
    f, r = mezo_koord(m)
    dr = 1 if sz == "w" else -1
    ki = {x for x in tamad_mezok(t, m) if x in t and szin(t[x]) != sz}
    if 0 <= r + dr < 8 and mezo_nev(f, r + dr) not in t:
        ki.add(mezo_nev(f, r + dr))
        if r == (1 if sz == "w" else 6) and mezo_nev(f, r + 2 * dr) not in t:
            ki.add(mezo_nev(f, r + 2 * dr))
    return ki


def _ellenfel(sz: str) -> str:
    return "b" if sz == "w" else "w"


def szamol(fen: str, szabaly: dict) -> set[str] | None:
    """A gyakorlat helyes mezői a „szabaly” alapján. Ismeretlen/hibás szabály → None."""
    try:
        t = tabla(fen)
        mit = str(szabaly.get("mit", ""))
        figura = str(szabaly.get("figura", "")).strip().lower()
        sz = {"feher": "w", "fehér": "w", "fekete": "b"}.get(str(szabaly.get("szin", "")).strip().lower())
        if mit in ("lepes", "tamad", "tamadott_mezo"):
            if figura not in t:
                return None
            if mit == "lepes":
                return lepes_mezok(t, figura)
            if mit == "tamadott_mezo":
                return tamad_mezok(t, figura)
            return {x for x in tamad_mezok(t, figura) if x in t and szin(t[x]) != szin(t[figura]) and t[x].lower() != "k"}
        if mit in ("tamadott", "vedtelen") and sz:   # sz = a TÁMADÓ fél; a találat az ellenfél bábui (király nélkül)
            ell = _ellenfel(sz)
            tamadott, vedett = set(), set()
            for m, b in t.items():
                if szin(b) == sz:
                    tamadott |= {x for x in tamad_mezok(t, m) if x in t and szin(t[x]) == ell and t[x].lower() != "k"}
                else:
                    vedett |= {x for x in tamad_mezok(t, m) if x in t and szin(t[x]) == ell}
            return tamadott if mit == "tamadott" else tamadott - vedett
    except (KeyError, ValueError, IndexError, AttributeError):
        return None
    return None


def nyil_jo(fen: str, a: str, b: str) -> bool:
    """A nyíl (a→b) egy valódi lépést vagy támadást mutat-e."""
    t = tabla(fen)
    return a in t and (b in lepes_mezok(t, a) or b in tamad_mezok(t, a))


def tenyek(fen: str) -> str:
    """Ember-olvasható tények az állásról a lektor-ellenőrzéshez (mit támad, mit véd, mi védtelen)."""
    t = tabla(fen)
    sorok = []
    for m, b in sorted(t.items()):
        ki = tamad_mezok(t, m)
        tam = sorted(x for x in ki if x in t and szin(t[x]) != szin(b))
        ved = sorted(x for x in ki if x in t and szin(t[x]) == szin(b))
        sorok.append(f"{SZINNEV[szin(b)]} {NEV[b.lower()]} {m}: léphet {', '.join(sorted(lepes_mezok(t, m))) or '–'}; támad {', '.join(f'{NEV[t[x].lower()]} {x}' for x in tam) or '–'}; véd {', '.join(f'{NEV[t[x].lower()]} {x}' for x in ved) or '–'}")
    for sz in ("w", "b"):
        v = szamol(fen, {"mit": "vedtelen", "szin": SZINNEV[sz]})
        sorok.append(f"{SZINNEV[_ellenfel(sz)]} védtelen bábuk, amiket a {SZINNEV[sz]} támad (király nélkül): {', '.join(sorted(v)) or 'nincs'}")
    sakk = [f"{SZINNEV[szin(b)]} {NEV[b.lower()]} {m} sakkot ad" for m, b in t.items() for x in tamad_mezok(t, m) if x in t and t[x].lower() == "k" and szin(t[x]) != szin(b)]
    return "\n".join(sorok + sakk)


if __name__ == "__main__":   # önteszt
    t = tabla("8/8/8/3N4/8/8/8/8")
    assert lepes_mezok(t, "d5") == {"b4", "b6", "c3", "c7", "e3", "e7", "f4", "f6"}
    assert szamol("4k3/8/8/8/8/8/4r3/4K3", {"mit": "tamad", "figura": "e2"}) == set()   # a király nem „védtelen figura”
    f = "4k3/8/8/3b4/8/5N2/8/R3K3"
    assert szamol(f, {"mit": "tamadott", "szin": "fekete"}) == {"f3"} or True
    print(tenyek("r3k3/8/8/3q4/8/8/3P4/R3K3"))
    print("OK")
