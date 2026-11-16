#!/usr/bin/env python3
"""Tanoda – személyre szabott, játékos tanulóapp (Illés, 2026-11-15).

Illés beírja, mit akar megtanulni; a Claude tervet, beosztást és anyaglistát készít, majd lecke-ről lecke-re interaktív
gyakorlatokat. Amit kód is el tud dönteni (ismétlés-ütemezés, XP, sorozat, szint, kitűzők, beosztás), azt a kód számolja –
a Claude csak a tartalmat írja (tokentakarékosság). Csak a gépről / a Tailscale-hálózatból érhető el (127.0.0.1 + tailscale serve).

Futtatás: tanoda.service (felhasználói systemd) → http://127.0.0.1:8090
"""
import difflib
import hangcsomag
import sakk
import admin_dash
import hashlib
import hmac
import socket
import unicodedata
from http.cookies import SimpleCookie
import html as htmlmod
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ITT = Path(__file__).resolve().parent
sys.path.insert(0, str(ITT.parent))
sys.path.insert(0, str(ITT))   # önálló tanoda-tárolóban a hangkeszito.py a gyökérben van
ADAT = Path(os.environ["TANODA_ADAT"]) if os.environ.get("TANODA_ADAT") else ITT / "adat"  # a TANODA_ADAT csak teszthez
TTS_MAPPA = ITT / ".tts"
WEB = ITT / "web"
MUNKA_MAPPA = Path("/tmp/tanoda_munka")  # a Claude innen fut, hogy ne töltse be a ~/agentek CLAUDE.md-jét
PORT = int(os.environ.get("TANODA_PORT", "8090"))
MODELL = os.environ.get("TANODA_MODELL", "claude-sonnet-5-5")
MODELL_OLCSO = os.environ.get("TANODA_MODELL_OLCSO", "claude-haiku-5-5")
FELH_MAPPA = ADAT / "felhasznalok"
BIND = os.environ.get("TANODA_BIND", "0.0.0.0")   # a házi hálózaton is elérhető; a tailscale serve továbbra is a 127.0.0.1-re mutat
ADMIN_FELH = "illes"                                # az admin/tulajdonos profilja (ennek nincs vendég-keret)
VENDEG_CEL_MAX = int(os.environ.get("TANODA_VENDEG_CEL_MAX", "2"))
VENDEG_NAPI = int(os.environ.get("TANODA_VENDEG_NAPI", "12"))   # vendég: napi AI-generálások (terv/lecke/anyag/bővítés)
for m in (ADAT, FELH_MAPPA, TTS_MAPPA, MUNKA_MAPPA):
    m.mkdir(exist_ok=True)

IRAS_ZAR = threading.Lock()      # fájlírás
JELZES_ZAR = threading.Lock()    # a jelzés-lista olvasás-módosítás-írása (az ir() közben az IRAS_ZAR-t veszi)
CLAUDE_ZAR = threading.Lock()    # egyszerre egy Claude-hívás (4 GB RAM)
TTS_ZAR = threading.Lock()
WHISPER_ZAR = threading.Lock()
WHISPER = ITT.parent / "whisper" / "build" / "bin" / "whisper-cli"
WHISPER_MODELL = ITT.parent / "whisper" / "models" / f"ggml-{os.environ.get('WHISPER_MODELL', 'small-q5_1')}.bin"
MUNKAK: dict[str, dict] = {}     # háttérmunkák állapota (memóriában)

APP_URL = os.environ.get("TANODA_URL", "https://kisfonok.tail4d6ec9.ts.net:8443")

DOBOZ_NAP = [0, 1, 2, 4, 8, 16, 32]   # ismétlési dobozok (nap)
HET_NAPJAI = {1: [0], 2: [0, 3], 3: [0, 2, 4], 4: [0, 1, 3, 4], 5: [0, 1, 2, 3, 4], 6: [0, 1, 2, 3, 4, 5], 7: [0, 1, 2, 3, 4, 5, 6]}

KITUZOK = {
    "elso": ("🌱", "Első lecke", "Végigvittél egy leckét"),
    "s3": ("🔥", "3 napos sorozat", "3 napot egymás után tanultál"),
    "s7": ("🔥", "Heti láng", "7 napos sorozat"),
    "s14": ("🔥", "Két hét", "14 napos sorozat"),
    "s30": ("🏆", "Havi bajnok", "30 napos sorozat"),
    "tokeletes": ("💎", "Hibátlan", "Egy lecke 100%-ra"),
    "k25": ("🃏", "25 kártya", "25 kártyát tanultál meg"),
    "k100": ("🃏", "100 kártya", "100 kártyát tanultál meg"),
    "szint5": ("⭐", "5. szint", "Elérted az 5. szintet"),
    "cel1": ("🎓", "Kész kurzus", "Végigvittél egy teljes tanulási tervet"),
    "visszatero": ("💪", "Visszatérő", "Kiesés után visszajöttél tanulni"),
}


# ---------------------------------------------------------------------------------------------------- tár
_T = threading.local()   # a kérést / háttérmunkát kiszolgáló szál felhasználója


def aktualis() -> str:
    s = getattr(_T, "slug", None)
    if not s:
        raise RuntimeError("nincs bejelentkezett felhasználó ebben a szálban")
    return s


class felhasznalo:
    """with felhasznalo("anna"): ... – az adott felhasználó adatmappájában dolgozunk (kérés, háttérmunka, admin)."""
    def __init__(self, slug: str):
        self.slug = slug

    def __enter__(self):
        self.regi = getattr(_T, "slug", None)
        _T.slug = self.slug
        return self

    def __exit__(self, *a):
        _T.slug = self.regi


def felh_dir(slug: str | None = None) -> Path:
    return FELH_MAPPA / (slug or aktualis())


def olvas(nev: str, alap):
    f = felh_dir() / nev
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return alap


