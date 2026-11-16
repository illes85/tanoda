#!/usr/bin/env python3
"""Tanoda – profilok kezelése (admin). Használat (a ~/agentek mappából):
  venv/bin/python tanoda/felhasznalok.py lista                       – a profilok és korlátaik
  venv/bin/python tanoda/felhasznalok.py vip <az> [max_tanfolyam] [napi_generalas]   – VIP: több tanfolyam (alap 5), opcionálisan több napi AI-generálás
  venv/bin/python tanoda/felhasznalok.py alap <az>                   – vissza a vendég-korlátokra
A profil-azonosítót a `lista` mutatja. TANODA_ADAT-tal külön adatmappa adható (teszt)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import szerver as s  # noqa: E402


def main() -> None:
    a = sys.argv[1:] or ["lista"]
    if a[0] == "lista":
        for p in s.felh_lista():
            m = s.felh_meta(p["az"]) or {}
            mc, nap = s.felh_korlat(p["az"])
            print(f'{p["az"]:14} {p["nev"]:22} {"ADMIN" if p["az"] == s.ADMIN_FELH else ("VIP  " if m.get("vip") else "vendég")}  tanfolyam≤{"∞" if p["az"] == s.ADMIN_FELH else mc}  napi AI≤{"∞" if p["az"] == s.ADMIN_FELH else nap}  {"🔒PIN" if p["pin"] else ""}')
    elif a[0] in ("vip", "alap") and len(a) > 1:
        m = s.felh_meta(a[1])
        if not m:
            sys.exit("Nincs ilyen profil.")
        if a[0] == "vip":
            m["vip"], m["max_cel"] = True, int(a[2]) if len(a) > 2 else 5
            if len(a) > 3:
                m["napi"] = int(a[3])
        else:
            for k in ("vip", "max_cel", "napi"):
                m.pop(k, None)
        s.meta_ment(a[1], m)
        print("Kész:", json.dumps({k: m.get(k) for k in ("vip", "max_cel", "napi")}, ensure_ascii=False))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
