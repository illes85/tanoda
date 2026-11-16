#!/usr/bin/env python3
"""Tanoda – nyelvi hangcsomagok (Piper): a tanult nyelvhez megkeresi a legtermészetesebbnek ígérkező hangot, letölti és nyilvántartja.
Nyelvtanulásnál (nem magyar, nem angol) a rendszer ezt automatikusan intézi: a Piper nyilvános hangkatalógusából (rhasspy/piper-voices)
a legjobb minőségű, lehetőleg egybeszélős, ismerten jó hangot választja. Ha nincs ilyen hang, a böngésző/eszköz saját hangja a tartalék.
Használat: venv/bin/python tanoda/hangcsomag.py <nyelvkód> [keres]   (pl. de; a „keres” csak kiírja a választást, nem tölt le)"""
import json
import re
import sys
import threading
import time
import urllib.request
from pathlib import Path

ITT = Path(__file__).resolve().parent.parent
MODELLEK = ITT / "hangmodellek"
KATALOG = MODELLEK / "_katalogus.json"
ALLAPOT = MODELLEK / "nyelvi_hangok.json"
ALAP_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
ZAR = threading.Lock()

NYELVEK = {"en": "angol", "de": "német", "fr": "francia", "es": "spanyol", "it": "olasz", "pt": "portugál", "nl": "holland", "pl": "lengyel", "ru": "orosz",
           "uk": "ukrán", "cs": "cseh", "sk": "szlovák", "ro": "román", "sv": "svéd", "no": "norvég", "da": "dán", "fi": "finn", "tr": "török", "el": "görög",
           "ar": "arab", "zh": "kínai", "ja": "japán", "ko": "koreai", "hi": "hindi", "ca": "katalán", "bg": "bolgár", "sl": "szlovén", "sr": "szerb", "lt": "litván",
           "lv": "lett", "et": "észt", "is": "izlandi", "he": "héber", "fa": "perzsa", "vi": "vietnámi", "th": "thai", "id": "indonéz", "sw": "szuahéli", "cy": "walesi"}
MINOSEG = {"x_low": 0, "low": 1, "medium": 2, "high": 3}
# ismerten természetesen hangzó (és egybeszélős) hangok nyelvenként – csak bónusz a választásnál, a katalógus dönti el, léteznek-e
KEDVENC = {"de": ["thorsten"], "fr": ["siwis", "tom"], "es": ["davefx", "sharvard", "carlfm"], "it": ["riccardo", "paola"], "pt": ["faber", "edresson", "tugao"],
           "nl": ["nathalie", "pim"], "pl": ["gosia", "darkman"], "ru": ["irina", "denis", "dmitri"], "uk": ["lada"], "cs": ["jirka"], "sv": ["nst"],
           "da": ["talesyntese"], "fi": ["harri"], "tr": ["dfki", "fahrettin"], "el": ["rapunzelina"], "ca": ["upc_ona"], "ro": ["mihai"], "sk": ["lili"],
           "no": ["talesyntese"], "zh": ["huayan"], "ar": ["kareem"]}


ELSODLEGES_REGIO = {"es": "ES", "pt": "PT", "fr": "FR", "de": "DE", "it": "IT", "nl": "NL", "pl": "PL", "ru": "RU", "ar": "JO", "zh": "CN", "sv": "SE", "no": "NO"}


def nyelv_kod(x) -> str:
    k = str(x or "").strip().lower()[:2]
    return k if k in NYELVEK else ""


def _olvas(f: Path, alap):
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return alap


def katalogus() -> dict:
    """A Piper hangkatalógusa (hetente frissül, helyben gyorsítótárazva)."""
    if KATALOG.exists() and time.time() - KATALOG.stat().st_mtime < 7 * 86400:
        k = _olvas(KATALOG, None)
        if k:
            return k
    try:
        with urllib.request.urlopen(ALAP_URL + "voices.json", timeout=60) as r:
            adat = json.loads(r.read().decode())
        MODELLEK.mkdir(exist_ok=True)
        KATALOG.write_text(json.dumps(adat), encoding="utf-8")
        return adat
    except Exception:  # noqa: BLE001
        return _olvas(KATALOG, {})


