# Tanoda

AI-támogatott, személyre szabott tanuló-webapp (angol, sakk, bármilyen téma): terv, beosztás, játékos gyakorlatok, felolvasás, kabala.
Python (csak standard könyvtár) + egyetlen oldalas webes felület; az AI-t a `claude -p` parancs adja.

- `szerver.py` – a szerver (`python szerver.py`, alapból a 8090-es porton)
- `web/` – a felület (`index.html`) és a 3D kabala (`maskot3d.js`, forrása: `maskot/`, építés: `maskot/build.sh`)
- `sakk.py` – kóddal számolt sakk-tények a feladatok ellenőrzéséhez
- `hangkeszito.py`, `hangcsomag.py` – felolvasás (piper) és nyelvi hangcsomagok
- `visszajelzesek.py`, `jelzesek.py`, `felhasznalok.py` – admin-eszközök (visszajelzések, jelzések, profilok)

A felhasználói adat (`adat/`) szándékosan NINCS a tárolóban. Teszteléshez: `TANODA_ADAT=/tmp/teszt TANODA_PORT=8099 python szerver.py`.