def ir(nev: str, adat) -> None:
    f = felh_dir() / nev
    with IRAS_ZAR:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(f.suffix + ".tmp")
        tmp.write_text(json.dumps(adat, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(f)


def olvas_g(nev: str, alap):
    """Közös (nem felhasználónkénti) fájl a gyökérmappában."""
    try:
        return json.loads((ADAT / nev).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return alap


def ir_g(nev: str, adat) -> None:
    f = ADAT / nev
    with IRAS_ZAR:
        tmp = f.with_suffix(f.suffix + ".tmp")
        tmp.write_text(json.dumps(adat, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(f)


# ---------------------------------------------------------------------------------------------------- profilok (nincs jelszó: házi hálózat; opcionális PIN)
SLUG_RE = re.compile(r"[a-z0-9-]{2,24}")
EMOJIK = ["🧑", "👩", "👨", "🧒", "👧", "👦", "🧓", "🦊", "🐼", "🐯", "🦉", "🐸", "🚀", "🌟", "🎸", "📚"]
PIN_HIBAK: dict[str, list] = {}   # ip → [hibák száma, utolsó hiba ideje]


def titok() -> bytes:
    f = ADAT / ".titok"
    try:
        v = f.read_text().strip()
        if len(v) >= 32:
            return v.encode()
    except OSError:
        pass
    v = uuid.uuid4().hex + uuid.uuid4().hex
    f.write_text(v)
    os.chmod(f, 0o600)
    return v.encode()


def suti_alair(slug: str) -> str:
    return slug + "." + hmac.new(titok(), slug.encode(), hashlib.sha256).hexdigest()[:24]


def suti_slug(ertek: str) -> str | None:
    slug, _, al = (ertek or "").partition(".")
    if SLUG_RE.fullmatch(slug) and hmac.compare_digest(al, suti_alair(slug).partition(".")[2]):
        return slug
    return None


def felh_meta(slug: str) -> dict | None:
    if not SLUG_RE.fullmatch(slug or ""):
        return None
    try:
        return json.loads((felh_dir(slug) / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def felh_lista() -> list[dict]:
    out = []
    for d in sorted(FELH_MAPPA.iterdir()) if FELH_MAPPA.exists() else []:
        m = felh_meta(d.name)
        if m:
            out.append({"az": d.name, "nev": m["nev"], "emoji": m.get("emoji", "🧑"), "pin": bool(m.get("pin_hash"))})
    return out


def pin_hash(pin: str, so: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), so.encode(), 80000).hex()


def pin_norm(pin: str) -> str:
    """Számok előtti nullák nélkül (035 → 35), hogy a gépelt és a mentett PIN ugyanaz legyen."""
    return str(pin).lstrip("0") or ("0" if str(pin) else "")


def pin_jo(meta: dict, pin: str) -> bool:
    if not meta.get("pin_hash"):
        return True
    pin = str(pin)
    # a régebben (nullákkal) mentett PIN-ek is működnek
    jel = {pin, pin_norm(pin)}
    if pin.isdigit():   # a régi, nullával kezdődő PIN-t a kliens már levágva küldi: a kitöltött változatokat is próbáljuk
        jel |= {pin_norm(pin).zfill(n) for n in range(4, 9)}
    return any(hmac.compare_digest(pin_hash(v, meta["so"]), meta["pin_hash"]) for v in jel)


def meta_ment(slug: str, meta: dict) -> None:
    d = felh_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    with IRAS_ZAR:
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def felh_letrehoz(nev: str, emoji: str, pin: str) -> str:
    nev = " ".join(str(nev).split())[:24]
    if len(nev) < 2:
        raise ValueError("Írj be legalább 2 betűs nevet.")
    if len(felh_lista()) >= 12:
        raise ValueError("Elértük a profilok maximális számát (12).")
    alap = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", nev).encode("ascii", "ignore").decode().lower()).strip("-")[:20] or "u" + uuid.uuid4().hex[:4]
    slug, i = alap if len(alap) >= 2 else alap + "x", 2
    while (felh_dir(slug) / "meta.json").exists() or slug == ADMIN_FELH:   # az „illes” az adminé (a migráció hozza létre)
        slug, i = f"{alap}-{i}", i + 1
    meta = {"nev": nev, "emoji": emoji if emoji in EMOJIK else "🧑", "letrehozva": ma().isoformat()}
    if pin:
        if not re.fullmatch(r"\d{4,8}", pin):
            raise ValueError("A PIN 4-8 számjegy legyen.")
        meta["so"] = uuid.uuid4().hex
        meta["pin_hash"] = pin_hash(pin_norm(pin), meta["so"])
    meta_ment(slug, meta)
    return slug


def migral() -> None:
    """Az egyfelhasználós időszak adata (a gyökérmappából) az „illes” profilba kerül. Többször is futtatható."""
    FELH_MAPPA.mkdir(parents=True, exist_ok=True)
    regi = list(ADAT.glob("cel_*.json")) + list(ADAT.glob("cel_*.torolt")) + [ADAT / x for x in ("profil.json", "emlekezteto.json") if (ADAT / x).exists()]
    d = felh_dir(ADMIN_FELH)
    if regi:
        d.mkdir(parents=True, exist_ok=True)
        for f in regi:
            if not (d / f.name).exists():
                f.replace(d / f.name)
    if d.exists() and not (d / "meta.json").exists():
        meta_ment(ADMIN_FELH, {"nev": "Illés", "emoji": "🧑", "letrehozva": ma().isoformat()})


def lan_url() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
    except OSError:
        ip = "127.0.0.1"
    return f"http://{ip}:{PORT}"


class KeretHiba(Exception):
    """A vendég napi AI-kerete elfogyott."""


def felh_korlat(slug: str | None = None) -> tuple[int, int]:
    """(legfeljebb ennyi tanfolyam, napi AI-generálás) – a profil meta.json-jában felülírható (max_cel, napi; VIP-nél)."""
    m = felh_meta(slug or aktualis()) or {}
    return int(m.get("max_cel", VENDEG_CEL_MAX)), int(m.get("napi", VENDEG_NAPI))


def keret_fogyaszt(suly: int = 1) -> None:
    if aktualis() == ADMIN_FELH:
        return
    p = profil()
    k = p["beallitasok"].get("keret") or {}
    if k.get("nap") != ma().isoformat():
        k = {"nap": ma().isoformat(), "db": 0}
    napi = felh_korlat()[1]
    if k["db"] >= napi:
        raise KeretHiba(f"Mára elfogyott a napi keret ({napi} generálás naponta). Holnap folytathatod, a már elkészült leckék addig is játszhatók.")
    k["db"] += suly
    p["beallitasok"]["keret"] = k
    ir("profil.json", p)


def ma() -> date:
    return date.today()


def profil() -> dict:
    p = olvas("profil.json", {})
    p.setdefault("xp", 0)
    p.setdefault("sorozat", 0)
    p.setdefault("utolso_nap", "")
    p.setdefault("fagyasztas", 1)
    p.setdefault("kituzok", [])
    p.setdefault("megtanult_kartya", 0)
    p.setdefault("beallitasok", {})
    p.setdefault("napi", {})  # "2026-11-15": {"xp": n, "leckek": n}
    return p


def szint_adat(xp: int) -> dict:
    """A szinthez szükséges XP: 100 * szint^1.5 (kód számolja)."""
    sz = 1
    while xp >= round(100 * sz ** 1.5):
        xp -= round(100 * sz ** 1.5)
        sz += 1
    kell = round(100 * sz ** 1.5)
    return {"szint": sz, "xp_szinten": xp, "xp_kell": kell}


def hatso_sorozat(p: dict) -> int:
    """A kijelzett sorozat: ha tegnap óta nem tanult, és nincs fagyasztás, nulla."""
    if not p["utolso_nap"]:
        return 0
    kul = (ma() - date.fromisoformat(p["utolso_nap"])).days
    if kul <= 1:
        return p["sorozat"]
    if kul == 2 and p["fagyasztas"] > 0:
        return p["sorozat"]
    return 0


def sorozat_frissit(p: dict) -> bool:
    """Lecke végén hívjuk. True, ha kiesés után tért vissza."""
    mai = ma().isoformat()
    if p["utolso_nap"] == mai:
        return False
    visszatero = False
    if not p["utolso_nap"]:
        p["sorozat"] = 1
    else:
        kul = (ma() - date.fromisoformat(p["utolso_nap"])).days
        if kul == 1:
            p["sorozat"] += 1
        elif kul == 2 and p["fagyasztas"] > 0:
            p["fagyasztas"] -= 1
            p["sorozat"] += 1
        else:
            visszatero = p["sorozat"] >= 1 or kul > 2
            p["sorozat"] = 1
    if p["sorozat"] % 7 == 0 and p["fagyasztas"] < 2:
        p["fagyasztas"] += 1  # minden 7. napért egy fagyasztás (kiesés elleni védelem, max 2)
    p["utolso_nap"] = mai
    return visszatero


def cel_lista() -> list[dict]:
    return [c for c in (olvas(f.name, None) for f in sorted(felh_dir().glob("cel_*.json"))) if c]


def cel_olvas(cid: str) -> dict | None:
    if not re.fullmatch(r"[a-z0-9]{6,12}", cid or ""):
        return None
    return olvas(f"cel_{cid}.json", None)


# ---------------------------------------------------------------------------------------------------- Claude
def claude_json(prompt: str, modell: str, effort: str = "low", eszkozok: str = "", timeout: int = 420) -> dict:
    """Claude-hívás (claude -p), a válaszból kiszedi a JSON-t. Hibánál RuntimeError."""
    with CLAUDE_ZAR:
        p = subprocess.run(["claude", "-p", prompt, "--model", modell, "--effort", effort, "--tools", eszkozok,
                            "--no-session-persistence", "--output-format", "json"],
                           cwd=MUNKA_MAPPA, capture_output=True, timeout=timeout, text=True)
    if p.returncode != 0:
        raise RuntimeError("A Claude hívása nem sikerült: " + (p.stderr or p.stdout)[-300:])
    try:
        valasz = json.loads(p.stdout)
        szoveg = valasz.get("result", "") if isinstance(valasz, dict) else str(valasz)
        usd = valasz.get("total_cost_usd") or valasz.get("cost_usd") or 0
    except ValueError:
        szoveg, usd = p.stdout, 0
    a, b = szoveg.find("{"), szoveg.rfind("}")
    if a < 0 or b <= a:
        raise RuntimeError("A válasz nem JSON: " + szoveg[:200])
    try:
        adat = json.loads(szoveg[a:b + 1])
    except ValueError as e:
        raise RuntimeError(f"Hibás JSON a válaszban: {e}")
    naplo_koltseg(modell, usd)
    return adat


def naplo_koltseg(modell: str, usd) -> None:
    try:
        with (ADAT / "koltseg.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ido": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "modell": modell, "usd": usd, "user": getattr(_T, "slug", "") or "", "munka": getattr(_T, "munka", "") or "egyeb"}) + "\n")
    except OSError:
        pass


def tanulasi_napok(cel: dict) -> list[int]:
    return HET_NAPJAI.get(int(cel.get("nap_hetente", 3)), HET_NAPJAI[3])


def leckek_szama(cel: dict) -> int:
    return max(6, min(40, round(int(cel.get("nap_hetente", 3)) * int(cel.get("hetek", 4)))))


TERV_PROMPT = """Tanulási tervet készítesz egy magyar felhasználónak. Válaszod KIZÁRÓLAG egyetlen JSON-objektum legyen, más szöveg nélkül.

Tanulnivaló: {cim}
Cél: {cel}
Jelenlegi szint: {szint}
Napi idő: {perc} perc, hetente {nap} nap, {hetek} hét.
Megjegyzés: {megjegyzes}

Pontosan {n} leckét tervezz, egymásra épülő sorrendben, modulokba (fejezetekbe) csoportosítva. A leckék legyenek kicsik: egy leckében egy jól körülhatárolt dolgot tanul meg, {perc} perc alatt.
A tervben legyen visszatérő ismétlés és mérőpont is (pl. 4. leckénként összefoglaló/mini-teszt jellegű lecke).

JSON-forma:
{{"osszefoglalo": "2-3 mondat: mi a stratégia és miért", "nyelv": "a tanult IDEGEN nyelv kétbetűs ISO-kódja (en, de, fr, es, it, pt, nl, pl, ru…), vagy üres, ha nem nyelvtanulásról van szó",
 "modszerek": ["rövid módszerek, amiket használunk (pl. ismétlés, szituációs gyakorlás)"],
 "modulok": [{{"cim": "…", "cel": "mit tud majd a modul végén", "leckek": [{{"cim": "…", "tema": "1-2 mondat: mi a lecke tartalma", "kulcsfogalmak": ["…"]}}]}}]}}"""

BOVIT_PROMPT = """Egy meglévő tanulási tervet folytatsz egy magyar felhasználónak: írd meg a KÖVETKEZŐ SZAKASZT. Válaszod KIZÁRÓLAG egyetlen JSON-objektum legyen.

Tanulnivaló: {cim}
Cél: {cel}
Szint az elején: {szint}. Napi idő: {perc} perc, hetente {nap} nap.
Eddig elvégzett leckék (fejezetenként): {eddigi}
Az eddigi eredmények: {eredmenyek}
Gyengén ismert elemek: {gyenge}
A felhasználó kérése a következő szakaszra: {fokusz}

Pontosan {n} új leckét tervezz ({hetek} hétre), modulokba csoportosítva. Ne ismételd az eddigi leckéket, de építs rájuk, és a szintet emeld egy fokkal. Az első lecke legyen rövid ismétlés a gyengén menő részekből (ha vannak), a szakasz végén legyen mérőpont.
Forma: {{"osszefoglalo": "1-2 mondat: mire épül ez a szakasz, és mi a fókusza", "modulok": [{{"cim": "…", "cel": "mit tud majd a modul végén", "leckek": [{{"cim": "…", "tema": "1-2 mondat", "kulcsfogalmak": ["…"]}}]}}]}}"""

ANYAG_PROMPT = """Gyűjts tanulási anyagokat egy magyar felhasználónak. Keress a weben (WebSearch), és csak olyan forrást adj meg, amelyet valóban megtaláltál; URL-t soha ne találj ki.
Válaszod KIZÁRÓLAG egy JSON-objektum.

Tanulnivaló: {cim}
Cél: {cel}
Szint: {szint}
A terv fejezetei: {modulok}

Adj 6-10 forrást, lehetőleg ingyenest és jó minőségűt (magyarul vagy angolul), vegyesen: leírás/olvasnivaló, videó, gyakorló feladat, eszköz. Mindegyikhez: miért hasznos, melyik fejezethez illik.
Forma: {{"anyagok": [{{"cim": "…", "url": "https://…", "tipus": "olvasnivaló|videó|gyakorlás|eszköz|könyv", "miert": "1 mondat", "modul": "a fejezet címe vagy üres"}}]}}"""

ABRA_LEIRAS = """SZEMLÉLTETÉS – NAGYON FONTOS: a lecke legyen látványos és rajzos! A bevezetőhöz adj 2-3 ábrát az „abrak” tömbben, és legalább a gyakorlatok felénél legyen „abra” mező (egy ábra-objektum) – pl. kép alapján kérdezz („Mi látható?”, „Melyik illik az ábrához?”). SAKK ÉS TÁBLAJÁTÉKOK: sakk tanításakor MINDIG a táblán mutasd meg (tabla ábra a bevezetőben, és tabla gyakorlat a feladatok nagy részében). TILOS a tanulót lépéskódokkal (pl. „Nf3”, „e4”, „Bxc6”) magyarázni vagy kérdezni, amíg a tábla koordinátái (a–h oszlopok, 1–8 sorok) külön, ábrával be nem lettek vezetve; addig a lépéseket nyilakkal és kiemelt mezőkkel mutasd, a bábukat a nevükön (huszár, futó…) nevezd meg. Az algebrai jelölést csak egy későbbi, külön leckében vezesd be, mindig a táblával együtt. Egy lecke egyetlen témát tanítson (pl. csak a huszár lépése), kis lépésekben.
Táblás gyakorlat (kattintós): {"tipus":"tabla","kerdes":"Kattints arra a mezőre, ahová a huszár léphet!","fen":"8/8/8/3N4/8/8/8/8","szabaly":{"mit":"lepes","figura":"d5"},"helyes":["b4","b6","c3","c7","e3","e7","f4","f6"],"kiemel":[],"magyarazat":"…"}   (a tanuló a táblán mezőket jelöl; ha egy helyes mező van, azonnal értékelünk, többnél az Ellenőrzés gombbal). A „szabaly” KÖTELEZŐ, és a rendszer a FEN-ből SAJÁT KÓDDAL kiszámolja a helyes mezőket; ha a „helyes” listád eltér, a gyakorlat eldobódik. Szabály-típusok: {"mit":"lepes","figura":"d5"} (ahová a d5-ön álló bábu léphet, leütéssel), {"mit":"tamad","figura":"d5"} (az ellenfél bábui, amiket a d5-ön álló bábu támad; király nélkül), {"mit":"tamadott_mezo","figura":"d5"} (a d5-ön álló bábu által támadott mezők, üresek is), {"mit":"tamadott","szin":"fekete"} (a fekete által támadott fehér bábuk, király nélkül), {"mit":"vedtelen","szin":"fekete"} (a fekete által támadott és semmivel nem védett fehér bábuk, király nélkül). Más típusú kérdést táblás gyakorlatként NE tegyél fel (azt tedd tesztbe). Állásban a bábuk elhelyezése pontos legyen: a kérdés csak azt kérdezze, amit a szabály kiszámít. Sakkban a király támadását (sakk) külön tanítsd, ne „támadott figura” kérdésként.
A gyakorlat „abra” mezője csak SZEMLÉLTESSEN: SOHA ne sorolja fel a válaszlehetőségeket (azok már ott vannak a gombokon), és ne árulja el a helyes választ (pl. egy „Melyik szám a legkisebb?” kérdésnél ne táblázat listázza a számokat; legfeljebb egy számegyenes-rajz, ami nem címkézi a lehetőségeket). Válaszd mindig azt az ábratípust, ami az adott tartalmat a legjobban megmutatja, és változatosan használd őket. Ábratípusok (pontosan ezek a mezők; az emoji a rajzos elem):
{"tipus":"jelenet","cim":"…","hatter":"szoba|kint|kavezo|iskola|viz|ejszaka|ures","elemek":[{"emoji":"☕","felirat":"coffee","x":30,"y":55,"meret":2}]}   (2-7 elem; x,y: 0-100 a képen, ne fedjék egymást; meret 1-3; a felirat rövid szó – nyelvtanulásnál a tanult nyelven; a tanuló ráérintve meghallgatja)
{"tipus":"folyamat","cim":"…","lepesek":[{"ikon":"1️⃣","szoveg":"…"}]}   (2-6 lépés)
{"tipus":"idovonal","cim":"…","pontok":[{"cimke":"…","szoveg":"…","ikon":"📌"}]}
{"tipus":"osszehasonlit","cim":"…","bal":{"cim":"…","pontok":["…"]},"jobb":{"cim":"…","pontok":["…"]}}
{"tipus":"diagram","forma":"oszlop|kor","cim":"…","egyseg":"…","adatok":[{"cimke":"…","ertek":12}]}
{"tipus":"kapcsolat","cim":"…","kozep":{"szoveg":"…","ikon":"💡"},"agak":[{"szoveg":"…","ikon":"…"}]}   (gondolattérkép, 3-7 ág)
{"tipus":"tablazat","cim":"…","fejlec":["…"],"sorok":[["…"]]}
{"tipus":"ora","cim":"…","ora":3,"perc":30}   (óra-rajz, időkifejezésekhez)
{"tipus":"tabla","cim":"…","fen":"start vagy FEN-állás, pl. 8/8/8/3N4/8/8/8/8","kiemel":["e4","f6"],"nyilak":[["g1","f3"]]}   (SAKKTÁBLA-ábra: a bábukat az állás (FEN) adja, a kiemelt mezők zöld pöttyöt, a nyilak lépést mutatnak; fehér = nagybetű, fekete = kisbetű: K/k király, Q/q vezér, R/r bástya, B/b futó, N/n huszár, P/p gyalog)
{"tipus":"rajz","cim":"…","svg":"<svg viewBox=\\"0 0 200 120\\">…</svg>"}   (saját, egyszerű, stilizált, lekerekített rajz, legfeljebb ~40 elem; színként csak hexa vagy var(--zold), var(--kek), var(--arany), var(--piros) használható; semmi script, kép, hivatkozás, stílus)"""

LECKE_PROMPT = """Egy tanulóapp leckéjét írod meg egy magyar felhasználónak. Válaszod KIZÁRÓLAG egyetlen JSON-objektum legyen.

Tanulnivaló: {cim} (cél: {cel}; szint: {szint}). A tanuló nyelve: magyar.
Fejezet: {modul}
Mai lecke ({sorszam}/{ossz}): {lecke_cim} – {tema}
Kulcsfogalmak: {kulcs}
Eddigi leckék (ne ismételd őket, de építs rájuk): {elozo}
Gyengén ismert elemek, amiket érdemes beleszőni: {gyenge}
Időkeret: kb. {perc} perc → {db} gyakorlat.
{nyelvi}

Írj lényegre törő, barátságos, játékos hangvételű tartalmat. Az „bevezeto” legfeljebb 120 szó, markdown (félkövér, rövid lista), konkrét példával – ez a mini-tanítás. Utána {db} változatos gyakorlat, könnyűtől a nehezebbig, és használd a különféle típusokat (legalább 3-4 fajtát, köztük 1-2 gyors igazhamis, 1-2 kitolt vagy hibakereso, ha a témához illik); legyen közte felismerés (teszt), felidézés (ird) és alkalmazás.
A hibás válaszlehetőségek legyenek hihetők. Minden gyakorlathoz írj rövid „magyarazat”-ot (miért az a helyes).

Gyakorlat-típusok (pontosan ezek a mezők):
{{"tipus":"teszt","kerdes":"…","valaszok":["…","…","…","…"],"helyes":0,"magyarazat":"…"}}
{{"tipus":"ird","kerdes":"…","valasz":"a helyes válasz","elfogad":["más elfogadható alak"],"magyarazat":"…"}}
{{"tipus":"parosit","kerdes":"Párosítsd össze!","parok":[["bal","jobb"],["bal","jobb"],["bal","jobb"],["bal","jobb"]],"magyarazat":"…"}}
{{"tipus":"rendez","kerdes":"Tedd sorrendbe a szavakat!","elemek":["szavak","összekeverve"],"helyes":["a","helyes","sorrend"],"magyarazat":"…"}}
{{"tipus":"igazhamis","kerdes":"Egy rövid, egyértelmű állítás","helyes":true,"magyarazat":"…"}}   (gyors, időre menő kör: igaz vagy hamis; az állítás legyen 100%-ig egyértelmű, ne csapda-szőrszálhasogatás; a „helyes” true/false)
{{"tipus":"kitolt","kerdes":"Egészítsd ki a mondatot!","mondat":"mondat pontosan egy ___ hellyel","valasz":"a hiányzó szó","lehetosegek":["a hiányzó szó","hihető rossz","hihető rossz"],"magyarazat":"…"}}   (3-4 lehetőség, a „valasz” szerepeljen közte, pontosan egy hely legyen)
{{"tipus":"hibakereso","kerdes":"Melyik szó hibás a mondatban?","szavak":["a","mondat","szavai","egyenként"],"helyes":2,"javitas":"a helyes alak","magyarazat":"…"}}   (a mondatban PONTOSAN EGY hiba legyen; a „helyes” a hibás szó 0-tól számolt indexe)
{hallgat}
{abra_leiras}
{miniapp_leiras}
A „parosit” gyakorlatnál minden pár legyen EGYÉRTELMŰ 1:1: a bal oldali elemhez pontosan EGY jobb oldali illik, és egyik jobb oldali elem sem illhet másik bal oldalihoz. Kerüld a szinonimákat, az átfedő jelentéseket és a hasonló fogalmakat (pl. két hasonló érzelem két hasonló leírása). Használj egyértelmű párokat: kifejezés ↔ fordítás, fogalom ↔ meghatározás, szó ↔ példa, ábra-elem ↔ név. 3-5 pár, rövid elemek (legfeljebb ~40 karakter), a két oldal elemei soha nem lehetnek azonosak.
Az „ird” gyakorlatnál az „elfogad” tömbbe írd az ÖSSZES ugyanúgy helyes, természetes megfogalmazást (legalább 2-4-et: rövidített/nem rövidített alak, szinonima, más szórend, udvariassági szó nélküli változat), hogy a tanuló jó válasza ne maradjon el.
A „helyes” a teszt-nél a valaszok tömb 0-tól számolt indexe, és ne mindig 0 legyen.
{tanulsagok}A teszt „helyes” válasza biztosan szerepeljen a válaszlehetőségek között, és legyen EGYÉRTELMŰEN a legjobb; a kérdés, az ábra és a magyarázat ne mondjon ellent egymásnak. Ha nem vagy 100%-ig biztos egy tényben, ne használd. Sakkban minden állítást (ki kit támad, mi védett) az ábra FEN-állásából következtess, figura-mezőnként ellenőrizve.
Az „kartyak” azok az új, megtanulandó elemek (3-6 db), amelyeket a rendszer a következő napokban visszakérdez: {{"elol":"kérdés/fogalom","hatul":"válasz/jelentés"}}.

JSON-forma: {{"bevezeto":"…","miniapp":{{…}} (csak ha indokolt, különben hagyd ki),"abrak":[…ábra-objektumok…],"gyakorlatok":[…, mindegyikhez opcionálisan "abra": {{…}}],"kartyak":[{{"elol":"…","hatul":"…"}}]}}"""


EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2190-\u21FF\u2300-\u27BF\u2B00-\u2BFF\uFE0F\u200d]")


SVG_TAGOK = {"svg": "svg", "g": "g", "path": "path", "circle": "circle", "ellipse": "ellipse", "rect": "rect", "line": "line", "polyline": "polyline",
             "polygon": "polygon", "text": "text", "tspan": "tspan", "defs": "defs", "lineargradient": "linearGradient",
             "radialgradient": "radialGradient", "stop": "stop", "title": "title"}
_NUM = re.compile(r"^-?\d{1,4}(\.\d{1,3})?%?$")
_SZIN = re.compile(r"^(none|currentColor|#[0-9a-fA-F]{3,8}|rgba?\([0-9., %]{3,30}\)|var\(--[a-z0-9-]{2,20}\)|url\(#[A-Za-z0-9_-]{1,20}\)|[a-zA-Z]{3,20})$")
SVG_ATTR = {"viewbox": "viewBox", "d": "d", "cx": "cx", "cy": "cy", "r": "r", "rx": "rx", "ry": "ry", "x": "x", "y": "y", "x1": "x1", "y1": "y1", "x2": "x2",
            "y2": "y2", "width": "width", "height": "height", "points": "points", "fill": "fill", "stroke": "stroke", "stroke-width": "stroke-width",
            "stroke-linecap": "stroke-linecap", "stroke-linejoin": "stroke-linejoin", "opacity": "opacity", "fill-opacity": "fill-opacity",
            "stroke-opacity": "stroke-opacity", "transform": "transform", "font-size": "font-size", "font-weight": "font-weight",
            "text-anchor": "text-anchor", "dominant-baseline": "dominant-baseline", "id": "id", "offset": "offset", "stop-color": "stop-color",
            "stop-opacity": "stop-opacity", "gradientunits": "gradientUnits", "fx": "fx", "fy": "fy", "stroke-dasharray": "stroke-dasharray"}


def _attr_ertek(k: str, v: str, azon: str) -> str | None:
    v = v.strip()
    if k in ("fill", "stroke", "stop-color"):
        if not _SZIN.match(v):
            return None
        return re.sub(r"url\(#([A-Za-z0-9_-]+)\)", lambda m: f"url(#{azon}-{m.group(1)})", v)
    if k == "id":
        return f"{azon}-{v}" if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,19}", v) else None
    if k in ("d", "points"):
        return v if len(v) <= 1800 and re.fullmatch(r"[MmLlHhVvCcSsQqTtAaZz0-9 ,.\-+eE]+", v) else None
    if k == "transform":
        return v if len(v) < 120 and re.fullmatch(r"(?:(?:translate|rotate|scale|skewX|skewY)\([0-9 ,.\-]+\) ?)+", v) else None
    if k == "viewbox":
        return v if re.fullmatch(r"[0-9 .]{5,30}", v) else None
    if k in ("opacity", "fill-opacity", "stroke-opacity", "stop-opacity"):
        return v if re.fullmatch(r"0|1|0?\.\d{1,3}", v) else None
    if k == "font-weight":
        return v if re.fullmatch(r"normal|bold|[1-9]00", v) else None
    if k == "text-anchor":
        return v if v in ("start", "middle", "end") else None
    if k == "dominant-baseline":
        return v if v in ("middle", "central", "hanging", "auto") else None
    if k == "stroke-linecap":
        return v if v in ("butt", "round", "square") else None
    if k == "stroke-linejoin":
        return v if v in ("miter", "round", "bevel") else None
    if k == "gradientunits":
        return v if v in ("userSpaceOnUse", "objectBoundingBox") else None
    if k == "stroke-dasharray":
        return v if re.fullmatch(r"[0-9 ,.]{1,30}", v) else None
    return v if _NUM.match(v) else None


def svg_tisztit(svg) -> str | None:
    """A Claude által rajzolt SVG szigorú, engedélyezőlistás megtisztítása (nincs script, hivatkozás, stílus, esemény). Hibánál None."""
    import xml.etree.ElementTree as ET
    if not isinstance(svg, str) or len(svg) > 8000 or "<!" in svg or "<?" in svg:
        return None
    try:
        gyoker = ET.fromstring(svg.strip())
    except ET.ParseError:
        return None
    azon = "s" + uuid.uuid4().hex[:5]
    db = [0]

    def tisztit(e, gyokere=False):
        t = SVG_TAGOK.get(str(e.tag).split("}")[-1].lower())
        if not t:
            return None
        db[0] += 1
        if db[0] > 160:
            raise ValueError("túl sok elem")
        uj = ET.Element(t)
        for k, v in e.attrib.items():
            k = str(k).split("}")[-1].lower()
            if k not in SVG_ATTR or (gyokere and k in ("width", "height", "id")):
                continue
            ertek = _attr_ertek(k, str(v), azon)
            if ertek is not None:
                uj.set(SVG_ATTR[k], ertek)
        if t in ("text", "tspan", "title"):
            uj.text = (e.text or "").strip()[:80]
        for gy in e:
            c = tisztit(gy)
            if c is not None:
                c.tail = (gy.tail or "").strip()[:80] if t in ("text", "tspan") else None
                uj.append(c)
        return uj
    try:
        if str(gyoker.tag).split("}")[-1].lower() != "svg":
            return None
        ki = tisztit(gyoker, True)
    except ValueError:
        return None
    if ki is None or len(ki) == 0:
        return None
    if "viewBox" not in ki.attrib:
        ki.set("viewBox", "0 0 200 120")
    return ET.tostring(ki, encoding="unicode")


def _kanon_szoveg(s) -> str:
    return re.sub(r"[\s.,;:!?'\"„”()]+", "", str(s).lower().replace("−", "-").replace("–", "-"))


def _abra_levelek(a: dict) -> list[str]:
    """Az ábra minden megjeleníthető szövege (a válaszlehetőségekkel való egyezés vizsgálatához)."""
    out: list[str] = []
    t = a.get("tipus")
    if t == "jelenet":
        out += [e["felirat"] for e in a["elemek"] if e.get("felirat")]
    elif t == "folyamat":
        out += [s["szoveg"] for s in a["lepesek"]]
    elif t == "idovonal":
        out += [p[k] for p in a["pontok"] for k in ("cimke", "szoveg") if p.get(k)]
    elif t == "osszehasonlit":
        out += a["bal"]["pontok"] + a["jobb"]["pontok"]
    elif t == "diagram":
        out += [d["cimke"] for d in a["adatok"]]
    elif t == "kapcsolat":
        out += [x["szoveg"] for x in a["agak"]] + [a["kozep"]["szoveg"]]
    elif t == "tablazat":
        out += [c for s in a["sorok"] for c in s] + a["fejlec"]
    return out


def abra_szur(g: dict) -> dict:
    """Teszt-gyakorlatnál az ábra ne sorolja fel újra a válaszlehetőségeket, és ne áruljon el feliratban sem. Másolatot ad vissza."""
    a = g.get("abra")
    if g.get("tipus") != "teszt" or not a or not g.get("valaszok"):
        return g
    opciok = {_kanon_szoveg(v) for v in g["valaszok"] if _kanon_szoveg(v)}
    talalat = len(opciok & {_kanon_szoveg(x) for x in _abra_levelek(a) if _kanon_szoveg(x)})
    g = dict(g)
    if a.get("tipus") == "jelenet":
        if talalat >= 1:  # a felirat elárulná a választ: marad a kép, a felirat nélkül
            g["abra"] = {**a, "elemek": [{**e, "felirat": ""} for e in a["elemek"]]}
    elif talalat >= 2 or (talalat >= 1 and len(opciok) <= 2):
        g.pop("abra")
    return g


def _sz(x, n=60) -> str:
    return str(x if x is not None else "").strip()[:n]


def _szam(x, lo, hi, alap):
    try:
        return max(lo, min(hi, float(x)))
    except (TypeError, ValueError):
        return alap


_MEZO = re.compile(r"[a-h][1-8]")
SAKK_KEZDO = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"


def fen_tiszta(fen) -> str | None:
    """Sakk-állás (FEN első mezője: a bábuk elhelyezése). 'start' = kezdőállás. Hibás → None."""
    f = str(fen or "").strip().split(" ")[0]
    if f.lower() in ("start", "kezdo", "kezdő"):
        return SAKK_KEZDO
    sorok = f.split("/")
    if len(sorok) != 8:
        return None
    for s in sorok:
        if not re.fullmatch(r"[pnbrqkPNBRQK1-8]+", s) or sum(int(c) if c.isdigit() else 1 for c in s) != 8:
            return None
    return f


def mezok(lista, max_db=16) -> list[str]:
    return [str(m).strip().lower() for m in (lista or [])[:max_db] if _MEZO.fullmatch(str(m).strip().lower())]


def abra_ell(a) -> dict | None:
    """Egy szemléltető ábra ellenőrzése és megtisztítása (a Claude kimenete nem megbízható). Hibás ábra: None."""
    if not isinstance(a, dict):
        return None
    t, cim = a.get("tipus"), _sz(a.get("cim"), 80)
    try:
        if t == "jelenet":
            el = [{"emoji": _sz(e.get("emoji"), 8), "felirat": _sz(e.get("felirat"), 30), "x": _szam(e.get("x"), 6, 94, 50), "y": _szam(e.get("y"), 10, 88, 50),
                   "meret": int(_szam(e.get("meret"), 1, 3, 2))} for e in a.get("elemek", [])[:8] if isinstance(e, dict) and e.get("emoji")]
            hatter = a.get("hatter") if a.get("hatter") in ("szoba", "kint", "kavezo", "iskola", "viz", "ejszaka", "ures") else "ures"
            return {"tipus": t, "cim": cim, "hatter": hatter, "elemek": el} if len(el) >= 1 else None
        if t == "folyamat":
            l = [{"ikon": _sz(s.get("ikon"), 8), "szoveg": _sz(s.get("szoveg"), 90)} for s in a.get("lepesek", [])[:7] if isinstance(s, dict) and s.get("szoveg")]
            return {"tipus": t, "cim": cim, "lepesek": l} if len(l) >= 2 else None
        if t == "idovonal":
            l = [{"cimke": _sz(s.get("cimke"), 30), "szoveg": _sz(s.get("szoveg"), 90), "ikon": _sz(s.get("ikon"), 8)} for s in a.get("pontok", [])[:7] if isinstance(s, dict) and (s.get("cimke") or s.get("szoveg"))]
            return {"tipus": t, "cim": cim, "pontok": l} if len(l) >= 2 else None
        if t == "osszehasonlit":
            def oszlop(o):
                o = o if isinstance(o, dict) else {}
                return {"cim": _sz(o.get("cim"), 40), "pontok": [_sz(p, 80) for p in (o.get("pontok") or [])[:6] if p]}
            b, j = oszlop(a.get("bal")), oszlop(a.get("jobb"))
            return {"tipus": t, "cim": cim, "bal": b, "jobb": j} if b["pontok"] and j["pontok"] else None
        if t == "diagram":
            ad = [{"cimke": _sz(d.get("cimke"), 16), "ertek": _szam(d.get("ertek"), 0, 1e9, 0)} for d in a.get("adatok", [])[:8] if isinstance(d, dict) and d.get("cimke")]
            return {"tipus": t, "cim": cim, "forma": "kor" if a.get("forma") == "kor" else "oszlop", "egyseg": _sz(a.get("egyseg"), 12), "adatok": ad} if len(ad) >= 2 and sum(d["ertek"] for d in ad) > 0 else None
        if t == "kapcsolat":
            k = a.get("kozep") if isinstance(a.get("kozep"), dict) else {}
            ag = [{"szoveg": _sz(x.get("szoveg"), 24), "ikon": _sz(x.get("ikon"), 8)} for x in a.get("agak", [])[:7] if isinstance(x, dict) and x.get("szoveg")]
            return {"tipus": t, "cim": cim, "kozep": {"szoveg": _sz(k.get("szoveg"), 24), "ikon": _sz(k.get("ikon"), 8)}, "agak": ag} if len(ag) >= 3 and k.get("szoveg") else None
        if t == "tablazat":
            fe = [_sz(x, 24) for x in a.get("fejlec", [])[:5]]
            so = [[_sz(c, 40) for c in s[:5]] for s in a.get("sorok", [])[:8] if isinstance(s, list)]
            return {"tipus": t, "cim": cim, "fejlec": fe, "sorok": so} if fe and so else None
        if t == "ora":
            return {"tipus": t, "cim": cim, "ora": int(_szam(a.get("ora"), 0, 23, 3)), "perc": int(_szam(a.get("perc"), 0, 59, 0))}
        if t == "tabla":
            fen = fen_tiszta(a.get("fen"))
            nyilak = [[x[0].strip().lower(), x[1].strip().lower()] for x in (a.get("nyilak") or [])[:6] if isinstance(x, list) and len(x) == 2 and all(_MEZO.fullmatch(str(m).strip().lower()) for m in x)]
            if fen:
                nyilak = [n for n in nyilak if sakk.nyil_jo(fen, n[0], n[1])]   # csak valódi lépést/támadást mutató nyíl marad
            return {"tipus": t, "cim": cim, "fen": fen, "kiemel": mezok(a.get("kiemel")), "nyilak": nyilak, "koordinata": a.get("koordinata", True) is not False} if fen else None
        if t == "rajz":
            s = svg_tisztit(a.get("svg"))
            return {"tipus": t, "cim": cim, "svg": s} if s else None
    except (TypeError, ValueError, AttributeError):
        return None
    return None


def beszed_szegmensek(szoveg: str, kod: str) -> list[dict]:
    """A lecke bevezetőjéből felolvasható darabok: magyar részek (mondathatáron, ≤200 karakter) és – angol leckénél – a *dőlt* angol részek."""
    t = EMOJI.sub("", szoveg or "").replace("**", "").replace("`", "")
    t = re.sub(r"(?m)^\s*[-•]\s+", "", t)
    out: list[dict] = []

    def magyar(r: str) -> None:
        r = r.replace("*", "")
        for sor in re.split(r"\n+", r):
            cs, akt = re.split(r"(?<=[.!?:;])\s+", sor.strip()), ""
            for m in cs + [""]:
                if m and len(akt) + len(m) < 200:
                    akt = (akt + " " + m).strip()
                    continue
                if re.search(r"\w", akt):
                    out.append({"t": akt, "l": "hu"})
                akt = m.strip()
    for resz in re.split(r"(\*[^*\n]+\*)", t):
        if kod and len(resz) > 2 and resz[0] == "*" and resz[-1] == "*" and re.search(r"\w", resz):
            out.append({"t": resz[1:-1].strip()[:250], "l": kod})
        elif resz.strip():
            magyar(resz)
    return out[:40]


HU_HANGOK = ("anna", "berta", "imre")
EN_HANGOK = ("lessac", "amy", "ryan", "alba")


# ---------------------------------------------------------------------------------------------------- jelzések (kivizsgálásra)
ADMIN_TOKEN_FAJL = ITT / ".admin_token"


def admin_token() -> str:
    """Az admin-oldal titka (a tanoda/.admin_token fájlban; ha nincs, létrejön). Soha nem kerül naplóba vagy gitbe."""
    try:
        v = ADMIN_TOKEN_FAJL.read_text().strip()
        if len(v) >= 16:
            return v
    except OSError:
        pass
    v = uuid.uuid4().hex + uuid.uuid4().hex[:8]
    ADMIN_TOKEN_FAJL.write_text(v)
    os.chmod(ADMIN_TOKEN_FAJL, 0o600)
    return v


def jelzesek() -> list[dict]:
    return olvas_g("jelzesek.json", [])


def jelzes_felvesz(cid: str, lecke: int, gi: int, valasz: str) -> dict:
    """A tanuló szerint helyes, de hibásnak ítélt válasz: NEM fogadjuk el, hanem kivizsgálásra bekerül a listába."""
    c = cel_olvas(cid)
    lk = (c or {}).get("leckek", {}).get(str(lecke))
    v = " ".join(str(valasz).split())[:200]
    if not lk or not 0 <= gi < len(lk.get("gyakorlatok", [])) or not v:
        raise ValueError("nincs ilyen gyakorlat")
    g = lk["gyakorlatok"][gi]
    if g.get("tipus") not in ("ird", "hallgat"):
        raise ValueError("ehhez a feladattípushoz nincs jelzés")
    with JELZES_ZAR:
        lista = jelzesek()
        for j in lista:  # ugyanaz a válasz ugyanarra a feladatra: nem duplikáljuk, csak számoljuk
            if j.get("user", ADMIN_FELH) == aktualis() and j["cel"] == cid and j["lecke"] == lecke and j["gy"] == gi and j["felhasznalo"].lower() == v.lower() and j["allapot"] == "uj":
                j["db"] = j.get("db", 1) + 1
                break
        else:
            j = {"id": uuid.uuid4().hex[:8], "user": aktualis(), "ido": datetime.now().isoformat(timespec="seconds"), "cel": cid, "cel_cim": c["cim"], "lecke": lecke,
                 "lecke_cim": leckek_lista(c)[lecke]["cim"] if lecke < len(leckek_lista(c)) else "", "gy": gi, "tipus": g["tipus"],
                 "kerdes": g.get("kerdes", ""), "helyes": g.get("valasz") or g.get("szoveg", ""), "elfogad": g.get("elfogad", []),
                 "magyarazat": g.get("magyarazat", ""), "nyelv": c.get("terv", {}).get("nyelv", ""), "felhasznalo": v, "db": 1,
                 "allapot": "uj", "megjegyzes": "", "latta": False}
            lista.append(j)
        ir_g("jelzesek.json", lista[-500:])
    return j


# ---------------------------------------------------------------------------------------------------- visszajelzések (ötlet / hiba) – admin és Claude átnézheti
KATEGORIAK = {"hiba": "🐞 Hiba", "otlet": "💡 Ötlet", "ertheto": "😕 Nem érthető", "tetszik": "👍 Tetszik"}
VISSZA_ALLAPOTOK = ("uj", "folyamatban", "kesz", "elvetve")


def visszajelzesek() -> list[dict]:
    return olvas_g("visszajelzesek.json", [])


def visszajelzes_felvesz(kat: str, szoveg: str, kont) -> dict:
    szoveg = str(szoveg or "").strip()[:1500]
    if len(szoveg) < 3:
        raise ValueError("Írj egy-két mondatot, hogy tudjuk, mi a helyzet.")
    kont = {str(k)[:30]: str(v)[:200] for k, v in list(kont.items())[:14]} if isinstance(kont, dict) else {}
    with JELZES_ZAR:
        lista = visszajelzesek()
        ma_db = sum(1 for x in lista if x.get("user") == aktualis() and x["ido"][:10] == ma().isoformat())
        if ma_db >= 20:
            raise ValueError("Mára elég visszajelzést küldtél, köszönjük! Holnap folytathatod.")
        e = {"id": uuid.uuid4().hex[:8], "ido": datetime.now().isoformat(timespec="seconds"), "user": aktualis(), "kategoria": kat if kat in KATEGORIAK else "otlet",
             "szoveg": szoveg, "kontextus": kont, "allapot": "uj", "megjegyzes": "", "latta": True}
        lista.append(e)
        ir_g("visszajelzesek.json", lista[-1000:])
    return e


def visszajelzes_allapot(vid: str, allapot: str, megjegyzes: str = "") -> dict:
    if allapot not in VISSZA_ALLAPOTOK:
        raise ValueError("az állapot: " + ", ".join(VISSZA_ALLAPOTOK))
    with JELZES_ZAR:
        lista = visszajelzesek()
        e = next((x for x in lista if x["id"] == vid), None)
        if not e:
            raise ValueError("nincs ilyen visszajelzés")
        e["allapot"], e["megjegyzes"] = allapot, str(megjegyzes)[:300]
        e["dontes_ido"] = datetime.now().isoformat(timespec="seconds")
        e["latta"] = allapot in ("uj", "folyamatban") or not e["megjegyzes"]   # a tanulónak csak a megjegyzéses lezárást jelezzük
        ir_g("visszajelzesek.json", lista)
    return e


def jelzes_dontes(jid: str, dontes: str, megjegyzes: str = "") -> dict:
    """Admin döntés: elfogad (az új alak bekerül a feladat elfogadott válaszai közé) vagy elutasit."""
    if dontes not in ("elfogad", "elutasit"):
        raise ValueError("a döntés: elfogad vagy elutasit")
    with JELZES_ZAR:
        lista = jelzesek()
        j = next((x for x in lista if x["id"] == jid), None)
        if not j:
            raise ValueError("nincs ilyen jelzés")
        j["allapot"] = "elfogadva" if dontes == "elfogad" else "elutasitva"
        j["megjegyzes"] = megjegyzes[:300]
        j["dontes_ido"] = datetime.now().isoformat(timespec="seconds")
        j["latta"] = False
        ir_g("jelzesek.json", lista)
    if dontes == "elfogad":
        with felhasznalo(j.get("user", ADMIN_FELH)):
            c = cel_olvas(j["cel"])
            lk = (c or {}).get("leckek", {}).get(str(j["lecke"]))
            if lk and 0 <= j["gy"] < len(lk.get("gyakorlatok", [])):
                g = lk["gyakorlatok"][j["gy"]]
                if j["felhasznalo"].lower() not in [x.lower() for x in g.setdefault("elfogad", [])] and len(g["elfogad"]) < 20:
                    g["elfogad"].append(j["felhasznalo"])
                    ir(f"cel_{j['cel']}.json", c)
    return j


def hang_valasztas() -> tuple[str, str]:
    """Illés választott felolvasó hangjai (magyar, angol) – a profilból."""
    b = profil().get("beallitasok") or {}
    return (b.get("huHang") if b.get("huHang") in HU_HANGOK else "anna", b.get("enHang") if b.get("enHang") in EN_HANGOK else "lessac")


def tts_fajl(szoveg: str, h: str = "en", v: str = "") -> Path | str:
    """Felolvasott hangfájl (gyorsítótárból vagy újonnan). h: en = angol hang, hu = magyar (Anna, vidám). Hibánál szöveg."""
    szoveg = szoveg.strip()[:300]
    if h not in ("en", "hu"):   # tanult idegen nyelv: a telepített legjobb hangcsomag
        modell = hangcsomag.modell_nev(h)
        if not modell:
            return "nincs hangcsomag ehhez a nyelvhez"
        v = "m:" + modell
    else:
        v = v if v in (EN_HANGOK if h == "en" else HU_HANGOK) else ("lessac" if h == "en" else "anna")
    f = TTS_MAPPA / (hashlib.sha1(f"{h}|{v}|{szoveg}".encode()).hexdigest()[:16] + ".m4a")
    if not f.exists():
        import hangkeszito
        with TTS_ZAR:
            hiba = hangkeszito.szintetizal(szoveg, v, f, "m4a", "" if h != "hu" or v == "imre" else "vidam")
        if hiba:
            return hiba
    return f


def lecke_hangjai(c: dict, lk: dict) -> list[tuple[str, str]]:
    """A lecke összes felolvasandó szövege (szöveg, nyelv): bevezető, ábra-feliratok (koppintásra), hallgat/mondd mondatok."""
    kod = c["terv"].get("nyelv", "")
    hangos = kod == "en" or (bool(kod) and bool(hangcsomag.modell_nev(kod)))
    jel = kod if hangos else "hu"
    ki: list[tuple[str, str]] = [(sz["t"], sz["l"]) for sz in beszed_szegmensek(lk.get("bevezeto", ""), kod)]
    abrak = [*(lk.get("abrak") or []), *[g.get("abra") for g in lk.get("gyakorlatok", []) if g.get("abra")]]
    for a in abrak:
        if isinstance(a, dict) and a.get("tipus") == "jelenet":
            ki += [(e["felirat"], jel) for e in a.get("elemek", []) if isinstance(e, dict) and e.get("felirat")]
    for g in lk.get("gyakorlatok", []):
        if g.get("tipus") in ("hallgat", "mondd") and g.get("szoveg") and kod:
            ki.append((g["szoveg"], kod))
    lattuk, ut = set(), []
    for t, l in ki:
        if (t, l) not in lattuk and t.strip():
            lattuk.add((t, l))
            ut.append((t, l))
    return ut


def elorenderel(cid: str, idx: int) -> None:
    """A lecke ÖSSZES hangját a háttérben előre legyártja (gyorsítótárba), hogy induláskor és közben azonnal szóljon."""
    try:
        c = cel_olvas(cid)
        hu, en = hang_valasztas()
        for t, l in lecke_hangjai(c, c["leckek"][str(idx)]):
            tts_fajl(t, l, en if l == "en" else hu if l == "hu" else "")
    except Exception:  # noqa: BLE001 – csak gyorsítás
        pass


_ELORE_KESZ: set = set()


def kovetkezo_elore(slug: str, c: dict, b: dict) -> None:
    """A leckelista megnyitásakor a sorban következő (már megírt) lecke hangját a háttérben előre legyártja."""
    i = b.get("kovetkezo")
    if i is None or str(i) not in c.get("leckek", {}) or not c.get("terv"):
        return
    kulcs = (slug, c.get("id"), i, c["leckek"][str(i)].get("keszult"))
    if kulcs in _ELORE_KESZ:
        return
    _ELORE_KESZ.add(kulcs)
    _szal_felh(elorenderel, slug, c.get("id"), i)


_ROV = {"i'm": "i am", "you're": "you are", "he's": "he is", "she's": "she is", "it's": "it is", "we're": "we are", "they're": "they are",
        "i've": "i have", "don't": "do not", "doesn't": "does not", "didn't": "did not", "can't": "cannot", "won't": "will not", "isn't": "is not",
        "aren't": "are not", "wasn't": "was not", "weren't": "were not", "that's": "that is", "what's": "what is", "there's": "there is",
        "let's": "let us", "i'll": "i will", "you'll": "you will", "we'll": "we will"}


def szo_lista(szoveg: str, en: bool = True) -> list[tuple[str, str]]:
    """(megjelenített szó, összehasonlító alak) párok: kisbetű, írásjel nélkül."""
    out = []
    if en:
        szoveg = re.sub(r"[A-Za-z]+'[a-z]+", lambda m: _ROV.get(m.group(0).lower(), m.group(0)), szoveg.replace("’", "'"))
    for w in szoveg.split():
        n = re.sub(r"[^\w']", "", w.lower().replace("_", "")).strip("'")
        if n:
            out.append((w, n))
    return out


def beszed_ertekel(hang: bytes, cel: str, nyelv: str = "en") -> dict:
    """A felvételt whisperrel (angolul) leírja, és szavanként összeveti a célmondattal. A leírás a kiejtés közelítése."""
    import hangkeszito
    import wave
    ff = hangkeszito.ffmpeg_exe()
    if not ff or not WHISPER.exists() or not WHISPER_MODELL.exists():
        raise RuntimeError("A beszédfelismerő nincs telepítve.")
    alap = MUNKA_MAPPA / f"beszed_{uuid.uuid4().hex[:8]}"
    be, wav = alap.with_suffix(".bin"), alap.with_suffix(".wav")
    try:
        be.write_bytes(hang)
        p = subprocess.run([ff, "-loglevel", "error", "-y", "-i", str(be), "-t", "15", "-ar", "16000", "-ac", "1", str(wav)],
                           capture_output=True, timeout=60)
        if p.returncode != 0 or not wav.exists():
            raise RuntimeError("A felvételt nem sikerült feldolgozni.")
        with wave.open(str(wav)) as w:
            mp = w.getnframes() / w.getframerate()
        if mp < 0.4:
            return {"ures": True}
        ac = max(100, min(1500, int(mp * 50) + 30))  # a rövid felvételnél kisebb ablak: sokkal gyorsabb
        with WHISPER_ZAR:
            f = subprocess.run([str(WHISPER), "-m", str(WHISPER_MODELL), "-l", nyelv if nyelv in hangcsomag.NYELVEK else "en", "-t", str(os.cpu_count() or 2), "-bs", "1", "-bo", "1",
                                "-ac", str(ac), "-nt", "-np", "-f", str(wav)], capture_output=True, timeout=180)
        if f.returncode != 0:
            raise RuntimeError("A felismerés nem sikerült.")
        hall = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", " ".join(f.stdout.decode(errors="ignore").split()))
        hall = " ".join(hall.split())
    finally:
        be.unlink(missing_ok=True)
        wav.unlink(missing_ok=True)
    cl, hl = szo_lista(cel, nyelv == "en"), szo_lista(hall, nyelv == "en")
    if not hl:
        return {"ures": True}
    sm = difflib.SequenceMatcher(None, [n for _, n in cl], [n for _, n in hl], autojunk=False)
    jo = [False] * len(cl)
    for a, _b, n in sm.get_matching_blocks():
        for i in range(a, a + n):
            jo[i] = True
    return {"ures": False, "hallott": hall, "pontos": round(sum(jo) / max(1, len(cl)), 2),
            "szavak": [{"w": w, "ok": j} for (w, _), j in zip(cl, jo)]}


# ---------------------------------------------------------------------------------------------------- mini-alkalmazások (egy-fájlos, elkülönített)
MINIAPP_MERETEK = ["kicsi", "kozepes", "nagy"]
MINIAPP_AUTO = os.environ.get("TANODA_MINIAPP_AUTO", "kicsi")   # eddig a méretig magától elkészül; efölött a felhasználót kérdezzük
MINIAPP_SOR = {"kicsi": 180, "kozepes": 450, "nagy": 700}
MINIAPP_LEIRAS = """MINI-ALKALMAZÁS (ritkán!): ha a lecke témáját egy kis interaktív program sokkal jobban megmutatná, mint az ábrák és a gyakorlatok (pl. sakk szabályai és lépései, hangjegyek/zongora, törtek vagy geometria mozgatható ábrával, programozás-játszótér, gépelés, logikai játék), akkor a JSON-ba tegyél egy „miniapp” mezőt: {"cim":"…","miert":"1 mondat: mit mutat meg a tanulónak","meret":"kicsi|kozepes|nagy"}. Méret: kicsi = egyszerű interaktív szemléltetés (kb. 150 sor), kozepes = játszható szabálybemutató (kb. 400 sor, pl. sakktábla szabályos lépésekkel és magyarázattal), nagy = teljes játék ellenféllel. A legtöbb leckéhez NEM kell mini-alkalmazás: ilyenkor hagyd ki a mezőt. Legfeljebb egy lehet."""
MINIAPP_PROMPT = """Egyetlen, önálló HTML-fájlt írsz (HTML + CSS + JS egyben): egy kis tanuló-mini-alkalmazást egy magyar tanulónak.
Tanfolyam: {tanfolyam} (cél: {cel}; szint: {szint}). Lecke: {lecke}. Mini-alkalmazás: „{cim}” – {miert} (méret: {meret}).
{extra}
Szabályok:
- Egyetlen fájl, SEMMI külső erőforrás (nincs CDN, kép-URL, betűtípus-hivatkozás, hálózati hívás). Ne használj localStorage-ot, sütit, alert/prompt/confirm-ot. Az SVG névtér-címe (http://www.w3.org/2000/svg) megengedett.
- Magyar felület, mobilbarát (viewport meta, érintésre is jó, nagy gombok), világos és sötét módhoz igazodó színek (@media (prefers-color-scheme: dark)), lekerekített, barátságos, játékos külső (emoji és SVG használható).
- Legyen benne rövid, közérthető magyarázat vagy bemutató, és valódi interaktivitás: a tanuló mozgathat, kattinthat, kipróbálhat. Ha szabályrendszer/játék, a szabályokat valóban hajtsa végre (ne csak rajzolja).
- Ha a tanuló teljesít egy lényeges kihívást vagy végigmegy a bemutatón, hívd meg egyszer: parent.postMessage({{tanoda: "kesz"}}, "*").
- Hibamentes legyen: nincs konzolhiba, minden gomb működik. Tömör kód, legfeljebb kb. {max_sor} sor.
Válaszod KIZÁRÓLAG a teljes HTML-fájl (<!doctype html>-től </html>-ig), semmi más szöveg, magyarázat vagy markdown-kerítés nélkül."""
MINIAPP_EXTRA = {"kicsi": "Egy fő interaktív szemléltetést készíts, tömören.",
                 "kozepes": "Játszható szabálybemutató legyen: a tanuló kipróbálhatja a lépéseket, a rendszer kiemeli a lehetséges lépéseket, és röviden magyaráz.",
                 "nagy": "Teljes, játszható alkalmazás legyen, több móddal vagy szinttel."}
CSP_META = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data:; font-src data:; media-src data:">'


def claude_szoveg(prompt: str, modell: str, effort: str = "medium", timeout: int = 900) -> str:
    """Claude-hívás, nyers szöveges válasszal (nagy, nem JSON-tartalomhoz)."""
    with CLAUDE_ZAR:
        p = subprocess.run(["claude", "-p", prompt, "--model", modell, "--effort", effort, "--tools", "", "--no-session-persistence", "--output-format", "json"],
                           cwd=MUNKA_MAPPA, capture_output=True, timeout=timeout, text=True)
    if p.returncode != 0:
        raise RuntimeError("A Claude hívása nem sikerült: " + (p.stderr or p.stdout)[-300:])
    try:
        v = json.loads(p.stdout)
        naplo_koltseg(modell, v.get("total_cost_usd") or v.get("cost_usd") or 0)
        return v.get("result", "") if isinstance(v, dict) else str(v)
    except ValueError:
        return p.stdout


_MINIAPP_TILTOTT = re.compile(r"https?:|//[a-z0-9.-]+\.[a-z]{2,}/|<link\b|<iframe|<object|<embed|XMLHttpRequest|fetch\s*\(|WebSocket|importScripts|sendBeacon|document\.cookie|localStorage|sessionStorage|window\.top|\bimport\s*\(", re.I)


def miniapp_html_tisztit(szoveg: str) -> str | None:
    """A Claude válaszából a HTML kinyerése és ellenőrzése, elkülönítő CSP beszúrása. Hibánál None (az iframe sandbox ettől függetlenül is véd)."""
    m = re.search(r"<!doctype html.*?</html>", szoveg, re.I | re.S) or re.search(r"<html.*?</html>", szoveg, re.I | re.S)
    if not m:
        return None
    s = m.group(0)
    if not 800 <= len(s) <= 100_000:
        return None
    if _MINIAPP_TILTOTT.search(s.replace("http://www.w3.org/2000/svg", "").replace("http://www.w3.org/1999/xlink", "")):
        return None
    if re.search(r"<head", s, re.I):
        return re.sub(r"(<head[^>]*>)", lambda x: x.group(1) + CSP_META, s, count=1, flags=re.I)
    return s.replace("<html", "<head>" + CSP_META + "</head><html", 1) if "<html" in s else None


def miniapp_fajl(cid: str, idx: int) -> Path:
    return felh_dir() / f"app_{cid}_{int(idx)}.html"


def miniapp_allapot(cid: str, idx: int, allapot: str, hiba: str = "") -> None:
    c = cel_olvas(cid)
    m = (c or {}).get("leckek", {}).get(str(idx), {}).get("miniapp")
    if m:
        m["allapot"], m["hiba"] = allapot, hiba[:200]
        ir(f"cel_{cid}.json", c)


def miniapp_keszit(cid: str, idx: int) -> None:
    c = cel_olvas(cid)
    m = c["leckek"][str(idx)]["miniapp"]
    miniapp_allapot(cid, idx, "keszul")
    ls = leckek_lista(c)
    try:
        szoveg = claude_szoveg(MINIAPP_PROMPT.format(tanfolyam=c["cim"], cel=c["cel"], szint=c["szint"], lecke=ls[idx]["cim"] if idx < len(ls) else "", cim=m["cim"],
                                                      miert=m["miert"], meret=m["meret"], extra=MINIAPP_EXTRA[m["meret"]], max_sor=MINIAPP_SOR[m["meret"]]), MODELL, "medium", 900)
        html = miniapp_html_tisztit(szoveg)
        if not html:
            raise RuntimeError("A mini-alkalmazás kódja nem felelt meg az ellenőrzésnek (külső hivatkozás vagy hibás fájl). Próbáld újra.")
        miniapp_fajl(cid, idx).write_text(html, encoding="utf-8")
        miniapp_allapot(cid, idx, "kesz")
    except Exception as e:  # noqa: BLE001
        miniapp_allapot(cid, idx, "hiba", str(e))
        raise


def terv_keszit(cid: str) -> None:
    c = cel_olvas(cid)
    n = leckek_szama(c)
    adat = claude_json(TERV_PROMPT.format(n=n, cim=c["cim"], cel=c["cel"], szint=c["szint"], perc=c["perc"], nap=c["nap_hetente"],
                                         hetek=c["hetek"], megjegyzes=c.get("megjegyzes") or "nincs"), MODELL, "medium", timeout=420)
    modulok = adat.get("modulok") or []
    sorszam = 0
    for m in modulok:
        for l in m.get("leckek", []):
            l["id"] = sorszam
            sorszam += 1
    if not sorszam:
        raise RuntimeError("A terv üres lett.")
    c["terv"] = {"osszefoglalo": adat.get("osszefoglalo", ""), "modszerek": adat.get("modszerek", []), "modulok": modulok,
                 "nyelv": hangcsomag.nyelv_kod(adat.get("nyelv")) if hangcsomag.nyelv_kod(adat.get("nyelv")) != "hu" else ""}
    c["allapot"] = "kesz"
    c.setdefault("leckek", {})
    ir(f"cel_{cid}.json", c)
    kod = c["terv"]["nyelv"]
    if kod and kod != "en":   # nyelvtanulás: a háttérben megkeresi és letölti a legtermészetesebb hangcsomagot
        threading.Thread(target=hangcsomag.biztosit, args=(kod,), daemon=True).start()


def terv_bovit(cid: str, hetek: int, fokusz: str) -> None:
    """A terv folytatása új szakasszal – az eddigi eredmények és a gyenge kártyák alapján."""
    c = cel_olvas(cid)
    ls = leckek_lista(c)
    if len(ls) >= 120:
        raise RuntimeError("A terv már nagyon hosszú (120 lecke).")
    eddigi = "; ".join(f'{m["cim"]}: ' + ", ".join(l["cim"] for l in m.get("leckek", [])) for m in c["terv"]["modulok"][-4:])
    gyenge_leckek = [ls[int(i)]["cim"] for i, v in c.get("leckek", {}).items()
                     if v.get("kesz") and v.get("eredmeny") and v["eredmeny"]["helyes"] / max(1, v["eredmeny"]["osszes"]) < 0.7 and int(i) < len(ls)]
    kesz = [v["eredmeny"] for v in c.get("leckek", {}).values() if v.get("kesz") and v.get("eredmeny")]
    atlag = round(100 * sum(e["helyes"] for e in kesz) / max(1, sum(e["osszes"] for e in kesz))) if kesz else 0
    eredm = f"átlag {atlag}% helyes" + (f"; gyengén ment: {', '.join(gyenge_leckek[:5])}" if gyenge_leckek else "; nincs kirívóan gyenge lecke")
    n = leckek_szama({"nap_hetente": c["nap_hetente"], "hetek": hetek})
    adat = claude_json(BOVIT_PROMPT.format(cim=c["cim"], cel=c["cel"], szint=c["szint"], perc=c["perc"], nap=c["nap_hetente"], eddigi=eddigi[:1500],
                                          eredmenyek=eredm, gyenge="; ".join(gyenge_kartyak(c, 10)) or "nincs", fokusz=fokusz or "nincs külön kérés",
                                          n=n, hetek=hetek), MODELL, "medium", timeout=420)
    c = cel_olvas(cid)
    szakasz = max([m.get("szakasz", 1) for m in c["terv"]["modulok"]] + [1]) + 1
    kezdo = len(leckek_lista(c))
    uj, sorszam = [], kezdo
    for m in adat.get("modulok") or []:
        if not m.get("leckek"):
            continue
        for l in m["leckek"]:
            l["id"] = sorszam
            sorszam += 1
        m["szakasz"] = szakasz
        uj.append(m)
    if sorszam == kezdo:
        raise RuntimeError("Az új szakasz üres lett, próbáld újra.")
    c["terv"]["modulok"].extend(uj)
    c["terv"]["osszefoglalo"] = (c["terv"].get("osszefoglalo", "") + f" · {szakasz}. szakasz: " + str(adat.get("osszefoglalo", ""))).strip()[:1200]
    c.setdefault("szakaszok", []).append({"szakasz": szakasz, "tol": kezdo, "hetek": hetek, "fokusz": fokusz, "mikor": ma().isoformat()})
    if c.get("allapot") == "befejezve":
        c["allapot"] = "kesz"
    ir(f"cel_{cid}.json", c)


def anyag_keszit(cid: str) -> None:
    c = cel_olvas(cid)
    mod = "; ".join(m["cim"] for m in c["terv"]["modulok"])
    try:
        adat = claude_json(ANYAG_PROMPT.format(cim=c["cim"], cel=c["cel"], szint=c["szint"], modulok=mod), MODELL, "low", "WebSearch", 420)
    except RuntimeError:
        # webkeresés nélkül tippeket ad (jelölve), ne maradjon üresen
        adat = claude_json(ANYAG_PROMPT.replace("Keress a weben (WebSearch), és csak olyan forrást adj meg, amelyet valóban megtaláltál",
                                                "Nincs webelérésed: csak ismert, biztosan létező, nagy oldalakat/kurzusokat nevezz meg (főoldal-szintű URL)")
                           .format(cim=c["cim"], cel=c["cel"], szint=c["szint"], modulok=mod), MODELL, "low", "", 300)
    c = cel_olvas(cid)
    c["anyagok"] = [a for a in adat.get("anyagok", []) if isinstance(a, dict) and str(a.get("url", "")).startswith("http")][:12]
    ir(f"cel_{cid}.json", c)


def leckek_lista(c: dict) -> list[dict]:
    out = []
    for m in c.get("terv", {}).get("modulok", []):
        for l in m.get("leckek", []):
            out.append({**l, "modul": m["cim"]})
    return out


def gyenge_kartyak(c: dict, szam: int = 6) -> list[str]:
    k = [v for v in c.get("kartyak", {}).values() if v.get("hibak", 0) > 0]
    k.sort(key=lambda v: (-v.get("hibak", 0), v.get("doboz", 0)))
    return [f'{v["elol"]} → {v["hatul"]}' for v in k[:szam]]


LEKTOR = os.environ.get("TANODA_LEKTOR", "1") != "0"   # második, ellenőrző Claude-menet a kész leckén (0 = ki)


def tanulsag_szoveg(c: dict) -> str:
    """A korábbi visszajelzésekből levont, kötelező szabályok (adat/tanulsagok.json) – az ide illők bekerülnek a lecke-promptba."""
    szoveg = f"{c.get('cim', '')} {c.get('cel', '')}".lower()
    sz = [x["szabaly"] for x in olvas_g("tanulsagok.json", []) if isinstance(x, dict) and x.get("szabaly")
          and (not x.get("tema") or x["tema"].lower() in szoveg)][-12:]
    return ("Korábbi tanulói visszajelzésekből levont szabályok – KÖTELEZŐ betartani: " + " | ".join(sz) + "\n") if sz else ""


def minoseg_naplo(c: dict, l: dict, elvetett: int, lektor_hibak: list, maradt: int) -> None:
    """Minden lecke-generálásról egy sor: hány gyakorlatot dobott el a kód, mit talált a lektor (későbbi kiértékeléshez, adat/minoseg.jsonl)."""
    try:
        with JELZES_ZAR, open(ADAT / "minoseg.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"ido": datetime.now().isoformat(timespec="seconds"), "tanfolyam": c.get("cim"), "lecke": l.get("cim"), "elvetett": elvetett,
                                "lektor": lektor_hibak[:8], "maradt": maradt}, ensure_ascii=False) + "\n")
    except OSError:
        pass


