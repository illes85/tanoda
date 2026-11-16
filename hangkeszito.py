"""Közös hangkészítés: szöveg -> hangfájl az agent saját hangján (Piper helyben, ffmpeg effektekkel).
A bot (Telegram-hangüzenetek) és az Irányítópult (HQ-s csevej) is ezt használja. Claude-ot nem hív, tokenbe nem kerül."""
import json
import re
import subprocess
from pathlib import Path

ITT = Path(__file__).resolve().parent
PIPER = ITT / "venv" / "bin" / "piper"

# a Piper hangja halk: a hangüzeneteket a telefonon megszokott szintre hozza (loudnorm, -16 LUFS)
HANGOSITAS = "loudnorm=I=-16:TP=-1.5:LRA=11"
# robothang (FELOLVAS_HANG=robot): Imre hangja magasabban, kicsit lassítva, remegtetve és visszhanggal – kis robot
ROBOT_SZURO = "asetrate=22050*1.18,aresample=22050,atempo=0.85,tremolo=f=45:d=0.55,aecho=0.8:0.65:10:0.45"
# ...és retro sci-fi csipogás előtte (felfelé szökő hangok) és utána (lefelé): a beszédre ráteszi a robotszűrőt, elé-mögé csippanásokat fűz
_CSIP = "sine=f={f}:d={d},volume={v},afade=t=out:st={st}:d=0.02,aformat=sample_rates=22050:channel_layouts=mono"
ROBOT_CSIPOGAS_NYERS = (
    ";".join(f"{_CSIP.format(f=f, d=d, st=round(d - 0.02, 2), v=0.9)}[e{i}]" for i, (f, d) in enumerate([(1300, 0.06), (2000, 0.06), (1600, 0.09)]))
    + ";anullsrc=r=22050:cl=mono,atrim=duration=0.15[csend]"
    + f";[0:a]{ROBOT_SZURO},aformat=sample_rates=22050:channel_layouts=mono[besz]"
    + ";anullsrc=r=22050:cl=mono,atrim=duration=0.12[csend2]"
    + ";" + ";".join(f"{_CSIP.format(f=f, d=d, st=round(d - 0.02, 2), v=0.6)}[u{i}]" for i, (f, d) in enumerate([(1900, 0.06), (1400, 0.07), (900, 0.14)]))
    + ";[e0][e1][e2][csend][besz][csend2][u0][u1][u2]concat=n=9:v=0:a=1"
)
ROBOT_CSIPOGAS = ROBOT_CSIPOGAS_NYERS + "," + HANGOSITAS


def ffmpeg_exe() -> str | None:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        import shutil
        return shutil.which("ffmpeg")


def _env_ertek(fajl: Path, kulcs: str) -> str | None:
    try:
        m = re.search(rf"^{kulcs}=(.*)$", fajl.read_text(encoding="utf-8"), re.M)
        return m.group(1).strip().strip("\"'") if m else None
    except OSError:
        return None


def agent_hang(mappa: str) -> str:
    """Az agent hangja: imre (férfi), anna / berta (női) vagy robot; az agent.env, aztán a közös .env FELOLVAS_HANG-ja."""
    for f in (ITT / mappa / "agent.env", ITT / ".env"):
        if (h := _env_ertek(f, "FELOLVAS_HANG")):
            return h
    return "imre"


