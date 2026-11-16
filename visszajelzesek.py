#!/usr/bin/env python3
"""Tanoda – a tanulók visszajelzései (hiba / ötlet / nem érthető / tetszik) – admin és admin-Claude számára.
Használat (a ~/agentek mappából):
  venv/bin/python tanoda/visszajelzesek.py lista [mind]                  – tömör lista (alapból az újak és a folyamatban lévők)
  venv/bin/python tanoda/visszajelzesek.py atnez                         – az újak teljes szövege + környezete egyben, átvizsgálásra
  venv/bin/python tanoda/visszajelzesek.py megnez <id>                   – egy visszajelzés minden adata
  venv/bin/python tanoda/visszajelzesek.py allapot <id> <uj|folyamatban|kesz|elvetve> [megjegyzés a tanulónak]
  venv/bin/python tanoda/visszajelzesek.py tanulsag "<szabály>" [téma-kulcsszó]   – tartós szabály a lecke-generálásnak (minden új leckébe bekerül; a téma-kulcsszóval csak az ahhoz illő tanfolyamokba)
  venv/bin/python tanoda/visszajelzesek.py tanulsagok                    – a rögzített szabályok listája
Ha a lezáráshoz (kesz / elvetve) megjegyzés is tartozik, a tanuló a főoldalon értesül róla.
Böngészőből: https://kisfonok.tail4d6ec9.ts.net:8443/admin?k=<token>&oldal=vissza (a token: tanoda/.admin_token).
Az adat: tanoda/adat/visszajelzesek.json (TANODA_ADAT-tal külön adatmappa adható)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import szerver as s  # noqa: E402


def sor(x: dict) -> str:
    return f'{x["id"]} [{x["allapot"]}] {x["kategoria"]} {x["user"]}: {x["szoveg"][:90].replace(chr(10), " ")}'


def main() -> None:
    a = sys.argv[1:] or ["lista"]
    lista = s.visszajelzesek()
    if a[0] == "lista":
        sz = [x for x in lista if a[1:] == ["mind"] or x["allapot"] in ("uj", "folyamatban")]
        print("\n".join(sor(x) for x in sz) or "Nincs tétel.")
    elif a[0] == "atnez":
        uj = [x for x in lista if x["allapot"] == "uj"]
        print(f"{len(uj)} új visszajelzés. Mindegyiknél: mi a gond/ötlet, mit lehet vele kezdeni (javítás, fejlesztés, magyarázat), és állítsd az állapotát.\n")
        for x in uj:
            print(f'--- {x["id"]} | {x["kategoria"]} | {x["user"]} | {x["ido"]}\n{x["szoveg"]}\nKörnyezet: ' + "; ".join(f"{k}={v}" for k, v in x.get("kontextus", {}).items()) + "\n")
    elif a[0] == "megnez" and len(a) > 1:
        x = next((y for y in lista if y["id"] == a[1]), None)
        print(json.dumps(x, ensure_ascii=False, indent=1) if x else "Nincs ilyen visszajelzés.")
    elif a[0] == "allapot" and len(a) > 2:
        print("Kész:", sor(s.visszajelzes_allapot(a[1], a[2], " ".join(a[3:]))))
    elif a[0] == "tanulsag" and len(a) > 1:
        l = s.olvas_g("tanulsagok.json", [])
        l.append({"szabaly": a[1], "tema": a[2] if len(a) > 2 else "", "ido": s.datetime.now().isoformat(timespec="seconds")})
        s.ir_g("tanulsagok.json", l)
        print(f"Rögzítve ({len(l)} szabály).")
    elif a[0] == "tanulsagok":
        for i, x in enumerate(s.olvas_g("tanulsagok.json", []), 1):
            print(f'{i}. [{x.get("tema") or "minden"}] {x["szabaly"]}')
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
