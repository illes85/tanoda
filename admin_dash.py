"""Tanoda admin dashboard: laptop-terhelés mérése (háttérszál) és az admin-oldal megjelenítése.
Csak standard könyvtár; az adatokat a szerver.py gyűjti (admin_adatok), ez csak kirajzolja. Minden szöveg escape-elt."""
import html
import json
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

APP_NEV = "Tanoda"          # ide jön majd a végleges név
MINTA_MP = 60               # a laptop-terhelés mintavétele (másodperc)
MEGTART_SOR = 11000         # kb. 7 nap
e = html.escape


# ------------------------------------------------------------------------------------------ laptop-terhelés mérése
def _olvas(f: str) -> str:
    try:
        return Path(f).read_text()
    except OSError:
        return ""


def _cpu_ido() -> tuple[int, int]:
    v = [int(x) for x in _olvas("/proc/stat").split("\n")[0].split()[1:9]]
    return sum(v), v[3] + v[4]          # összes, tétlen (idle + iowait)


def _hom() -> float | None:
    ts = []
    for f in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            t = int(f.read_text()) / 1000
            if 0 < t < 130:
                ts.append(t)
        except (OSError, ValueError):
            pass
    return round(max(ts), 1) if ts else None


def _akku() -> tuple[int | None, str]:
    for b in Path("/sys/class/power_supply").glob("BAT*"):
        try:
            return int((b / "capacity").read_text()), (b / "status").read_text().strip()
        except (OSError, ValueError):
            pass
    return None, ""


def _claude_db() -> int:
    n = 0
    for d in Path("/proc").iterdir():
        if d.name.isdigit():
            try:
                a = (d / "cmdline").read_bytes().split(b"\0")
                if a and a[0].endswith((b"claude", b"/claude")) and b"-p" in a:
                    n += 1
            except OSError:
                pass
    return n


def egy_minta(elozo: tuple[int, int] | None) -> tuple[dict, tuple[int, int]]:
    ossz, tet = _cpu_ido()
    cpu = round(100 * (1 - (tet - elozo[1]) / max(1, ossz - elozo[0])), 1) if elozo else 0.0
    m = {k: int(v.split()[0]) for k, v in (l.split(":", 1) for l in _olvas("/proc/meminfo").splitlines() if ":" in l)}
    mem = round(100 * (1 - m.get("MemAvailable", 0) / max(1, m.get("MemTotal", 1))), 1)
    swap = round(100 * (1 - m.get("SwapFree", 0) / m["SwapTotal"]), 1) if m.get("SwapTotal") else 0.0
    du = shutil.disk_usage("/home")
    l1, l5 = [float(x) for x in _olvas("/proc/loadavg").split()[:2]]
    akku, akku_all = _akku()
    rss = 0
    for sor in _olvas("/proc/self/status").splitlines():
        if sor.startswith("VmRSS"):
            rss = int(sor.split()[1]) // 1024
    return ({"t": int(time.time()), "cpu": cpu, "l1": l1, "l5": l5, "mem": mem, "swap": swap, "disk": round(100 * du.used / du.total, 1),
             "temp": _hom(), "bat": akku, "toltes": akku_all == "Charging", "claude": _claude_db(), "rss": rss}, (ossz, tet))


def mintavetel_indit(adat: Path) -> None:
    """Háttérszál: percenként egy mérési sor az adat/rendszer.jsonl-be (kb. 7 napot tart meg)."""
    fajl = adat / "rendszer.jsonl"

    def ciklus() -> None:
        elozo, db = None, 0
        while True:
            try:
                minta, elozo = egy_minta(elozo)
                if db > 0:   # az első minta CPU-ja még nem értelmes
                    with fajl.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(minta) + "\n")
                db += 1
                if db % 360 == 0 and fajl.exists():     # óránként: a régi sorok levágása
                    sorok = fajl.read_text(encoding="utf-8").splitlines()
                    if len(sorok) > MEGTART_SOR:
                        fajl.write_text("\n".join(sorok[-MEGTART_SOR:]) + "\n", encoding="utf-8")
            except Exception:  # noqa: BLE001 – a mérés soha ne állítsa meg a szervert
                pass
            time.sleep(MINTA_MP)
    threading.Thread(target=ciklus, daemon=True, name="rendszer-mintavetel").start()