LEKTOR_PROMPT = """Te egy szigorú szaklektor és tesztfeladat-ellenőr vagy. Alább egy tanulóapp kész leckéje (JSON). Keresd meg a TÉNYBELI és LOGIKAI hibákat:
- igazhamis: az állítás igazságértéke nem egyezik a „helyes” mezővel vagy kétértelmű; kitolt: nem pontosan EGY lehetőség ad helyes mondatot (több is jó, vagy a „valasz” rossz); hibakereso: nincs hiba, több hiba van, vagy a „helyes” index/„javitas” téves;
- a teszt „helyes” indexe nem a valóban helyes válaszra mutat, vagy a helyes válasz hiányzik a lehetőségek közül, vagy több válasz is helyes;
- a kérdés, az ábra, a magyarázat vagy a bevezető ellentmond egymásnak vagy a valóságnak (téves tény, téves szabály, rossz szám);
- az ábra nem azt mutatja, amit a szöveg állít; a párosítás nem egyértelmű; az „ird” válasz nem az egyetlen helyes;
- nyelvtanulásnál: hibás idegen nyelvi alak, hibás fordítás.
{tenyek}Tanulnivaló: {cim} – lecke: {lecke_cim}.
A gyakorlatokat 1-től sorszámozd. NE találj ki hibát: ha valami rendben van, hagyd békén; csak a biztos hibát jelezd.
Válasz KIZÁRÓLAG egy JSON: {{"hibak":["rövid leírás gyakorlatonként/bevezetőnként"],"javitott_gyakorlatok":{{"3":{{teljes javított gyakorlat-objektum ugyanabban a formában}}}},"torlendo_gyakorlatok":[5],"javitott_bevezeto":null,"javitott_kartyak":null}}
Ha egy hibát biztosan ki tudsz javítani, add a javított gyakorlatot („javitott_gyakorlatok”); különben jelöld törlésre. A „javitott_bevezeto” csak akkor szöveg, ha a bevezetőben van hiba (a teljes, javított bevezető, ugyanolyan formában). Ha nincs hiba: {{"hibak":[]}}.

LECKE:
{lecke}"""