# Hangulat (FELOLVAS_HANGULAT az agent.env-ben): a Piper hangja alapból elég lapos, ezért a beszéd változatosságát (noise), tempóját és
# magasságát/élénkségét (ffmpeg) állítjuk. Valódi érzelmet a Piper nem tud, de ezzel sokkal élénkebb lesz.
HANGULATOK = {
    # név: (hangtempó-szorzó [<1 gyorsabb], zaj, hangszínváltozatosság, hangmagasság-szorzó, pluszszűrő)
    "vidam": (0.94, 0.80, 1.00, 1.03, "treble=g=2:f=4000"),
    "lelkes": (0.88, 0.95, 1.15, 1.07, "treble=g=3:f=4000,acompressor=threshold=-22dB:ratio=3:attack=5:release=90:makeup=3"),
    # Vili: mélyebb tónus, kapkodó, okoskodó tempó (a szöveg okoskodó stílusát az agent írja, itt csak a hang)
    "vili": (0.86, 0.90, 1.08, 0.93, "bass=g=3:f=150,treble=g=1:f=4000"),
    "vili2": (0.80, 0.95, 1.12, 0.90, "bass=g=4:f=140,treble=g=2:f=4000,acompressor=threshold=-24dB:ratio=3:attack=5:release=70:makeup=3"),
    "pergos": (0.90, 0.85, 1.05, 1.05, "treble=g=2:f=4000"),
    "extralelkes": (0.82, 1.00, 1.12, 1.10, "treble=g=3:f=4000,acompressor=threshold=-24dB:ratio=4:attack=4:release=80:makeup=4"),
    "melyebb": (1.00, 0.70, 0.90, 0.92, "bass=g=3:f=150"),
    "radios": (0.95, 0.80, 0.90, 0.95, "bass=g=4:f=120,treble=g=1,acompressor=threshold=-20dB:ratio=3:attack=5:release=90:makeup=3"),
    # Berci: fiatal2 gyorsabban, rövid mondatközi szünetekkel – pörgős, lendületes kis menedzser
    "berci": (0.76, 0.95, 1.10, 1.11, "treble=g=3:f=4000,acompressor=threshold=-24dB:ratio=3:attack=5:release=70:makeup=4"),
    "berci2": (0.70, 0.95, 1.10, 1.12, "treble=g=4:f=4000,acompressor=threshold=-26dB:ratio=4:attack=4:release=60:makeup=5"),
    "fiatal2": (0.85, 0.95, 1.15, 1.11, "treble=g=3:f=4000,acompressor=threshold=-22dB:ratio=3:attack=5:release=80:makeup=3"),
    "fiatal3": (0.82, 1.00, 1.12, 1.15, "treble=g=4:f=4000,acompressor=threshold=-24dB:ratio=4:attack=4:release=80:makeup=4"),
    "lendulet": (0.80, 1.00, 1.12, 1.08, "treble=g=3:f=3800,acompressor=threshold=-26dB:ratio=5:attack=3:release=70:makeup=5"),
    "fiatal": (0.88, 0.90, 1.10, 1.08, "treble=g=2:f=4000"),
    "nyugodt": (1.08, 0.55, 0.70, 0.97, ""),
    # Klippa reklámhangja (2026-11-12): nagyon lelkes, élénk, kicsit gyorsabb, erős kompresszióval (a hangsúlyok kiemelkednek)
    "reklam": (0.80, 1.00, 1.18, 1.10, "treble=g=4:f=4000,acompressor=threshold=-24dB:ratio=4:attack=4:release=70:makeup=5"),
}


def _elo_szuro(hangulat: str = "") -> str:
    """A hangulat szerinti magasság/élénkség lánca a hangosítás nélkül (üres: nincs változtatás)."""
    h = HANGULATOK.get(hangulat)
    if not h:
        return "anull"
    elemek = []
    if h[3] != 1:
        elemek.append(f"asetrate=22050*{h[3]},aresample=22050,atempo={1 / h[3]:.4f}")
    if h[4]:
        elemek.append(h[4])
    return ",".join(elemek) or "anull"


MONDATSZUNET = {"reklam": 0.08, "lelkes": 0.15, "extralelkes": 0.12, "berci": 0.06, "vili": 0.06, "vili2": 0.04, "berci2": 0.04, "lendulet": 0.06}


def agent_hangulat(mappa: str) -> str:
    for f in (ITT / mappa / "agent.env", ITT / ".env"):
        if (h := _env_ertek(f, "FELOLVAS_HANGULAT")):
            return h
    return ""