def minta_olvas(adat: Path, ora: float) -> list[dict]:
    f = adat / "rendszer.jsonl"
    if not f.exists():
        return []
    hatar, ki = time.time() - ora * 3600, []
    for sor in f.read_text(encoding="utf-8").splitlines()[-MEGTART_SOR:]:
        try:
            r = json.loads(sor)
            if r["t"] >= hatar:
                ki.append(r)
        except (ValueError, KeyError):
            pass
    return ki


# ------------------------------------------------------------------------------------------ diagramok (SVG, egy sorozat / diagram, nincs kettős tengely)
def _szep_max(v: float) -> float:
    for k in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000):
        if v <= k:
            return k
    return v


def vonal(minta: list[dict], kulcs: str, egyseg: str, szin: str, fix_max: float | None = None, ora: float = 24) -> str:
    """Időbeli vonaldiagram, a pontokra állva tooltip (title). A hiányzó értékű mintákat kihagyja."""
    pontok = [(r["t"], r[kulcs]) for r in minta if r.get(kulcs) is not None]
    if len(pontok) < 2:
        return '<div class="ures">Még kevés mérési adat – percenként gyűlik.</div>'
    N = 180   # legfeljebb ennyi pont: a sűrű mintákat átlagoljuk, a csúcsot a tooltip mutatja
    if len(pontok) > N:
        k = len(pontok) / N
        csoportok = [pontok[int(i * k):int((i + 1) * k)] for i in range(N)]
        pontok = [(cs[len(cs) // 2][0], sum(v for _, v in cs) / len(cs), max(v for _, v in cs)) for cs in csoportok if cs]
    else:
        pontok = [(t, v, v) for t, v in pontok]
    mx = fix_max or _szep_max(max(p[2] for p in pontok) * 1.1)
    W, H, L, R, T, B = 640, 170, 38, 10, 10, 24
    t1 = time.time()
    t0 = t1 - ora * 3600   # a kért időablak (az üres rész azt jelzi, hogy arra az időre még nincs mérés)
    x = lambda t: L + (t - t0) / max(1, t1 - t0) * (W - L - R)     # noqa: E731
    y = lambda v: T + (1 - min(v, mx) / mx) * (H - T - B)           # noqa: E731
    rács = "".join(f'<line x1="{L}" x2="{W - R}" y1="{y(mx * i / 4):.1f}" y2="{y(mx * i / 4):.1f}" class="g"/><text x="{L - 5}" y="{y(mx * i / 4) + 3.5:.1f}" class="t" text-anchor="end">{mx * i / 4:g}</text>' for i in range(5))
    fmt = "%H:%M" if ora <= 48 else "%m-%d"
    cimkek = "".join(f'<text x="{x(t0 + (t1 - t0) * i / 4):.1f}" y="{H - 6}" class="t" text-anchor="middle">{datetime.fromtimestamp(t0 + (t1 - t0) * i / 4).strftime(fmt)}</text>' for i in range(5))
    vonal_pts = " ".join(f"{x(t):.1f},{y(v):.1f}" for t, v, _ in pontok)
    terulet = f"{x(t0):.1f},{y(0):.1f} {vonal_pts} {x(t1):.1f},{y(0):.1f}"
    sav = max(2.0, (W - L - R) / max(1, ora * 60))   # egy perc széles sáv
    horog = "".join(f'<rect x="{x(t) - sav / 2:.1f}" y="{T}" width="{sav:.1f}" height="{H - T - B}" fill="transparent"><title>{datetime.fromtimestamp(t).strftime("%m-%d %H:%M")} · átlag {v:.1f}{egyseg} · csúcs {m:.1f}{egyseg}</title></rect>' for t, v, m in pontok)
    return (f'<svg viewBox="0 0 {W} {H}" class="vz" role="img" aria-label="{e(kulcs)}">{rács}{cimkek}<polygon points="{terulet}" fill="var({szin})" opacity=".14"/>'
            f'<polyline points="{vonal_pts}" fill="none" stroke="var({szin})" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>{horog}</svg>')


def oszlopok(adat: list[tuple[str, float]], egyseg: str, szin: str = "--s1") -> str:
    """Oszlopdiagram (napi bontás): lekerekített felső vég, a tooltip a pontos érték."""
    if not adat:
        return '<div class="ures">Még nincs adat.</div>'
    W, H, L, T, B = 640, 150, 38, 10, 24
    mx = _szep_max(max(v for _, v in adat) * 1.1 or 1) if max(v for _, v in adat) > 5 else max(max(v for _, v in adat) * 1.25, 0.01)
    sz = (W - L - 8) / len(adat)
    bw = min(34, sz * 0.62)
    rács = "".join(f'<line x1="{L}" x2="{W - 8}" y1="{T + (1 - i / 4) * (H - T - B):.1f}" y2="{T + (1 - i / 4) * (H - T - B):.1f}" class="g"/><text x="{L - 5}" y="{T + (1 - i / 4) * (H - T - B) + 3.5:.1f}" class="t" text-anchor="end">{mx * i / 4:.4g}</text>' for i in range(5))
    sorok = []
    for i, (cim, v) in enumerate(adat):
        h = v / mx * (H - T - B)
        cx = L + sz * (i + .5)
        sorok.append(f'<g><rect x="{cx - bw / 2:.1f}" y="{H - B - h:.1f}" width="{bw:.1f}" height="{max(h, 0):.1f}" rx="4" fill="var({szin})"><title>{e(cim)} · {v:.3g}{e(egyseg)}</title></rect>'
                     f'<text x="{cx:.1f}" y="{H - 6}" class="t" text-anchor="middle">{e(cim[-5:])}</text></g>')
    return f'<svg viewBox="0 0 {W} {H}" class="vz" role="img">{rács}{"".join(sorok)}</svg>'


def sav(cimke: str, v: float, mx: float, szoveg: str, szin: str = "--s1") -> str:
    p = 0 if mx <= 0 else max(1.5, min(100, v / mx * 100)) if v > 0 else 0
    return f'<div class="sv"><span class="sc">{e(cimke)}</span><div class="sk"><i style="width:{p:.1f}%;background:var({szin})"></i></div><b>{e(szoveg)}</b></div>'


def csempe(cim: str, ertek: str, mellek: str = "", allapot: str = "") -> str:
    return f'<div class="cs {allapot}"><div class="cc">{e(cim)}</div><div class="cn">{e(ertek)}</div><div class="cm">{e(mellek)}</div></div>'


# ------------------------------------------------------------------------------------------ oldalak
STILUS = """
:root{color-scheme:light;--bg:#f4f6f5;--k:#fff;--v:#dde5e0;--t:#10201a;--t2:#4f5f57;--t3:#7a887f;--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--ok:#1a8f4d;--fig:#b86e00;--rossz:#c4372f}
@media(prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#131716;--k:#1b211f;--v:#2c3631;--t:#eef2ef;--t2:#b4c0b8;--t3:#8a9890;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--ok:#4cc27d;--fig:#e0a43a;--rossz:#ef6a62}}
a{color:var(--s1)}*{box-sizing:border-box}body{font:15px/1.45 system-ui,sans-serif;margin:0;background:var(--bg);color:var(--t)}
.w{max-width:1040px;margin:0 auto;padding:14px 14px 40px}h1{font-size:1.35rem;margin:6px 0 2px}h2{font-size:1.05rem;margin:0 0 8px}h3{font-size:.95rem;margin:14px 0 6px;color:var(--t2)}
nav{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 14px}nav a{padding:7px 13px;border-radius:999px;background:var(--k);border:1px solid var(--v);color:var(--t2);text-decoration:none;font-weight:600}
nav a.be{background:var(--t);color:var(--bg);border-color:var(--t)}.sz{display:flex;gap:6px;margin:0 0 10px}.sz a{padding:4px 11px;border-radius:8px;border:1px solid var(--v);color:var(--t2);text-decoration:none;font-size:.9rem}.sz a.be{background:var(--s1);color:#fff;border-color:var(--s1)}
.kart{background:var(--k);border:1px solid var(--v);border-radius:14px;padding:14px;margin:0 0 14px}.racs{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:0 0 14px}
.cs{background:var(--k);border:1px solid var(--v);border-radius:14px;padding:12px 14px}.cc{color:var(--t3);font-size:.82rem}.cn{font-size:1.7rem;font-weight:800;line-height:1.15}.cm{color:var(--t2);font-size:.82rem}
.cs.fig{border-color:var(--fig)}.cs.rossz{border-color:var(--rossz)}.cs.ok .cn{color:var(--ok)}.dupla{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.vz{width:100%;height:auto;display:block}.vz .g{stroke:var(--v);stroke-width:1}.vz .t{fill:var(--t3);font-size:10px}.ures{color:var(--t3);padding:18px 0;text-align:center}
.sv{display:grid;grid-template-columns:minmax(90px,170px) 1fr auto;gap:8px;align-items:center;margin:5px 0}.sc{color:var(--t2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.sk{height:10px;background:var(--v);border-radius:6px;overflow:hidden}.sk i{display:block;height:100%;border-radius:6px}
table{width:100%;border-collapse:collapse;font-size:.92rem}th,td{padding:7px 8px;text-align:left;border-bottom:1px solid var(--v);vertical-align:top}th{color:var(--t3);font-weight:600;font-size:.8rem}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.cimke{display:inline-block;padding:1px 8px;border-radius:8px;background:var(--v);color:var(--t2);font-size:.8rem}.fig{color:var(--fig)}.rossz{color:var(--rossz)}.ok{color:var(--ok)}.kicsi{color:var(--t3);font-size:.84rem}
details{margin:6px 0}summary{cursor:pointer;color:var(--t2);font-weight:600}pre{white-space:pre-wrap;margin:6px 0;font:inherit}
"""

FULEK = [("attekintes", "📊 Áttekintés"), ("tanulok", "👥 Tanulók"), ("minoseg", "🎯 Tartalom-minőség"), ("rendszer", "🖥️ Rendszer"), ("jelzes", "🚩 Jelzések"), ("vissza", "💬 Visszajelzések")]


def keret(ful: str, tok: str, tartalom: str, frissit: bool = False) -> str:
    nav = "".join(f'<a class="{"be" if k == ful else ""}" href="?k={e(tok)}&oldal={k}">{n}</a>' for k, n in FULEK)
    return (f'<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">{"<meta http-equiv=refresh content=60>" if frissit else ""}'
            f'<title>{e(APP_NEV)} – admin</title><style>{STILUS}</style><div class="w"><h1>🌿 {e(APP_NEV)} – admin</h1><div class="kicsi">Csak neked látszik · minden adat a laptopon marad</div><nav>{nav}</nav>{tartalom}</div>')


def usd(v: float) -> str:
    return f"${v:.2f}" if v >= 0.1 else f"${v:.3f}"


def attekintes(D: dict, tok: str) -> str:
    k, f = D["kolt"], D["felh"]
    ma = D["ma"]
    aktiv = sum(1 for x in f if x["utolso_nap"] == ma)
    het_aktiv = sum(1 for x in f if x["utolso_nap"] >= D["het_eleje"])
    leckek = sum(x["leckek_kesz"] for x in f)
    gen = sum(x["leckek_gen"] for x in f)
    cs = "".join([
        csempe("Tanulók", str(len(f)), f"ma aktív: {aktiv} · 7 napban: {het_aktiv}"),
        csempe("Kész leckék", str(leckek), f"{gen} elkészített lecke összesen"),
        csempe("AI-költség ma", usd(k["ma_usd"]), f"7 nap: {usd(k['het_usd'])} · összesen {usd(k['ossz_usd'])}"),
        csempe("AI-hívások", str(k["hivas"]), f"átlag {usd(k['ossz_usd'] / max(1, k['hivas']))} / hívás"),
        csempe("Egy lecke ára", usd(k["lecke_ar"]) if k["lecke_ar"] else "–", f'valós: {k["lecke_minta"]} lecke alapján (lektorral)' if k["lecke_minta"] else "még nincs elég mért adat"),
        csempe("Nyitott visszajelzés", str(D["vissza"]["nyitott"]), f"kivizsgálandó jelzés: {D['jelzes']['nyitott']}", "fig" if D["vissza"]["nyitott"] + D["jelzes"]["nyitott"] else "ok"),
    ])
    napok = oszlopok([(n[5:], v) for n, v in k["napok"]], " USD", "--s1")
    ember = max([v for v in k["user"].values()] or [0])
    por = "".join(sav(n, v, ember, usd(v)) for n, v in sorted(k["user"].items(), key=lambda x: -x[1])[:8]) or '<div class="ures">Még nincs adat.</div>'
    mmax = max([v for v in k["munka"].values()] or [0])
    mun = "".join(sav(MUNKA_NEV.get(n, n), v, mmax, usd(v), "--s2") for n, v in sorted(k["munka"].items(), key=lambda x: -x[1])) or '<div class="ures">Még nincs adat.</div>'
    r = D["rendszer"]
    rend = (f'<p>CPU átlag (24 óra): <b>{r["cpu_atlag"]:.0f}%</b> · csúcs <b>{r["cpu_csucs"]:.0f}%</b> · memória csúcs <b>{r["mem_csucs"]:.0f}%</b> · hőmérséklet csúcs <b>{r["temp_csucs"]:.0f} °C</b> '
            f'<a href="?k={e(tok)}&oldal=rendszer">részletek →</a></p>') if r["van"] else '<p class="kicsi">A rendszer-mérés most indult, percenként gyűlik az adat.</p>'
    return (f'<div class="racs">{cs}</div><div class="dupla"><div class="kart"><h2>AI-költség naponta (14 nap)</h2>{napok}</div>'
            f'<div class="kart"><h2>Költség tanulónként</h2>{por}<h3>Mire megy el</h3>{mun}</div></div><div class="kart"><h2>Laptop terhelése</h2>{rend}</div>')


MUNKA_NEV = {"lecke": "Lecke-generálás", "lecke_lektor": "Lektor (ellenőrzés)", "terv": "Tanulási terv", "bovit": "Terv bővítése", "anyag": "Anyaggyűjtés", "miniapp": "Mini-alkalmazás", "egyeb": "Bontás nélküli (a címkézés előtti hívások)"}


def tanulok(D: dict, tok: str) -> str:
    sorok = []
    for x in sorted(D["felh"], key=lambda x: x["utolso_nap"], reverse=True):
        mini = "".join(f'<i style="display:inline-block;width:6px;margin-right:1px;background:var(--s3);height:{max(2, min(18, v // 10))}px;vertical-align:bottom;border-radius:2px" title="{n}: {v} XP"></i>' for n, v in x["napi7"])
        keret_s = "korlátlan" if x["az"] == D["admin"] else f'{x["keret_ma"]}/{x["napi_limit"]}'
        sorok.append(f'<tr><td>{e(x["emoji"])} <b>{e(x["nev"])}</b>{" <span class=cimke>VIP</span>" if x["vip"] else ""}<div class="kicsi">{e(x["az"])}</div></td>'
                     f'<td class="n">{x["szint"]}</td><td class="n">{x["xp"]}</td><td class="n">{x["sorozat"]}</td><td class="n">{x["celok"]}</td><td class="n">{x["leckek_kesz"]}/{x["leckek_gen"]}</td>'
                     f'<td class="n">{keret_s}</td><td class="n">{usd(x["usd"])}</td><td>{e(x["utolso_nap"] or "–")}</td><td>{mini}</td></tr>')
    return ('<div class="kart"><h2>Tanulók</h2><table><tr><th>Tanuló</th><th class="n">Szint</th><th class="n">XP</th><th class="n">Sorozat</th><th class="n">Tanfolyam</th><th class="n">Kész/elkészített lecke</th>'
            '<th class="n">Mai AI-keret</th><th class="n">AI-költség</th><th>Utoljára</th><th>XP / 7 nap</th></tr>' + "".join(sorok) + '</table>'
            f'<p class="kicsi">A mai keret a napi generálási korlát. A tanulónkénti költség csak a bontás kezdete ({e(D["kolt"]["cimkes_kezdet"][:16] or "még nincs")}) óta mért hívásokat tartalmazza, ezért kisebb lehet az összköltségnél.</p></div>')


def minoseg(D: dict, tok: str) -> str:
    m, g = D["minoseg"], D["gy"]
    cs = "".join([
        csempe("Ellenőrzött leckék", str(m["n"]), "a minoseg.jsonl alapján"),
        csempe("Kidobott feladat / lecke", f'{m["elvetett_atlag"]:.1f}', "a kód elutasította (hibás szerkezet / válasz)", "fig" if m["elvetett_atlag"] > 1.5 else ""),
        csempe("Lektor talált hibát", f'{m["lektor_arany"]:.0f}%', f'{m["lektor_db"]} lecke · a lektor javított vagy törölt', "fig" if m["lektor_arany"] > 40 else ""),
        csempe("Rögzített szabály", str(D["tanulsag"]), "tanulságok.json – minden új lecke promptjába kerül"),
    ])
    tip = "".join(sav(TIPUS_NEV.get(t, t), 100 * j / max(1, n), 100, f'{100 * j / max(1, n):.0f}% jó · {n} válasz', "--s3" if j / max(1, n) >= 0.5 else "--s2") for t, (n, j) in sorted(g["tipusok"].items(), key=lambda x: -x[1][0])) or '<div class="ures">Még nincs válasz-adat (a mostantól befejezett leckékből gyűlik).</div>'
    gy = "".join(f'<tr><td>{e(x["user"])}</td><td>{e(x["cim"])}<div class="kicsi">{e(x["lecke"])}</div></td><td><span class="cimke">{e(TIPUS_NEV.get(x["t"], x["t"]))}</span></td><td>{e(x["kerdes"])}</td><td class="n rossz">{x["arany"]:.0f}%</td><td class="n">{x["n"]}</td></tr>' for x in g["gyanus"]) \
        or '<tr><td colspan=6 class="kicsi">Nincs gyanús feladat (legalább 3 válasz kell, és 35% alatti találati arány).</td></tr>'
    lek = "".join(f'<details><summary>{e(x["ido"][:16])} · {e(x["tanfolyam"])} – {e(x["lecke"])}</summary><pre>{e(chr(10).join(x["lektor"]))}</pre></details>' for x in m["utolso_lektor"]) or '<div class="ures">A lektor még nem talált hibát.</div>'
    return (f'<div class="racs">{cs}</div><div class="dupla"><div class="kart"><h2>Találati arány feladattípusonként</h2>{tip}'
            '<p class="kicsi">Ha egy típus nagyon alacsony: túl nehéz vagy hibásan készül.</p></div>'
            f'<div class="kart"><h2>Mit talált a lektor? (legutóbbi)</h2>{lek}</div></div>'
            f'<div class="kart"><h2>Gyanús feladatok – sokan elrontják</h2><table><tr><th>Tanuló</th><th>Tanfolyam / lecke</th><th>Típus</th><th>Kérdés</th><th class="n">Jó</th><th class="n">Válasz</th></tr>{gy}</table>'
            '<p class="kicsi">Ezeket érdemes átnézni: lehet, hogy a feladat hibás. A hibás mintákból szabály lesz: <code>visszajelzesek.py tanulsag "…"</code>.</p></div>')


TIPUS_NEV = {"teszt": "Teszt", "ird": "Írd le", "parosit": "Párosítás", "rendez": "Sorrend", "hallgat": "Hallgat", "mondd": "Mondd ki", "tabla": "Sakktábla", "igazhamis": "Igaz/hamis", "kitolt": "Kitöltős", "hibakereso": "Hibakereső"}


def rendszer(D: dict, tok: str, ora: int) -> str:
    mi = D["minta"]
    szuro = '<div class="sz">' + "".join(f'<a class="{"be" if o == ora else ""}" href="?k={e(tok)}&oldal=rendszer&ora={o}">{n}</a>' for o, n in ((1, "1 óra"), (6, "6 óra"), (24, "24 óra"), (168, "7 nap"))) + '</div>'
    if not mi:
        return szuro + '<div class="kart"><div class="ures">A mérés most indult – percenként gyűlik az adat, nézz vissza pár perc múlva.</div></div>'
    u = mi[-1]
    gyujt = (time.time() - D["elso_minta"]) / 3600 if D.get("elso_minta") else 0
    megj = (f'<div class="kart kicsi">ℹ️ A mérés {gyujt:.1f} órája gyűlik, ezért a {ora} órás nézetben még csak a jobb oldali szakaszon van adat – a bal oldali üres rész azt az időt jelzi, amikor még nem mértünk.</div>'
            if gyujt and gyujt < ora * 0.95 else "")
    mag = D["magok"]
    def ertek(k):  # noqa: ANN001
        return [r[k] for r in mi if r.get(k) is not None]
    cpu, mem, tmp, l1 = ertek("cpu"), ertek("mem"), ertek("temp"), ertek("l1")
    csucs_t = max(mi, key=lambda r: r["cpu"])["t"]
    cs = "".join([
        csempe("CPU most", f'{u["cpu"]:.0f}%', f'átlag {sum(cpu) / len(cpu):.0f}% · csúcs {max(cpu):.0f}% ({datetime.fromtimestamp(csucs_t).strftime("%H:%M")})', "fig" if max(cpu) > 85 else ""),
        csempe("Terhelés (load)", f'{u["l1"]:.2f}', f'{mag} mag · csúcs {max(l1):.2f}', "fig" if max(l1) > mag else ""),
        csempe("Memória", f'{u["mem"]:.0f}%', f'csúcs {max(mem):.0f}% · swap {u["swap"]:.0f}%', "fig" if max(mem) > 85 else ""),
        csempe("Hőmérséklet", f'{u["temp"]:.0f} °C' if u.get("temp") is not None else "–", f'csúcs {max(tmp):.0f} °C' if tmp else "nincs érzékelő", "fig" if tmp and max(tmp) > 85 else ""),
        csempe("Lemez", f'{u["disk"]:.0f}%', "a /home partíció foglaltsága", "fig" if u["disk"] > 85 else ""),
        csempe("Akku", f'{u["bat"]}%' if u.get("bat") is not None else "–", ("töltődik" if u.get("toltes") else "nem tölt") if u.get("bat") is not None else "nincs akku-adat"),
        csempe("AI-folyamatok", str(u["claude"]), f'egyszerre legfeljebb {max(r["claude"] for r in mi)}'),
        csempe("Tanoda memóriája", f'{u["rss"]} MB', "a szerver-folyamat"),
    ])
    d = lambda k, cim, egy, szin, fix=None: f'<div class="kart"><h2>{cim}</h2>{vonal(mi, k, egy, szin, fix, ora)}</div>'  # noqa: E731
    return (szuro + megj + f'<div class="racs">{cs}</div><div class="dupla">{d("cpu", "CPU-használat (%)", "%", "--s1", 100)}{d("l1", "Terhelés (1 perces load)", "", "--s2")}'
            f'{d("mem", "Memória-használat (%)", "%", "--s3", 100)}{d("temp", "Hőmérséklet (°C)", " °C", "--s2")}{d("claude", "Egyszerre futó AI-hívások", "", "--s1")}{d("disk", "Lemez-foglaltság (%)", "%", "--s3", 100)}</div>'
            f'<p class="kicsi">Mérés percenként · {len(mi)} minta ebben az időszakban · az érték fölé állva a pontos idő és csúcs látszik. 7 napig őrzi.</p>')


def oldal(ful: str, D: dict, tok: str, ora: int = 24) -> str:
    if ful == "tanulok":
        return keret(ful, tok, tanulok(D, tok))
    if ful == "minoseg":
        return keret(ful, tok, minoseg(D, tok))
    if ful == "rendszer":
        return keret(ful, tok, rendszer(D, tok, ora), frissit=True)
    return keret("attekintes", tok, attekintes(D, tok))