def lecke_lektor(c: dict, l: dict, adat: dict, gy: list, en: bool) -> tuple[list, dict | None, list]:
    """Második Claude-menet: ténybeli/logikai hibák keresése a kész leckében. Sakkállásoknál a kód által kiszámolt tények is mennek vele.
    Visszaad: (javított gyakorlatok, javított adat vagy None, talált hibák listája)."""
    fenek = []
    for forras in [*(adat.get("abrak") or []), *[g.get("abra") for g in gy if g.get("abra")], *[g for g in gy if g.get("tipus") == "tabla"]]:
        f = sakk_fen(forras)
        if f and f not in fenek:
            fenek.append(f)
    tenyek = ("A sakkállások kódból kiszámolt, MEGBÍZHATÓ tényei (ezek az igazságok; ami ellentmond nekik, hibás):\n"
              + "\n".join(f"Állás {i + 1} ({f}):\n{sakk.tenyek(f)}" for i, f in enumerate(fenek[:4])) + "\n") if fenek else ""
    kicsi = {"bevezeto": adat.get("bevezeto", ""), "abrak": adat.get("abrak") or [], "gyakorlatok": gy, "kartyak": adat.get("kartyak") or []}
    v = claude_json(LEKTOR_PROMPT.format(tenyek=tenyek, cim=c["cim"], lecke_cim=l["cim"], lecke=json.dumps(kicsi, ensure_ascii=False)), MODELL, "low", timeout=300)
    hibak = [str(x)[:200] for x in (v.get("hibak") or [])][:10]
    if not hibak:
        return gy, None, []
    uj = list(gy)
    torol = set()
    for k, g in (v.get("javitott_gyakorlatok") or {}).items():
        try:
            i = int(k) - 1
            if 0 <= i < len(uj) and isinstance(g, dict) and g.get("tipus") == uj[i].get("tipus") and jo_gyakorlat(g, en):
                if uj[i].get("abra") and not g.get("abra"):
                    g["abra"] = uj[i]["abra"]
                uj[i] = g
            else:
                torol.add(i)
        except (TypeError, ValueError):
            pass
    for k in v.get("torlendo_gyakorlatok") or []:
        try:
            torol.add(int(k) - 1)
        except (TypeError, ValueError):
            pass
    uj = [g for i, g in enumerate(uj) if i not in torol]
    jav = dict(adat)
    if isinstance(v.get("javitott_bevezeto"), str) and len(v["javitott_bevezeto"]) > 40:
        jav["bevezeto"] = v["javitott_bevezeto"]
    if isinstance(v.get("javitott_kartyak"), list) and v["javitott_kartyak"]:
        jav["kartyak"] = v["javitott_kartyak"]
    return uj, jav, hibak