def _alap_tempo() -> float:
    try:
        return max(50, min(150, int(json.loads((ITT / "beallitasok.json").read_text(encoding="utf-8")).get("beszed_tempo", 100)))) / 100
    except Exception:
        return 1.0


def piper_args(hangulat: str = "") -> list[str]:
    """A Piper kapcsolói: tempó az Irányítópultról, hangulat szerint módosítva."""
    h = HANGULATOK.get(hangulat)
    hossz = (1 / _alap_tempo()) * (h[0] if h else 1)
    return ["--length_scale", f"{hossz:.2f}", *(["--noise-scale", str(h[1]), "--noise-w", str(h[2])] if h else []),
            *(["--sentence-silence", str(MONDATSZUNET[hangulat])] if hangulat in MONDATSZUNET else [])]


def szuro(hangulat: str = "") -> str:
    """Az ffmpeg -af lánca (nem robothangra): hangulat szerinti magasság/élénkség, aztán hangosítás."""
    h = HANGULATOK.get(hangulat)
    if not h:
        return HANGOSITAS
    elemek = []
    if h[3] != 1:
        elemek.append(f"asetrate=22050*{h[3]},aresample=22050,atempo={1 / h[3]:.4f}")
    if h[4]:
        elemek.append(h[4])
    return ",".join(elemek + [HANGOSITAS])


# Kiejtés-javítás: a Piper egyes szavakat félrehall(gat); ilyenkor a beszéd előtt hangzás szerint írjuk át (pl. a „szia" j-hangját kiírjuk).
KIEJTES = [(re.compile(r"\b([Ss])zia(sz|stok|sztok|sztok)?\b"), r"\1zija\2"), (re.compile(r"\bSzió\b"), "Szijó")]


def kiejtes(szoveg: str) -> str:
    for minta, csere in KIEJTES:
        szoveg = minta.sub(csere, szoveg)
    return szoveg


def _wav_masodperc(wav: Path) -> float:
    import wave
    try:
        with wave.open(str(wav)) as w:
            return w.getnframes() / w.getframerate()
    except Exception:
        return 0.0


# angol hangok (Tanoda): név → Piper-modell
ANGOL_HANGOK = {"angol": "en_US-lessac-medium", "lessac": "en_US-lessac-medium", "amy": "en_US-amy-medium",
                "ryan": "en_US-ryan-medium", "alba": "en_GB-alba-medium"}


