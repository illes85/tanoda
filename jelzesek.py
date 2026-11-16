#!/usr/bin/env python3
"""Tanoda – a tanulók „szerintem ez is helyes” jelzéseinek kezelése (admin / admin-Claude számára).
A jelzett válasz NEM számít helyesnek, amíg itt el nem fogadják. Használat (a ~/agentek mappából):
  venv/bin/python tanoda/jelzesek.py lista [mind]        – tömör lista (alapból csak az újak)
  venv/bin/python tanoda/jelzesek.py atnez               – az újak teljes szövege, egyben, átvizsgálásra (Claude-nak)
  venv/bin/python tanoda/jelzesek.py megnez <id>         – egy jelzés minden adata
  venv/bin/python tanoda/jelzesek.py elfogad <id> [megjegyzés]   – elfogad: az alak bekerül a feladat elfogadott válaszai közé
  venv/bin/python tanoda/jelzesek.py elutasit <id> [megjegyzés]  – elutasít (a tanuló a főoldalon értesül)
  venv/bin/python tanoda/jelzesek.py link                – az admin-oldal címe (a token a tanoda/.admin_token fájlban van)
Az adat: tanoda/adat/jelzesek.json. A TANODA_ADAT környezeti változóval külön adatmappa is megadható (teszt)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import szerver as s  # noqa: E402


def sor(j: dict) -> str:
    return f'{j["id"]} [{j["allapot"]}] {j["cel_cim"][:24]} / {j["lecke_cim"][:28]}: „{j["felhasznalo"]}” (várt: {j["helyes"]}) {j.get("db", 1)}×'


def main() -> None:
    a = sys.argv[1:] or ["lista"]
    cmd = a[0]
    lista = s.jelzesek()
    if cmd == "lista":
        sz = [j for j in lista if a[1:] == ["mind"] or j["allapot"] == "uj"]
        print("\n".join(sor(j) for j in sz) or "Nincs tétel.")
    elif cmd == "atnez":
        uj = [j for j in lista if j["allapot"] == "uj"]
        print(f"{len(uj)} új jelzés. Mindegyiknél döntsd el: a tanuló válasza az adott kérdésre ugyanúgy, értelmében helyes-e (akkor elfogad), vagy tévedés (akkor elutasit).\n")
        for j in uj:
            print(f'--- {j["id"]} | {j["cel_cim"]} / {j["lecke_cim"]} | {j["tipus"]}\nKérdés: {j["kerdes"]}\nVárt válasz: {j["helyes"]}\nEddig elfogadott: {", ".join(j["elfogad"]) or "-"}\n'
                  f'A tanuló válasza: {j["felhasznalo"]}\nMagyarázat: {j.get("magyarazat", "")}\n')
    elif cmd == "megnez" and len(a) > 1:
        j = next((x for x in lista if x["id"] == a[1]), None)
        print(json.dumps(j, ensure_ascii=False, indent=1) if j else "Nincs ilyen jelzés.")
    elif cmd in ("elfogad", "elutasit") and len(a) > 1:
        j = s.jelzes_dontes(a[1], cmd, " ".join(a[2:]))
        print("Kész:", sor(j))
    elif cmd == "link":
        print("Az admin-oldal: https://kisfonok.tail4d6ec9.ts.net:8443/admin?k=<a tanoda/.admin_token tartalma>")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