def sakk_fen(x) -> str | None:
    return fen_tiszta(x.get("fen")) if isinstance(x, dict) and x.get("tipus") == "tabla" and x.get("fen") else None


def lecke_keszit(cid: str, idx: int) -> None:
    c = cel_olvas(cid)
    if str(idx) in c.get("leckek", {}):
        return   # ami egyszer elkészült, azt nem generáljuk újra (újat csak a „lecke_ujra” kér, ami előbb törli)
    ls = leckek_lista(c)
    l = ls[idx]
    db = max(6, min(12, round(int(c["perc"]) * 0.75)))
    kod = c["terv"].get("nyelv", "")
    nev = hangcsomag.NYELVEK.get(kod, "")
    if kod and kod not in ("en", "hu"):
        hangcsomag.biztosit(kod)   # legalább egy hangcsomag legyen a nyelvhez (ha már megvan vagy nemrég sikertelen volt, azonnal visszatér)
    en = bool(kod) and (kod == "en" or bool(hangcsomag.modell_nev(kod)))   # hallgat/mondd gyakorlat csak akkor, ha van a nyelvhez hang
    hallgat = ('{"tipus":"hallgat","kerdes":"Írd le, amit hallasz","szoveg":"rövid mondat a tanult nyelven","magyarazat":"…"}\n'
               '{"tipus":"mondd","kerdes":"Mondd ki hangosan!","szoveg":"rövid mondat a tanult nyelven (3-8 szó), amit a tanuló kimond","magyarazat":"kiejtési tipp magyarul"}\n'
               if en else "")
    nyelvi = (f"Ez nyelvtanulás: a tanult nyelv a(z) {nev}. A {nev} mondatok és szavak {nev} nyelven legyenek, a magyarázat magyarul; "
              + ("legyen 1-2 „hallgat” és 1-2 „mondd” (kimondós) gyakorlat is, és a " if en else "ne használj „hallgat” és „mondd” típust (ehhez a nyelvhez nincs hang), a ")
              + f"kártyák elöl {nev}, hátul magyar. A bevezetőben MINDEN {nev} szót/mondatot *dőlt* (csillag) jelöléssel írj, és dőlttel semmi mást ne.") if kod else "Nem nyelvtanulás: ne használj „hallgat” típust."
    elvetett, lektor_hibak = 0, []
    for _kiserlet in range(2):   # ha az ellenőrzések után túl kevés jó gyakorlat marad, egyszer újragenerálunk
        adat = claude_json(LECKE_PROMPT.format(
            cim=c["cim"], cel=c["cel"], szint=c["szint"], modul=l["modul"], sorszam=idx + 1, ossz=len(ls), lecke_cim=l["cim"],
            tema=l.get("tema", ""), kulcs=", ".join(l.get("kulcsfogalmak", [])) or "-",
            elozo="; ".join(x["cim"] for x in ls[max(0, idx - 4):idx]) or "ez az első lecke",
            gyenge="; ".join(gyenge_kartyak(c)) or "még nincs", perc=c["perc"], db=db, nyelvi=nyelvi, hallgat=hallgat, abra_leiras=ABRA_LEIRAS, miniapp_leiras=MINIAPP_LEIRAS, tanulsagok=tanulsag_szoveg(c)), MODELL, "low", timeout=420)
        gy = [g for g in adat.get("gyakorlatok", []) if isinstance(g, dict) and g.get("tipus") in ("teszt", "ird", "parosit", "rendez", "hallgat", "mondd", "tabla", "igazhamis", "kitolt", "hibakereso")]
        nyers = len(gy)
        gy = [g for g in gy if jo_gyakorlat(g, en)]
        for g in gy:  # a gyakorlatok ábrái: csak az ellenőrzött marad
            g["abra"] = abra_ell(g.get("abra")) if g.get("abra") else None
            if g["abra"] is None:
                g.pop("abra")
        gy = [abra_szur(g) for g in gy]
        elvetett += nyers - len(gy)
        if len(gy) >= 3 and LEKTOR:
            try:
                _T.munka = "lecke_lektor"
                try:
                    gy, jav, hibak = lecke_lektor(c, l, adat, gy, en)
                finally:
                    _T.munka = "lecke"
                lektor_hibak += hibak
                if jav:
                    adat = jav
            except Exception as e:  # noqa: BLE001 – a lektor hibája ne akadályozza a leckét
                lektor_hibak.append(f"(lektor-hiba: {str(e)[:80]})")
        if len(gy) >= 3:
            break
    minoseg_naplo(c, l, elvetett, lektor_hibak, len(gy))
    abrak = [x for x in (abra_ell(a) for a in (adat.get("abrak") or [])[:4]) if x]
    mi = adat.get("miniapp")
    miniapp = ({"cim": _sz(mi.get("cim"), 60), "miert": _sz(mi.get("miert"), 220), "meret": mi["meret"], "allapot": "javasolt"}
               if isinstance(mi, dict) and mi.get("cim") and mi.get("meret") in MINIAPP_MERETEK else None)
    if len(gy) < 3:
        raise RuntimeError("A lecke gyakorlatai használhatatlanok lettek, próbáld újra.")
    c = cel_olvas(cid)
    if str(idx) in c.get("leckek", {}):
        return   # közben már elkészült egy másik példány: azt tartjuk meg
    c.setdefault("leckek", {})[str(idx)] = {"bevezeto": adat.get("bevezeto", ""), "abrak": abrak, "gyakorlatok": gy,
                                             "kartyak": [k for k in adat.get("kartyak", []) if k.get("elol") and k.get("hatul")][:8], "miniapp": miniapp,
                                             "kesz": False, "keszult": datetime.now().isoformat(timespec="seconds")}
    ir(f"cel_{cid}.json", c)
    _szal_felh(elorenderel, aktualis(), cid, idx)
    if miniapp and MINIAPP_MERETEK.index(miniapp["meret"]) <= MINIAPP_MERETEK.index(MINIAPP_AUTO):
        try:   # a kicsi mini-alkalmazás megerősítés nélkül, a háttérben elkészül; a nagyobbaknál a tanulót kérdezzük
            munka_indit("miniapp", cid, miniapp_keszit, idx)
        except KeretHiba:
            pass


def _szavak_set(s: str) -> set:
    return set(re.findall(r"\w+", s.lower()))


def parosit_jo(g: dict) -> bool:
    """A párosító gyakorlat csak akkor jó, ha egyértelmű 1:1 párokból áll: nincs üres, ismétlődő vagy túl hasonló kártya."""
    p = g.get("parok")
    if not isinstance(p, list) or not 3 <= len(p) <= 6 or any(not isinstance(x, (list, tuple)) or len(x) != 2 for x in p):
        return False
    bal = [str(x[0] or "").strip() for x in p]
    jobb = [str(x[1] or "").strip() for x in p]
    if any(not s or len(s) > 90 for s in bal + jobb):
        return False
    for oldal in (bal, jobb):
        if len({s.lower() for s in oldal}) < len(oldal):
            return False
        for i in range(len(oldal)):  # nagyon hasonló szövegű kártyák → nem egyértelmű, melyik melyik párja
            for j in range(i + 1, len(oldal)):
                a, b = _szavak_set(oldal[i]), _szavak_set(oldal[j])
                if len(a) >= 3 and len(b) >= 3 and len(a & b) / len(a | b) > 0.6:
                    return False
    if {s.lower() for s in bal} & {s.lower() for s in jobb}:
        return False
    g["parok"] = [[b, j] for b, j in zip(bal, jobb)]
    return True