def szintetizal(szoveg: str, hang: str, ki: Path, formatum: str = "m4a", hangulat: str = "") -> str | None:
    """A szöveget felolvassa a megadott hangon a `ki` fájlba (m4a = AAC, minden böngésző lejátssza). Hiba esetén a hibaszöveg."""
    ffmpeg = ffmpeg_exe()
    if not ffmpeg:
        return "nincs ffmpeg"
    idegen_modell = hang[2:] if hang.startswith("m:") and re.fullmatch(r"[\w.-]{3,60}", hang[2:]) else None   # Tanoda: telepített nyelvi hangcsomag
    angol = hang in ANGOL_HANGOK or bool(idegen_modell)  # idegen nyelv: Piper-hang, a magyar kiejtés-javító szótár nélkül
    modell = ITT / "hangmodellek" / (idegen_modell + ".onnx" if idegen_modell else ANGOL_HANGOK[hang] + ".onnx" if angol else f"hu_HU-{'imre' if hang == 'robot' else hang}-medium.onnx")
    if not modell.exists():
        modell = ITT / "hangmodellek" / "hu_HU-imre-medium.onnx"
    wav, nyers = ki.with_suffix(".tmp.wav"), ki.with_suffix(".nyers.wav")
    try:
        args = piper_args(hangulat)
        hossz_szorzo = float(args[args.index("--length_scale") + 1])
        for _proba in range(3):  # a Piper néha véletlenül elnyújt egy hangot („húúú"): ilyenkor újrakészítjük
            p = subprocess.run([str(PIPER), "-m", str(modell), *args, "-f", str(wav)], input=(szoveg if angol else kiejtes(szoveg)).encode(),
                               capture_output=True, timeout=180)
            if p.returncode != 0:
                return "piper: " + p.stderr.decode(errors="ignore")[-200:]
            if _wav_masodperc(wav) <= len(szoveg) * 0.07 * hossz_szorzo * 1.35 + 0.8:
                break
        # 1. hatások (hangulat / robothang) -> nyers hang; 2. hangosság mérése; 3. fix erősítés + csendes bevezető/lezáró + kódolás.
        # A kétmenetes (linear) loudnorm azért kell, mert az egymenetes az elején visszafogja a hangot, és a beszéd eleje „elveszett".
        elo = ["-filter_complex", ROBOT_CSIPOGAS_NYERS] if hang == "robot" else ["-af", _elo_szuro(hangulat)]
        f = subprocess.run([ffmpeg, "-loglevel", "error", "-y", "-i", str(wav), *elo, "-ar", "22050", "-ac", "1", str(nyers)],
                           capture_output=True, timeout=180)
        if f.returncode != 0:
            return "ffmpeg: " + f.stderr.decode(errors="ignore")[-200:]
        meres = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", str(nyers), "-af", HANGOSITAS + ":print_format=json", "-f", "null", "-"],
                               capture_output=True, timeout=180).stderr.decode(errors="ignore")
        hangositas = HANGOSITAS
        if (m := re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", meres, re.S)):
            try:
                x = json.loads(m.group(0))
                hangositas = (f"{HANGOSITAS}:measured_I={x['input_i']}:measured_TP={x['input_tp']}:measured_LRA={x['input_lra']}"
                              f":measured_thresh={x['input_thresh']}:offset={x['target_offset']}:linear=true")
            except (ValueError, KeyError):
                pass
        kodek = ["-c:a", "aac", "-b:a", "48k"] if formatum == "m4a" else ["-c:a", "libopus", "-b:a", "32k"]
        # 0,35 mp csend az elején (a telefon / böngésző hangkimenete ébredés közben lenyeli a legelejét), 0,25 mp a végén
        f = subprocess.run([ffmpeg, "-loglevel", "error", "-y", "-i", str(nyers), "-af", f"adelay=350:all=1,{hangositas},apad=pad_dur=0.25",
                            "-ar", "48000", "-ac", "1", *kodek, str(ki)], capture_output=True, timeout=180)
        if f.returncode != 0:
            return "ffmpeg: " + f.stderr.decode(errors="ignore")[-200:]
    finally:
        wav.unlink(missing_ok=True)
        nyers.unlink(missing_ok=True)
    return None


# Bemondás előtti csengő (négy hang, kb. 1,2 mp): a botban és az Irányítópult felolvasásánál is ugyanez szól
BEMONDAS_CSENGO_SZURO = ";".join(
    f"sine=f={f}:d={d},afade=t=out:st={round(d - 0.16, 2)}:d=0.16,volume=0.9[n{i}]"
    for i, (f, d) in enumerate([(784, 0.22), (988, 0.22), (1175, 0.22), (1568, 0.55)])
) + ";[n0][n1][n2][n3]concat=n=4:v=0:a=1,aformat=sample_rates=48000"


def bemondas_csengo_fajl() -> Path | None:
    """A csengő útvonala (egyszer készül el, utána a .hangcache-ből jön); None, ha nincs ffmpeg vagy hiba van."""
    csengo = ITT / ".hangcache" / "bemondas_csengo.wav"
    if csengo.exists():
        return csengo
    ffmpeg = ffmpeg_exe()
    if not ffmpeg:
        return None
    csengo.parent.mkdir(exist_ok=True)
    try:
        ok = subprocess.run([ffmpeg, "-loglevel", "error", "-y", "-filter_complex", BEMONDAS_CSENGO_SZURO, "-ar", "48000",
                             str(csengo)], timeout=60).returncode == 0
    except Exception:
        ok = False
    return csengo if ok else None