def legjobb(kod: str) -> dict | None:
    """A nyelv legtermészetesebbnek ígérkező hangja: minőség, egybeszélős, ismert jó hang, lehetőleg a „fő” régió."""
    jeloltek = []
    for key, x in katalogus().items():
        if x.get("language", {}).get("family") != kod:
            continue
        pont = MINOSEG.get(x.get("quality"), 0) * 100
        pont += 30 if x.get("name") in KEDVENC.get(kod, []) else 0
        ns = x.get("num_speakers", 1)
        pont += 10 if ns == 1 else (-50 if ns > 20 else 0)
        pont += 120 if x["language"].get("region", "") == ELSODLEGES_REGIO.get(kod) else 0   # a tanulónak az európai/alap kiejtés a hasznos
        jeloltek.append((pont, key, x))
    return max(jeloltek, key=lambda t: t[0])[2] if jeloltek else None


def modell_nev(kod: str) -> str | None:
    """A telepített hangmodell neve (vagy None)."""
    a = _olvas(ALLAPOT, {}).get(kod)
    if a and a.get("allapot") == "kesz" and (MODELLEK / f"{a['modell']}.onnx").exists() and (MODELLEK / f"{a['modell']}.onnx.json").exists():
        return a["modell"]
    return None


def info(kod: str) -> dict:
    a = _olvas(ALLAPOT, {}).get(kod) or {}
    if a.get("allapot") == "kesz" and not modell_nev(kod):
        return {"allapot": ""}
    return {"allapot": a.get("allapot", ""), "nev": a.get("nev", ""), "minoseg": a.get("minoseg", ""), "hiba": a.get("hiba", "")}


def _ment(kod: str, adat: dict) -> None:
    allj = _olvas(ALLAPOT, {})
    allj[kod] = adat
    ALLAPOT.write_text(json.dumps(allj, ensure_ascii=False, indent=1), encoding="utf-8")


def _letolt(rel: str, cel: Path) -> None:
    tmp = cel.with_suffix(cel.suffix + ".part")
    with urllib.request.urlopen(ALAP_URL + rel, timeout=60) as r, tmp.open("wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(cel)


def biztosit(kod: str, csak_keres: bool = False) -> dict:
    """Gondoskodik arról, hogy a nyelvhez legyen hangcsomag: kész → azonnal visszatér; különben keres, letölt, nyilvántartásba vesz.
    Sikertelen próbálkozás után 6 óráig nem próbálja újra. Visszaad: info()."""
    kod = nyelv_kod(kod)
    if not kod or kod in ("hu", "en"):
        return {"allapot": "kesz" if kod == "en" else ""}
    with ZAR:
        if modell_nev(kod):
            return info(kod)
        a = _olvas(ALLAPOT, {}).get(kod) or {}
        if a.get("allapot") == "nincs" and time.time() - a.get("ido", 0) < 6 * 3600 and not csak_keres:
            return info(kod)
        v = legjobb(kod)
        if not v:
            if not csak_keres:
                _ment(kod, {"allapot": "nincs", "ido": time.time(), "hiba": "nincs ilyen nyelvű hang a katalógusban"})
            return {"allapot": "nincs", "hiba": "nincs ilyen nyelvű hang a katalógusban"}
        nev = f"{v['name'].replace('_', ' ').title()} ({NYELVEK.get(kod, kod)}, {v['quality']} minőség)"
        if csak_keres:
            return {"allapot": "talalt", "modell": v["key"], "nev": nev}
        _ment(kod, {"allapot": "keszul", "modell": v["key"], "nev": nev, "minoseg": v["quality"], "ido": time.time()})
        try:
            MODELLEK.mkdir(exist_ok=True)
            for rel in v["files"]:
                if rel.endswith(".onnx") or rel.endswith(".onnx.json"):
                    _letolt(rel, MODELLEK / Path(rel).name)
            if (MODELLEK / f"{v['key']}.onnx").stat().st_size < 1_000_000:
                raise RuntimeError("a letöltött hangmodell hibás")
            _ment(kod, {"allapot": "kesz", "modell": v["key"], "nev": nev, "minoseg": v["quality"], "ido": time.time()})
        except Exception as e:  # noqa: BLE001
            _ment(kod, {"allapot": "nincs", "ido": time.time(), "hiba": str(e)[:150]})
        return info(kod)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    print(json.dumps(biztosit(sys.argv[1], csak_keres=sys.argv[2:] == ["keres"]), ensure_ascii=False))