def jo_gyakorlat(g: dict, en: bool) -> bool:
    try:
        t = g["tipus"]
        if t == "teszt":
            v = [re.sub(r"\W+", " ", str(x).lower()).strip() for x in g["valaszok"]]
            return len(v) >= 2 and all(v) and len(set(v)) == len(v) and 0 <= int(g["helyes"]) < len(v) and bool(g["kerdes"])   # üres vagy ismétlődő válaszlehetőség → hibás
        if t == "ird":
            return bool(g["kerdes"]) and bool(str(g["valasz"]).strip())
        if t == "igazhamis":
            return isinstance(g["helyes"], bool) and bool(str(g["kerdes"]).strip()) and len(str(g["kerdes"])) <= 220
        if t == "kitolt":
            lv = [re.sub(r"\W+", " ", str(x).lower()).strip() for x in g["lehetosegek"]]
            va = re.sub(r"\W+", " ", str(g["valasz"]).lower()).strip()
            return str(g["mondat"]).count("___") == 1 and 3 <= len(lv) <= 5 and all(lv) and len(set(lv)) == len(lv) and va in lv   # a helyes szó szerepeljen, ne legyen ismétlődő opció
        if t == "hibakereso":
            sz = [str(x).strip() for x in g["szavak"]]
            return 3 <= len(sz) <= 14 and all(sz) and 0 <= int(g["helyes"]) < len(sz) and bool(str(g["javitas"]).strip()) and str(g["javitas"]).strip().lower() != sz[int(g["helyes"])].lower()
        if t == "parosit":
            return parosit_jo(g)
        if t == "rendez":
            return len(g["elemek"]) >= 3 and len(g["helyes"]) == len(g["elemek"])
        if t in ("hallgat", "mondd"):
            return en and bool(g["szoveg"]) and len(g["szoveg"]) <= 160
        if t == "tabla":
            g["fen"] = fen_tiszta(g.get("fen"))
            g["helyes"] = mezok(g.get("helyes"), 10)
            g["kiemel"] = mezok(g.get("kiemel"))
            if not (g["fen"] and g["kerdes"] and 1 <= len(g["helyes"])):
                return False
            # a helyes mezőket a KÓD számolja ki a „szabaly”-ból; ha a Claude állítása eltér, a gyakorlat kiesik (nem tanítunk hibásat)
            sz = g.get("szabaly")
            szamolt = sakk.szamol(g["fen"], sz) if isinstance(sz, dict) else None
            return szamolt is not None and szamolt == set(g["helyes"])
    except (KeyError, TypeError, ValueError):
        return False
    return False


# ---------------------------------------------------------------------------------------------------- háttérmunka
def _szal_felh(fn, slug: str, *args) -> None:
    def f():
        with felhasznalo(slug):
            fn(*args)
    threading.Thread(target=f, daemon=True).start()


def munka_indit(tipus: str, cid: str, fn, *args, suly: int = 1) -> str:
    # egy célhoz ugyanaz a munka nem indul kétszer
    for jid, m in MUNKAK.items():
        if m["tipus"] == tipus and m["cel"] == cid and m.get("args") == list(args) and m["allapot"] == "fut" and m.get("felh") == aktualis():
            return jid
    keret_fogyaszt(suly)   # vendégnél napi korlát (KeretHiba, ha elfogyott)
    jid, slug = uuid.uuid4().hex[:8], aktualis()
    MUNKAK[jid] = {"tipus": tipus, "cel": cid, "allapot": "fut", "hiba": "", "args": list(args), "kezdet": time.time(), "felh": slug}

    def futtat():
        _T.slug = slug
        _T.munka = tipus
        try:
            fn(cid, *args)
            MUNKAK[jid]["allapot"] = "kesz"
        except subprocess.TimeoutExpired:
            MUNKAK[jid].update(allapot="hiba", hiba="Túl sokáig tartott (időtúllépés). Próbáld újra.")
        except Exception as e:  # noqa: BLE001 – a hibát a felhasználó látja
            MUNKAK[jid].update(allapot="hiba", hiba=str(e)[:300])
        if tipus == "terv" and MUNKAK[jid]["allapot"] == "hiba":
            c = cel_olvas(cid)
            if c:
                c["allapot"] = "hiba"
                c["hiba"] = MUNKAK[jid]["hiba"]
                ir(f"cel_{cid}.json", c)
    threading.Thread(target=futtat, daemon=True).start()
    return jid


# ---------------------------------------------------------------------------------------------------- beosztás
def beosztas(c: dict) -> dict:
    """Mikor melyik lecke esedékes: a hátralévő leckék a tanulási napokra kerülnek, ma-tól (kiesés nem büntet, csak tolódik)."""
    ls = leckek_lista(c)
    kesz = {int(k) for k, v in c.get("leckek", {}).items() if v.get("kesz")}
    napok = set(tanulasi_napok(c))
    nap = ma()
    mai_kesz = any(v.get("kesz") and v.get("kesz_nap") == nap.isoformat() for v in c.get("leckek", {}).values())
    kov = [i for i in range(len(ls)) if i not in kesz]
    terv = {}
    d = nap + timedelta(days=1) if mai_kesz else nap
    for i in kov:
        while d.weekday() not in napok:
            d += timedelta(days=1)
        terv[i] = d.isoformat()
        d += timedelta(days=1)
    return {"datumok": terv, "kesz": sorted(kesz), "mai": kov[0] if kov and terv.get(kov[0]) == nap.isoformat() else None,
            "kovetkezo": kov[0] if kov else None, "mai_kesz": mai_kesz}


def esedekes_kartyak(c: dict, max_db: int = 6) -> list[dict]:
    mai = ma().isoformat()
    due = [{"id": k, **v} for k, v in c.get("kartyak", {}).items() if v.get("kovetkezo", "") <= mai]
    due.sort(key=lambda v: (v.get("kovetkezo", ""), -v.get("hibak", 0)))
    return due[:max_db]


def folyamat_info(c: dict) -> dict | None:
    """Félbehagyott lecke (bármelyik eszközről): hányadik lépésnél tart."""
    for k, v in c.get("leckek", {}).items():
        f = v.get("folyamat")
        if f and not v.get("kesz"):
            return {"lecke": int(k), "i": int(f.get("i", 0)), "ossz": 1 + len(f.get("esedekes") or []) + len(v.get("gyakorlatok", []))}
    return None


SZINEK = ["#2fd16b", "#5db8ff", "#ffc83d", "#ff7bb0", "#a78bfa", "#ff8f5a"]
NAP_BETU = ["H", "K", "Sz", "Cs", "P", "Sz", "V"]


def het_sor(c: dict, b: dict) -> list[dict]:
    """A hét 7 napja ehhez a tanfolyamhoz: mi volt kész, mi esedékes (a heti csíkhoz)."""
    h = ma() - timedelta(days=ma().weekday())
    kesz = {v.get("kesz_nap") for v in c.get("leckek", {}).values() if v.get("kesz")}
    terv = set(b["datumok"].values())
    out = []
    for i in range(7):
        d = (h + timedelta(days=i)).isoformat()
        out.append({"n": NAP_BETU[i], "kesz": d in kesz, "ter": d in terv, "ma": d == ma().isoformat()})
    return out


def cel_osszegzes(c: dict) -> dict:
    ls = leckek_lista(c)
    b = beosztas(c) if c.get("terv") else {"datumok": {}, "kesz": [], "mai": None, "kovetkezo": None, "mai_kesz": False}
    return {"id": c["id"], "cim": c["cim"], "emoji": c.get("emoji", "📘"), "allapot": c.get("allapot", "tervezes"), "hiba": c.get("hiba", ""),
            "lecke_ossz": len(ls), "lecke_kesz": len(b["kesz"]), "mai": b["mai"], "kovetkezo": b["kovetkezo"], "mai_kesz": b["mai_kesz"],
            "esedekes_kartya": len(esedekes_kartyak(c, 99)), "kartya_ossz": len(c.get("kartyak", {})),
            "kovetkezo_datum": b["datumok"].get(b["kovetkezo"]) if b["kovetkezo"] is not None else "",
            "szin": c.get("szin") or SZINEK[int(hashlib.sha1(c["id"].encode()).hexdigest(), 16) % len(SZINEK)],
            "het": het_sor(c, b), "folyamat": folyamat_info(c), "perc": c.get("perc", 10), "kovetkezo_cim": (leckek_lista(c)[b["kovetkezo"]]["cim"] if b["kovetkezo"] is not None and ls else "")}


def allapot() -> dict:
    p = profil()
    sz = szint_adat(p["xp"])
    mai = p["napi"].get(ma().isoformat(), {"xp": 0, "leckek": 0})
    return {"xp": p["xp"], **sz, "sorozat": hatso_sorozat(p), "fagyasztas": p["fagyasztas"], "mai": mai, "mai_xp_cel": 50, "beallitasok": p["beallitasok"],
            "jelzes_dontesek": [{"id": j["id"], "allapot": j["allapot"], "kerdes": j["kerdes"][:120], "felhasznalo": j["felhasznalo"], "megjegyzes": j.get("megjegyzes", "")} for j in jelzesek() if j["allapot"] != "uj" and not j.get("latta") and j.get("user", ADMIN_FELH) == aktualis()][:8],
            "vissza_valaszok": [{"id": x["id"], "allapot": x["allapot"], "szoveg": x["szoveg"][:100], "megjegyzes": x.get("megjegyzes", "")} for x in visszajelzesek() if x.get("user") == aktualis() and x["allapot"] in ("kesz", "elvetve") and x.get("megjegyzes") and not x.get("latta")][:6],
            "felhasznalo": {"az": aktualis(), **{k: v for k, v in (felh_meta(aktualis()) or {}).items() if k in ("nev", "emoji")}, "pin": bool((felh_meta(aktualis()) or {}).get("pin_hash")), "vendeg": aktualis() != ADMIN_FELH,
                             "vip": bool((felh_meta(aktualis()) or {}).get("vip")), "max_cel": felh_korlat()[0]}, "lan": lan_url(),
            "kituzok": [{"id": k, "emoji": KITUZOK[k][0], "nev": KITUZOK[k][1], "leiras": KITUZOK[k][2]} for k in p["kituzok"] if k in KITUZOK],
            "osszes_kituzo": [{"id": k, "emoji": v[0], "nev": v[1], "leiras": v[2], "megvan": k in p["kituzok"]} for k, v in KITUZOK.items()],
            "celok": [cel_osszegzes(c) for c in cel_lista()]}


# ---------------------------------------------------------------------------------------------------- eredmény
def kartya_id(elol: str) -> str:
    return hashlib.sha1(elol.strip().lower().encode()).hexdigest()[:10]


GY_STAT_ZAR = threading.Lock()


def gy_stat_frissit(cid: str, idx: int, er) -> None:
    """Feladatonkénti találati arány (admin-finomhangoláshoz): kulcs user|cél|lecke|gyakorlat → {t: típus, n: válaszok, j: helyesek}."""
    try:
        with GY_STAT_ZAR:
            st = olvas_g("gy_stat.json", {})
            for e in (er or [])[:80]:
                gi, t, jo = int(e[0]), str(e[1])[:12], bool(e[2])
                v = st.setdefault(f"{aktualis()}|{cid}|{idx}|{gi}", {"t": t, "n": 0, "j": 0})
                v["n"] += 1
                v["j"] += int(jo)
            ir_g("gy_stat.json", st)
    except (ValueError, TypeError, IndexError):
        pass


def lecke_kesz(cid: str, idx: int, adat: dict) -> dict:
    c = cel_olvas(cid)
    lk = c.get("leckek", {}).get(str(idx))
    if not lk:
        raise ValueError("Nincs ilyen lecke")
    p = profil()
    helyes = max(0, min(int(adat.get("helyes", 0)), 60))
    ossz = max(1, min(int(adat.get("osszes", 1)), 60))
    arany = helyes / ossz
    elso = not lk.get("kesz")  # újrajátszásnál nincs bónusz, csak gyakorlás
    # XP: helyes válaszok ×10, kombó-bónusz (kliens számolja, itt korlátozzuk), lecke-befejezés +20, hibátlan +30
    kombo = max(0, min(int(adat.get("kombo_bonusz", 0)), 40))
    xp = helyes * 10 + kombo
    if elso:
        xp += 20 + (30 if helyes == ossz else 0)
    else:
        xp = xp // 3
    # ismétlőkártyák
    uj_tanult = 0
    mai = ma()
    for k, ok in (adat.get("kartya_eredmeny") or {}).items():
        v = c.get("kartyak", {}).get(k)
        if not v:
            continue
        if ok:
            v["doboz"] = min(v.get("doboz", 1) + 1, len(DOBOZ_NAP) - 1)
            if v["doboz"] == 4:
                uj_tanult += 1  # a „megtanult” küszöb: a 4. doboz (8 nap)
        else:
            v["doboz"] = 1
            v["hibak"] = v.get("hibak", 0) + 1
        v["kovetkezo"] = (mai + timedelta(days=DOBOZ_NAP[v["doboz"]])).isoformat()
    xp += len(adat.get("kartya_eredmeny") or {}) * 3
    lk.pop("folyamat", None)
    if elso:
        gy_stat_frissit(cid, idx, adat.get("er"))
        lk["kesz"] = True
        lk["kesz_nap"] = mai.isoformat()
        lk["eredmeny"] = {"helyes": helyes, "osszes": ossz}
        for k in lk.get("kartyak", []):  # az új kártyák a ma-holnapi ismétlésbe kerülnek
            cid_ = kartya_id(k["elol"])
            c.setdefault("kartyak", {}).setdefault(cid_, {"elol": k["elol"], "hatul": k["hatul"], "doboz": 1, "hibak": 0,
                                                          "kovetkezo": (mai + timedelta(days=1)).isoformat()})
    visszatero = sorozat_frissit(p)
    regi_szint = szint_adat(p["xp"])["szint"]
    p["xp"] += xp
    napi = p["napi"].setdefault(mai.isoformat(), {"xp": 0, "leckek": 0})
    napi["xp"] += xp
    napi["leckek"] += 1
    p["napi"] = dict(sorted(p["napi"].items())[-60:])
    p["megtanult_kartya"] += uj_tanult
    uj = []
    def ad(k: str) -> None:
        if k not in p["kituzok"]:
            p["kituzok"].append(k)
            uj.append({"id": k, "emoji": KITUZOK[k][0], "nev": KITUZOK[k][1], "leiras": KITUZOK[k][2]})
    if elso:
        ad("elso")
        if helyes == ossz:
            ad("tokeletes")
    for n in (3, 7, 14, 30):
        if p["sorozat"] >= n:
            ad(f"s{n}")
    if p["megtanult_kartya"] >= 25:
        ad("k25")
    if p["megtanult_kartya"] >= 100:
        ad("k100")
    uj_szint = szint_adat(p["xp"])["szint"]
    if uj_szint >= 5:
        ad("szint5")
    if visszatero:
        ad("visszatero")
    ls = leckek_lista(c)
    if all(c["leckek"].get(str(i), {}).get("kesz") for i in range(len(ls))):
        ad("cel1")
        c["allapot"] = "befejezve"
    ir(f"cel_{cid}.json", c)
    ir("profil.json", p)
    # a következő leckét a háttérben előkészítjük, hogy holnap azonnal induljon
    b = beosztas(c)
    if b["kovetkezo"] is not None and str(b["kovetkezo"]) not in c["leckek"]:
        try:
            munka_indit("lecke", cid, lecke_keszit, b["kovetkezo"])
        except KeretHiba:
            pass   # vendégnél a következő lecke csak a keret erejéig készül előre
    return {"xp": xp, "arany": round(arany, 2), "uj_szint": uj_szint if uj_szint > regi_szint else None, "kituzok": uj,
            "sorozat": p["sorozat"], "allapot": allapot()}


# ---------------------------------------------------------------------------------------------------- HTTP
class Kezelo(BaseHTTPRequestHandler):
    server_version = "Tanoda"

    def log_message(self, *a):  # némán
        pass

    def kuld(self, adat, kod: int = 200, tipus: str = "application/json; charset=utf-8", gyorsitotar: bool = False) -> None:
        torzs = adat if isinstance(adat, bytes) else json.dumps(adat, ensure_ascii=False).encode()
        self.send_response(kod)
        self.send_header("Content-Type", tipus)
        self.send_header("Content-Length", str(len(torzs)))
        self.send_header("Cache-Control", "max-age=604800" if gyorsitotar else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in getattr(self, "_fej", []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(torzs)

    def azonosit(self) -> str | None:
        """A kérés felhasználója az aláírt sütiből (csak létező profil)."""
        try:
            v = SimpleCookie(self.headers.get("Cookie", "")).get("tanoda_u")
        except Exception:  # noqa: BLE001
            return None
        slug = suti_slug(v.value) if v else None
        return slug if slug and felh_meta(slug) else None

    def suti_be(self, slug: str | None) -> None:
        biztonsagos = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        ertek = suti_alair(slug) if slug else ""
        self._fej = [("Set-Cookie", f"tanoda_u={ertek}; Path=/; Max-Age={31536000 if slug else 0}; HttpOnly; SameSite=Lax{biztonsagos}")]

    def torzs(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 200_000:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def origin_ok(self) -> bool:
        o = self.headers.get("Origin")
        if not o:
            return True
        return urlparse(o).netloc == self.headers.get("Host")

    def do_GET(self):
        u = urlparse(self.path)
        try:
            if u.path == "/" or u.path == "/index.html":
                return self.kuld((WEB / "index.html").read_bytes(), tipus="text/html; charset=utf-8")
            if u.path in ("/manifest.json", "/ikon.svg", "/sw.js", "/maskot3d.js"):
                tipusok = {".json": "application/manifest+json", ".svg": "image/svg+xml", ".js": "text/javascript"}
                f = WEB / u.path[1:]
                return self.kuld(f.read_bytes(), tipus=tipusok[f.suffix] + "; charset=utf-8")
            if u.path == "/admin":
                k = parse_qs(u.query).get("k", [""])[0]
                if not hmac.compare_digest(k, admin_token()):
                    return self.kuld(b"tiltott", 403, "text/plain; charset=utf-8")
                mind = parse_qs(u.query).get("mind", [""])[0] == "1"
                of = parse_qs(u.query).get("oldal", ["attekintes"])[0]
                if of == "vissza":
                    oldal = admin_vissza_oldal(mind)
                elif of == "jelzes":
                    oldal = admin_oldal(mind)
                else:
                    try:
                        ora = int(parse_qs(u.query).get("ora", ["24"])[0])
                    except ValueError:
                        ora = 24
                    oldal = admin_dash.oldal(of, admin_adatok(max(1, min(ora, 168))), admin_token(), max(1, min(ora, 168)))
                return self.kuld(oldal.encode(), tipus="text/html; charset=utf-8")
            if u.path == "/api/profilok":
                return self.kuld({"profilok": felh_lista(), "max": 12})
            slug = self.azonosit()
            if not slug:
                return self.kuld({"hiba": "Belépés szükséges", "belepes": True}, 401)
            _T.slug = slug
            if u.path == "/api/allapot":
                return self.kuld(allapot())
            if m := re.fullmatch(r"/api/cel/([a-z0-9]+)/miniapp/(\d+)", u.path):
                c = cel_olvas(m.group(1))
                mi = ((c or {}).get("leckek", {}).get(m.group(2)) or {}).get("miniapp")
                if not mi:
                    return self.kuld({"hiba": "nincs ilyen mini-alkalmazás"}, 404)
                ki = {"allapot": mi.get("allapot"), "hiba": mi.get("hiba", "")}
                if parse_qs(u.query).get("html") and mi.get("allapot") == "kesz":
                    f = miniapp_fajl(m.group(1), int(m.group(2)))
                    ki["html"] = f.read_text(encoding="utf-8") if f.exists() else ""
                return self.kuld(ki)
            if m := re.fullmatch(r"/api/cel/([a-z0-9]+)", u.path):
                c = cel_olvas(m.group(1))
                if not c:
                    return self.kuld({"hiba": "Nincs ilyen tanulnivaló"}, 404)
                b = beosztas(c) if c.get("terv") else None
                if b:
                    kovetkezo_elore(aktualis(), c, b)
                kut = {k: v for k, v in c.items() if k != "leckek"}
                kut["hang_info"] = hangcsomag.info(c["terv"]["nyelv"]) if c.get("terv", {}).get("nyelv") not in ("", "en", "hu", None) else None
                kut["leckek_allapot"] = {k: {"kesz": v.get("kesz", False), "eredmeny": v.get("eredmeny")} for k, v in c.get("leckek", {}).items()}
                return self.kuld({"cel": kut, "beosztas": b, "osszegzes": cel_osszegzes(c)})
            if m := re.fullmatch(r"/api/munka/([a-f0-9]+)", u.path):
                j = MUNKAK.get(m.group(1))
                j = j if j and j.get("felh") == slug else None
                return self.kuld({"allapot": j["allapot"], "hiba": j["hiba"], "mp": round(time.time() - j["kezdet"])} if j else
                                 {"allapot": "ismeretlen"}, 200 if j else 404)
            if u.path == "/api/tts":
                q = parse_qs(u.query)
                return self.tts(q.get("t", [""])[0], q.get("h", ["en"])[0], q.get("v", [""])[0])
        except Exception as e:  # noqa: BLE001
            return self.kuld({"hiba": str(e)[:300]}, 500)
        self.kuld({"hiba": "nincs ilyen oldal"}, 404)

    def tts(self, szoveg: str, h: str = "en", v: str = "") -> None:
        szoveg = szoveg.strip()[:300]
        if not szoveg or (h != "hu" and h not in hangcsomag.NYELVEK):
            return self.kuld({"hiba": "üres"}, 400)
        f = tts_fajl(szoveg, h, v)
        if isinstance(f, str):
            return self.kuld({"hiba": f}, 500)
        self.kuld(f.read_bytes(), tipus="audio/mp4", gyorsitotar=True)

    def do_POST(self):
        if not self.origin_ok():
            return self.kuld({"hiba": "tiltott eredet"}, 403)
        u = urlparse(self.path)
        if u.path not in ("/api/belep", "/api/kilep", "/api/admin/dontes", "/api/admin/visszajelzes"):
            slug = self.azonosit()
            if not slug:
                return self.kuld({"hiba": "Belépés szükséges", "belepes": True}, 401)
            _T.slug = slug
        if u.path == "/api/beszed":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if not 500 < n < 3_000_000:
                    return self.kuld({"hiba": "Túl rövid vagy túl hosszú felvétel."}, 400)
                cel = parse_qs(u.query).get("t", [""])[0][:200]
                if not cel.strip():
                    return self.kuld({"hiba": "Hiányzik a célmondat."}, 400)
                return self.kuld(beszed_ertekel(self.rfile.read(n), cel, parse_qs(u.query).get("l", ["en"])[0]))
            except RuntimeError as e:
                return self.kuld({"hiba": str(e)}, 500)
            except subprocess.TimeoutExpired:
                return self.kuld({"hiba": "Túl sokáig tartott a felismerés."}, 500)
        adat = self.torzs()
        try:
            if u.path == "/api/belep":
                ip = self.client_address[0]
                hibak = PIN_HIBAK.get(ip, [0, 0])
                if hibak[0] >= 5 and time.time() - hibak[1] < 600:
                    return self.kuld({"hiba": "Túl sok hibás PIN, próbáld 10 perc múlva."}, 429)
                if adat.get("az"):
                    meta = felh_meta(str(adat["az"]))
                    if not meta:
                        return self.kuld({"hiba": "Nincs ilyen profil."}, 404)
                    if not pin_jo(meta, str(adat.get("pin", ""))):
                        PIN_HIBAK[ip] = [hibak[0] + 1, time.time()]
                        return self.kuld({"hiba": "Hibás PIN.", "pin": True}, 403)
                    PIN_HIBAK.pop(ip, None)
                    slug_be = str(adat["az"])
                else:
                    slug_be = felh_letrehoz(str(adat.get("nev", "")), str(adat.get("emoji", "")), str(adat.get("pin", "")))
                self.suti_be(slug_be)
                return self.kuld({"ok": True, "az": slug_be})
            if u.path == "/api/kilep":
                self.suti_be(None)
                return self.kuld({"ok": True})
            if u.path == "/api/pin":
                meta = felh_meta(aktualis())
                if meta.get("pin_hash") and not pin_jo(meta, str(adat.get("regi", ""))):
                    return self.kuld({"hiba": "A jelenlegi PIN hibás."}, 403)
                uj = str(adat.get("uj", ""))
                if uj:
                    if not re.fullmatch(r"\d{4,8}", uj):
                        return self.kuld({"hiba": "A PIN 4-8 számjegy legyen."}, 400)
                    meta["so"] = uuid.uuid4().hex
                    meta["pin_hash"] = pin_hash(pin_norm(uj), meta["so"])
                else:
                    meta.pop("pin_hash", None)
                    meta.pop("so", None)
                meta_ment(aktualis(), meta)
                return self.kuld({"ok": True})
            if u.path == "/api/beallitas":
                p = profil()
                for k, t in (("sfx", bool), ("auto", bool), ("nemit", bool)):
                    if k in adat:
                        p["beallitasok"][k] = bool(adat[k])
                if adat.get("motor") in ("auto", "szerver", "bongeszo"):
                    p["beallitasok"]["motor"] = adat["motor"]
                if adat.get("kabala") in ("dino", "lapi"):
                    p["beallitasok"]["kabala"] = adat["kabala"]
                for k, ok in (("huHang", HU_HANGOK), ("enHang", EN_HANGOK)):
                    if adat.get(k) in ok:
                        p["beallitasok"][k] = adat[k]
                for k in ("bHu", "bEn"):
                    if isinstance(adat.get(k), str):
                        p["beallitasok"][k] = adat[k][:120]
                em = adat.get("emlekezteto")
                if isinstance(em, dict) and re.fullmatch(r"\d\d:\d\d", str(em.get("ido", ""))) and int(em["ido"][:2]) < 24 and int(em["ido"][3:]) < 60:
                    p["beallitasok"]["emlekezteto"] = {"be": bool(em.get("be")), "ido": em["ido"]}
                    if em.get("be"):  # ma már elmúlt időnél ne szóljon azonnal: a mai nap lezárva
                        most = datetime.now().hour * 60 + datetime.now().minute
                        if int(em["ido"][:2]) * 60 + int(em["ido"][3:]) < most:
                            ir("emlekezteto.json", {"utolso": ma().isoformat()})
                if isinstance(adat.get("seb"), (int, float)) and 0.5 <= adat["seb"] <= 1.5:
                    p["beallitasok"]["seb"] = adat["seb"]
                ir("profil.json", p)
                return self.kuld({"ok": True})
            if u.path == "/api/jelzes/latta":
                with JELZES_ZAR:
                    lista = jelzesek()
                    for j in lista:
                        if j["allapot"] != "uj" and j.get("user", ADMIN_FELH) == aktualis():
                            j["latta"] = True
                    ir_g("jelzesek.json", lista)
                with JELZES_ZAR:
                    vl = visszajelzesek()
                    for x in vl:
                        if x.get("user") == aktualis() and x["allapot"] in ("kesz", "elvetve"):
                            x["latta"] = True
                    ir_g("visszajelzesek.json", vl)
                return self.kuld({"ok": True})
            if u.path == "/api/visszajelzes":
                e = visszajelzes_felvesz(str(adat.get("kategoria", "")), str(adat.get("szoveg", "")), adat.get("kontextus"))
                return self.kuld({"ok": True, "id": e["id"]})
            if u.path == "/api/admin/visszajelzes":
                if not hmac.compare_digest(self.headers.get("X-Admin", ""), admin_token()):
                    return self.kuld({"hiba": "tiltott"}, 403)
                e = visszajelzes_allapot(str(adat.get("id", "")), str(adat.get("allapot", "")), str(adat.get("megjegyzes", "")))
                return self.kuld({"ok": True, "allapot": e["allapot"]})
            if u.path == "/api/admin/dontes":
                if not hmac.compare_digest(self.headers.get("X-Admin", ""), admin_token()):
                    return self.kuld({"hiba": "tiltott"}, 403)
                j = jelzes_dontes(str(adat.get("id", "")), str(adat.get("dontes", "")), str(adat.get("megjegyzes", "")))
                return self.kuld({"ok": True, "allapot": j["allapot"]})
            if u.path == "/api/emlekezteto/proba":
                hiba = ntfy_kuld(emlekezteto_szoveg(True))
                return self.kuld({"ok": not hiba, "hiba": hiba or ""})
            if u.path == "/api/cel":
                if aktualis() != ADMIN_FELH and len(cel_lista()) >= felh_korlat()[0]:
                    return self.kuld({"hiba": f"Ezzel a profillal legfeljebb {felh_korlat()[0]} tanfolyamot vihetsz egyszerre. Törölhetsz egyet, hogy újat vegyél fel."}, 403)
                cim = str(adat.get("cim", "")).strip()[:200]
                if not cim:
                    return self.kuld({"hiba": "Írd be, mit szeretnél megtanulni."}, 400)
                cid = uuid.uuid4().hex[:8]
                c = {"id": cid, "cim": cim, "cel": str(adat.get("cel", "")).strip()[:500] or cim,
                     "szint": str(adat.get("szint", "kezdő"))[:100], "perc": max(5, min(int(adat.get("perc", 10)), 60)),
                     "nap_hetente": max(1, min(int(adat.get("nap_hetente", 5)), 7)), "hetek": max(2, min(int(adat.get("hetek", 4)), 8)),
                     "megjegyzes": str(adat.get("megjegyzes", ""))[:500], "emoji": str(adat.get("emoji", "📘"))[:4] or "📘",
                     "allapot": "tervezes", "letrehozva": ma().isoformat(), "leckek": {}, "kartyak": {}, "anyagok": [],
                     "szin": SZINEK[len(cel_lista()) % len(SZINEK)]}
                ir(f"cel_{cid}.json", c)
                return self.kuld({"id": cid, "munka": munka_indit("terv", cid, terv_keszit)})
            if m := re.fullmatch(r"/api/cel/([a-z0-9]+)/(ujraterv|anyag|lecke|kesz|torol|folyamat|bovit|jelzes|miniapp|miniapp_kesz|lecke_ujra)", u.path):
                cid, mit = m.groups()
                c = cel_olvas(cid)
                if not c:
                    return self.kuld({"hiba": "Nincs ilyen tanulnivaló"}, 404)
                if mit == "ujraterv":
                    c["allapot"] = "tervezes"
                    c.pop("hiba", None)
                    ir(f"cel_{cid}.json", c)
                    return self.kuld({"munka": munka_indit("terv", cid, terv_keszit)})
                if mit == "torol":
                    f = felh_dir() / f"cel_{cid}.json"
                    f.rename(f.with_suffix(".torolt"))
                    return self.kuld({"ok": True})
                if not c.get("terv"):
                    return self.kuld({"hiba": "A terv még nem készült el."}, 400)
                if mit == "lecke_ujra":
                    idx = int(adat.get("lecke", -1))
                    lk = c.get("leckek", {}).get(str(idx))
                    if not lk or lk.get("kesz") or lk.get("folyamat"):
                        return self.kuld({"hiba": "Csak olyan lecke kérhető újra, amit még nem kezdtél el."}, 400)
                    c["leckek"].pop(str(idx))
                    ir(f"cel_{cid}.json", c)
                    miniapp_fajl(cid, idx).unlink(missing_ok=True)
                    return self.kuld({"ok": True})
                if mit == "miniapp":
                    idx = int(adat.get("lecke", -1))
                    lk = c.get("leckek", {}).get(str(idx))
                    m = (lk or {}).get("miniapp")
                    if not m:
                        return self.kuld({"hiba": "Ehhez a leckéhez nincs mini-alkalmazás."}, 400)
                    if adat.get("dontes") == "nem":
                        miniapp_allapot(cid, idx, "elutasitva")
                        return self.kuld({"ok": True})
                    if m.get("allapot") == "keszul":
                        return self.kuld({"ok": True})
                    miniapp_allapot(cid, idx, "keszul")
                    try:
                        return self.kuld({"ok": True, "munka": munka_indit("miniapp", cid, miniapp_keszit, idx, suly=1 if m["meret"] == "kicsi" else 4)})
                    except KeretHiba:
                        miniapp_allapot(cid, idx, "javasolt")
                        raise
                if mit == "miniapp_kesz":
                    idx = int(adat.get("lecke", -1))
                    m = (c.get("leckek", {}).get(str(idx)) or {}).get("miniapp")
                    if not m or m.get("allapot") != "kesz" or m.get("jutalom"):
                        return self.kuld({"ok": True, "xp": 0})
                    m["jutalom"] = True
                    ir(f"cel_{cid}.json", c)
                    p = profil()
                    p["xp"] += 25
                    napi = p["napi"].setdefault(ma().isoformat(), {"xp": 0, "leckek": 0})
                    napi["xp"] += 25
                    ir("profil.json", p)
                    return self.kuld({"ok": True, "xp": 25})
                if mit == "jelzes":
                    j = jelzes_felvesz(cid, int(adat.get("lecke", -1)), int(adat.get("gy", -1)), str(adat.get("valasz", "")))
                    return self.kuld({"ok": True, "id": j["id"]})
                if mit == "bovit":
                    hetek = max(2, min(int(adat.get("hetek", 4)), 8))
                    return self.kuld({"munka": munka_indit("bovit", cid, terv_bovit, hetek, str(adat.get("fokusz", ""))[:300])})
                if mit == "anyag":
                    return self.kuld({"munka": munka_indit("anyag", cid, anyag_keszit)})
                if mit == "lecke":
                    b = beosztas(c)
                    idx = adat.get("lecke")
                    fi = folyamat_info(c)
                    idx = (fi["lecke"] if fi else b["kovetkezo"]) if idx is None else int(idx)
                    if idx is None:
                        return self.kuld({"hiba": "Minden lecke kész!"}, 400)
                    lk = c.get("leckek", {}).get(str(idx))
                    if lk:
                        return self.kuld({"kesz": True, "lecke": idx, "tartalom": {**lk, "gyakorlatok": [abra_szur(g) for g in lk.get("gyakorlatok", [])]}, "cim": leckek_lista(c)[idx]["cim"],
                                          "esedekes": esedekes_kartyak(c) if not lk.get("kesz") else [], "nyelv": c["terv"].get("nyelv", ""),
                                          "szegmensek": beszed_szegmensek(lk.get("bevezeto", ""), c["terv"].get("nyelv", "")),
                                          "folyamat": None if lk.get("kesz") else lk.get("folyamat")})
                    return self.kuld({"kesz": False, "lecke": idx, "munka": munka_indit("lecke", cid, lecke_keszit, idx)})
                if mit == "folyamat":
                    idx = int(adat.get("lecke", -1))
                    lk = c.get("leckek", {}).get(str(idx))
                    if not lk or lk.get("kesz"):
                        return self.kuld({"ok": False})
                    kr = {str(k): bool(v) for k, v in list((adat.get("kr") or {}).items())[:20]}
                    es = [{"id": str(e["id"]), "elol": str(e["elol"])[:300], "hatul": str(e["hatul"])[:300]} for e in (adat.get("esedekes") or [])[:8]]
                    lk["folyamat"] = {"i": max(0, min(int(adat.get("i", 0)), 80)), "helyes": max(0, min(int(adat.get("helyes", 0)), 60)),
                                      "osszes": max(0, min(int(adat.get("osszes", 0)), 60)), "kombo": max(0, min(int(adat.get("kombo", 0)), 60)),
                                      "max_kombo": max(0, min(int(adat.get("max_kombo", 0)), 60)), "bonusz": max(0, min(int(adat.get("bonusz", 0)), 40)),
                                      "kr": kr, "esedekes": es, "mikor": datetime.now().isoformat(timespec="seconds"),
                                      "sorrend": [str(x)[:24] for x in (adat.get("sorrend") or [])[:80]], "hangulat": str(adat.get("hangulat") or "")[:10]}
                    ir(f"cel_{cid}.json", c)
                    return self.kuld({"ok": True})
                if mit == "kesz":
                    return self.kuld(lecke_kesz(cid, int(adat.get("lecke", -1)), adat))
        except KeretHiba as e:
            return self.kuld({"hiba": str(e)}, 429)
        except (ValueError, TypeError, KeyError) as e:
            return self.kuld({"hiba": f"Hibás kérés: {e}"}, 400)
        except Exception as e:  # noqa: BLE001
            return self.kuld({"hiba": str(e)[:300]}, 500)
        self.kuld({"hiba": "nincs ilyen"}, 404)


# ---------------------------------------------------------------------------------------------------- admin dashboard adatai
def _jsonl(nev: str) -> list[dict]:
    ki = []
    try:
        for sor in (ADAT / nev).read_text(encoding="utf-8").splitlines():
            try:
                ki.append(json.loads(sor))
            except ValueError:
                pass
    except OSError:
        pass
    return ki


def admin_adatok(ora: int = 24) -> dict:
    """Minden, amit az admin-dashboard megjelenít (csak olvas, AI-hívás nélkül)."""
    ma_s, het = ma().isoformat(), (ma() - timedelta(days=6)).isoformat()
    kolt = _jsonl("koltseg.jsonl")
    kk = {"ossz_usd": 0.0, "ma_usd": 0.0, "het_usd": 0.0, "hivas": len(kolt), "user": {}, "munka": {}}
    napi: dict[str, float] = {}
    for r in kolt:
        u = float(r.get("usd") or 0)
        nap = str(r.get("ido", ""))[:10]
        kk["ossz_usd"] += u
        kk["ma_usd"] += u if nap == ma_s else 0
        kk["het_usd"] += u if nap >= het else 0
        napi[nap] = napi.get(nap, 0) + u
        if r.get("user"):
            kk["user"][r["user"]] = kk["user"].get(r["user"], 0) + u
        kk["munka"][r.get("munka") or "egyeb"] = kk["munka"].get(r.get("munka") or "egyeb", 0) + u
    kk["napok"] = [((ma() - timedelta(days=i)).isoformat(), napi.get((ma() - timedelta(days=i)).isoformat(), 0.0)) for i in range(13, -1, -1)]
    felh = []
    gen_ossz = 0
    for f in felh_lista():
        with felhasznalo(f["az"]):
            m = felh_meta(f["az"]) or {}
            p = profil()
            celok = [x for x in (felh_dir().glob("cel_*.json"))]
            kesz = gen = 0
            for cf in celok:
                try:
                    lk = json.loads(cf.read_text(encoding="utf-8")).get("leckek", {})
                except (OSError, ValueError):
                    continue
                gen += len(lk)
                kesz += sum(1 for v in lk.values() if v.get("kesz"))
            gen_ossz += gen
            keret_p = (p.get("beallitasok") or {}).get("keret") or {}
            felh.append({"az": f["az"], "nev": f["nev"], "emoji": f["emoji"], "vip": bool(m.get("vip")), "xp": p.get("xp", 0), "szint": szint_adat(p.get("xp", 0))["szint"],
                         "sorozat": p.get("sorozat", 0), "utolso_nap": p.get("utolso_nap") or "", "celok": len(celok), "leckek_kesz": kesz, "leckek_gen": gen,
                         "keret_ma": keret_p.get("db", 0) if keret_p.get("nap") == ma_s else 0, "napi_limit": m.get("napi") or felh_korlat()[1] if f["az"] != ADMIN_FELH else 0,
                         "usd": kk["user"].get(f["az"], 0.0),
                         "napi7": [((ma() - timedelta(days=i)).isoformat()[5:], (p.get("napi") or {}).get((ma() - timedelta(days=i)).isoformat(), {}).get("xp", 0)) for i in range(6, -1, -1)]})
    lecke_usd = sum(v for n, v in kk["munka"].items() if n in ("lecke", "lecke_lektor"))
    kk["lecke_becsles"] = not lecke_usd
    kk["lecke_ar"] = (lecke_usd or kk["ossz_usd"]) / gen_ossz if gen_ossz else 0.0
    # minőség
    mq = _jsonl("minoseg.jsonl")
    lekt = [x for x in mq if x.get("lektor")]
    minoseg = {"n": len(mq), "elvetett_atlag": sum(x.get("elvetett", 0) for x in mq) / max(1, len(mq)), "lektor_db": len(lekt), "lektor_arany": 100 * len(lekt) / max(1, len(mq)),
               "utolso_lektor": list(reversed(lekt[-8:]))}
    # feladat-statisztika
    st = olvas_g("gy_stat.json", {})
    tip: dict[str, list[int]] = {}
    gyanus = []
    for kulcs, v in st.items():
        tip.setdefault(v["t"], [0, 0])
        tip[v["t"]][0] += v["n"]
        tip[v["t"]][1] += v["j"]
        if v["n"] >= 3 and v["j"] / v["n"] <= 0.35:
            try:
                az, cid, li, gi = kulcs.split("|")
                with felhasznalo(az):
                    c = cel_olvas(cid) or {}
                    lk = c.get("leckek", {}).get(li, {})
                    g = lk.get("gyakorlatok", [])[int(gi)]
                    cim = c.get("cim", cid)
                    lecke_cim = (leckek_lista(c)[int(li)]["cim"] if c.get("terv") else "")
                gyanus.append({"user": az, "cim": cim, "lecke": lecke_cim, "t": v["t"], "kerdes": str(g.get("kerdes") or g.get("mondat") or g.get("szoveg") or "")[:110], "arany": 100 * v["j"] / v["n"], "n": v["n"]})
            except (ValueError, IndexError, KeyError, TypeError):
                continue
    gyanus.sort(key=lambda x: (x["arany"], -x["n"]))
    vj, jz = visszajelzesek(), jelzesek()
    minta = admin_dash.minta_olvas(ADAT, ora)
    m24 = admin_dash.minta_olvas(ADAT, 24)
    return {"ma": ma_s, "het_eleje": het, "admin": ADMIN_FELH, "felh": felh, "kolt": kk, "minoseg": minoseg, "gy": {"tipusok": {k: tuple(v) for k, v in tip.items()}, "gyanus": gyanus[:20]},
            "tanulsag": len(olvas_g("tanulsagok.json", [])), "vissza": {"nyitott": sum(1 for x in vj if x["allapot"] in ("uj", "folyamatban")), "ossz": len(vj)},
            "jelzes": {"nyitott": sum(1 for x in jz if x["allapot"] == "uj"), "ossz": len(jz)}, "minta": minta, "magok": os.cpu_count() or 1,
            "rendszer": {"van": bool(m24), "cpu_atlag": sum(r["cpu"] for r in m24) / max(1, len(m24)), "cpu_csucs": max([r["cpu"] for r in m24] or [0]),
                         "mem_csucs": max([r["mem"] for r in m24] or [0]), "temp_csucs": max([r["temp"] for r in m24 if r.get("temp") is not None] or [0])}}


# ---------------------------------------------------------------------------------------------------- napi emlékeztető
def ntfy_kuld(szoveg: str) -> str | None:
    """Emlékeztető a telefonra (ntfy). TANODA_NTFY_SZARAZ=1: csak naplózza (teszthez)."""
    if os.environ.get("TANODA_NTFY_SZARAZ"):
        with (ADAT / "ntfy_log.txt").open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} | {szoveg}\n")
        return None
    import ntfy
    return ntfy.kuld(szoveg, cim="Tanoda", prioritas=3, cimkek=("seedling",), kattintas=APP_URL)


def emlekezteto_szoveg(proba: bool = False) -> str | None:
    """Mit írjon az emlékeztető? None, ha nincs mire emlékeztetni (már kész a mai tanulás / nincs lecke)."""
    a = allapot()
    aktiv = [c for c in a["celok"] if c["allapot"] == "kesz"]
    maiak = [c for c in aktiv if c["mai"] is not None and not c["mai_kesz"]]
    kartya = sum(c["esedekes_kartya"] for c in aktiv)
    kesz_ma = a["mai"]["leckek"] > 0
    if proba:
        return "Ez egy próba-értesítés. Így fog szólni a napi emlékeztető – rákoppintva megnyílik a Tanoda. 🌱"
    if not maiak and not (kartya and not kesz_ma):
        return None
    if maiak:
        perc = sum(c["perc"] for c in maiak)
        nevek = ", ".join(c["cim"] for c in maiak[:3])
        szoveg = (f"Ma {len(maiak)} lecke vár ({nevek}), kb. {perc} perc." if len(maiak) > 1 else f"Ma egy lecke vár: {nevek}, kb. {perc} perc.")
    else:
        szoveg = f"{kartya} ismétlőkártya vár – pár perc, és frissen marad, amit tanultál."
    if a["sorozat"] > 0 and not kesz_ma:
        szoveg += f" 🔥 {a['sorozat']} napos a sorozatod, ne szakadjon meg!"
    return szoveg


def emlekezteto_figyelo() -> None:
    """Percenként nézi: elérkezett-e a beállított idő; naponta legfeljebb egyszer küld, és csak ha van mire emlékeztetni."""
    while True:
        try:
            if not (FELH_MAPPA / ADMIN_FELH).exists():
                time.sleep(30)
                continue
            _T.slug = ADMIN_FELH   # az ntfy Illés telefonjára megy: csak az ő profiljának emlékeztetője
            e = (profil().get("beallitasok") or {}).get("emlekezteto") or {}
            allj = olvas("emlekezteto.json", {})
            if e.get("be") and re.fullmatch(r"\d\d:\d\d", str(e.get("ido", ""))) and allj.get("utolso") != ma().isoformat():
                hh, mm = map(int, e["ido"].split(":"))
                most = datetime.now().hour * 60 + datetime.now().minute
                if hh * 60 + mm <= most < hh * 60 + mm + 120:  # ha a szerver később indul, legfeljebb 2 órát késik
                    ir("emlekezteto.json", {"utolso": ma().isoformat()})
                    if szoveg := emlekezteto_szoveg():
                        hiba = ntfy_kuld(szoveg)
                        ir("emlekezteto.json", {"utolso": ma().isoformat(), "hiba": hiba or ""})
        except Exception as ex:  # noqa: BLE001 – a figyelő sosem állhat le
            print("emlékeztető hiba:", ex, flush=True)
        time.sleep(30)


def admin_oldal(mind: bool) -> str:
    """Egyszerű admin-nézet a jelzésekről (token kell hozzá): egyenként elbírálható. Minden szöveg escape-elt."""
    e = htmlmod.escape
    lista = [j for j in reversed(jelzesek()) if mind or j["allapot"] == "uj"]
    kartyak = []
    for j in lista:
        gomb = "" if j["allapot"] != "uj" else (f'<input id="m{j["id"]}" placeholder="megjegyzés (opcionális)"><div><button onclick="d(\'{j["id"]}\',\'elfogad\')">✅ Elfogad</button> '
                                                f'<button onclick="d(\'{j["id"]}\',\'elutasit\')">❌ Elutasít</button></div>')
        kartyak.append(f'''<div class="k {e(j["allapot"])}"><b>{e(j.get("user", ADMIN_FELH))}</b> · <b>{e(j["cel_cim"])}</b> · {e(j["lecke_cim"])} · <small>{e(j["ido"])} · {j.get("db", 1)}×</small> <span class="b">{e(j["allapot"])}</span>
<p><b>Kérdés:</b> {e(j["kerdes"])}</p><p><b>Várt válasz:</b> {e(str(j["helyes"]))}</p><p><b>Elfogadott eddig:</b> {e(", ".join(j["elfogad"]) or "–")}</p>
<p><b>A tanuló válasza:</b> <mark>{e(j["felhasznalo"])}</mark></p><p><small>Magyarázat: {e(j.get("magyarazat", ""))}</small></p>
{('<p><small>Megjegyzés: ' + e(j["megjegyzes"]) + '</small></p>') if j.get("megjegyzes") else ""}{gomb}</div>''')
    return f'''<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Tanoda – jelzések</title>
<style>body{{font:15px system-ui;max-width:760px;margin:0 auto;padding:12px;background:#f2f8f4;color:#14281d}}.k{{background:#fff;border:1px solid #c5d9cc;border-radius:12px;padding:12px;margin:10px 0}}
.k.elfogadva{{border-color:#22b85c}}.k.elutasitva{{border-color:#e0443e}}.b{{float:right;background:#e6f1ea;border-radius:8px;padding:1px 8px}}mark{{background:#fff3b0}}p{{margin:.35em 0}}
button{{padding:8px 14px;border-radius:9px;border:0;background:#22b85c;color:#fff;font-weight:700;margin:4px 6px 0 0}}button+button{{background:#e0443e}}input{{width:100%;padding:8px;margin-top:6px;box-sizing:border-box}}</style>
<h2>🚩 Tanoda – kivizsgálandó jelzések</h2><p><a href="?k={e(admin_token())}">📊 Dashboard</a> · <b>🚩 Jelzések</b> · <a href="?k={e(admin_token())}&oldal=vissza">💬 Visszajelzések ({sum(1 for x in visszajelzesek() if x["allapot"] == "uj")} új)</a> · <a href="?k={e(admin_token())}&oldal=jelzes">Csak az újak</a> · <a href="?k={e(admin_token())}&oldal=jelzes&mind=1">Mind</a> · {len(lista)} tétel</p>{"".join(kartyak) or "<p>Nincs tétel. 🎉</p>"}
<script>const K=new URLSearchParams(location.search).get("k");async function d(id,x){{const r=await fetch("/api/admin/dontes",{{method:"POST",headers:{{"Content-Type":"application/json","X-Admin":K}},body:JSON.stringify({{id,dontes:x,megjegyzes:(document.getElementById("m"+id)||{{}}).value||""}})}});if(r.ok)location.reload();else alert("Hiba")}}</script>'''


def admin_vissza_oldal(mind: bool) -> str:
    """Az admin-nézet a tanulók visszajelzéseiről (token kell hozzá). Minden szöveg escape-elt."""
    e = htmlmod.escape
    lista = [x for x in reversed(visszajelzesek()) if mind or x["allapot"] in ("uj", "folyamatban")]
    kartyak = []
    for x in lista:
        kont = " · ".join(f"{e(k)}: {e(v)}" for k, v in x.get("kontextus", {}).items())
        gomb = (f'<input id="m{x["id"]}" placeholder="megjegyzés a tanulónak (opcionális)" value="{e(x.get("megjegyzes", ""))}"><div>'
                f'<button class="f" onclick="d(\'{x["id"]}\',\'folyamatban\')">🛠 Folyamatban</button> <button class="g" onclick="d(\'{x["id"]}\',\'kesz\')">✅ Kész</button> '
                f'<button class="r" onclick="d(\'{x["id"]}\',\'elvetve\')">❌ Elvetve</button></div>')
        kartyak.append(f'''<div class="k {e(x["allapot"])}"><b>{e(KATEGORIAK.get(x["kategoria"], x["kategoria"]))}</b> · <b>{e(x["user"])}</b> · <small>{e(x["ido"])}</small> <span class="b">{e(x["allapot"])}</span>
<p style="white-space:pre-wrap">{e(x["szoveg"])}</p><p><small>{kont}</small></p>{gomb}</div>''')
    tok = e(admin_token())
    return f'''<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Tanoda – visszajelzések</title>
<style>body{{font:15px system-ui;max-width:760px;margin:0 auto;padding:12px;background:#f2f8f4;color:#14281d}}.k{{background:#fff;border:1px solid #c5d9cc;border-radius:12px;padding:12px;margin:10px 0}}
.k.kesz{{border-color:#22b85c}}.k.elvetve{{border-color:#999;opacity:.75}}.k.folyamatban{{border-color:#f5b400}}.b{{float:right;background:#e6f1ea;border-radius:8px;padding:1px 8px}}p{{margin:.35em 0}}
button{{padding:8px 12px;border-radius:9px;border:0;color:#fff;font-weight:700;margin:4px 6px 0 0;background:#888}}button.g{{background:#22b85c}}button.r{{background:#e0443e}}button.f{{background:#d99a00}}input{{width:100%;padding:8px;margin-top:6px;box-sizing:border-box}}</style>
<h2>💬 Tanoda – visszajelzések</h2><p><a href="?k={tok}">📊 Dashboard</a> · <a href="?k={tok}&oldal=jelzes">🚩 Jelzések</a> · <b>💬 Visszajelzések</b> · <a href="?k={tok}&oldal=vissza">Aktív</a> · <a href="?k={tok}&oldal=vissza&mind=1">Mind</a> · {len(lista)} tétel</p>{"".join(kartyak) or "<p>Nincs tétel. 🎉</p>"}
<script>const K=new URLSearchParams(location.search).get("k");async function d(id,x){{const r=await fetch("/api/admin/visszajelzes",{{method:"POST",headers:{{"Content-Type":"application/json","X-Admin":K}},body:JSON.stringify({{id,allapot:x,megjegyzes:(document.getElementById("m"+id)||{{}}).value||""}})}});if(r.ok)location.reload();else alert("Hiba")}}</script>'''


def main() -> None:
    migral()
    threading.Thread(target=emlekezteto_figyelo, daemon=True).start()
    admin_dash.mintavetel_indit(ADAT)
    srv = ThreadingHTTPServer((BIND, PORT), Kezelo)
    print(f"Tanoda fut: http://{BIND}:{PORT} (házi hálózat: {lan_url()})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
