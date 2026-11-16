// Rexi, a Tanoda 3D dínó-kabalája: szemüveges, könyves kis dínó, akinek a tanulás a mindene. (Pixar-hangulat: fényes anyag, nagy szemek.)
// A lapi.src.js hívja: epitDino() építi a modellt, dinoFrissit() állítja be az aktuális pózt (állapot: data-a).
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";

const V = (x, y, z) => new THREE.Vector3(x, y, z);
const sima = (a, b, k) => a + (b - a) * k;
const KAR_HOSSZ = 0.62;                        // a kar hossza a vállponttól a kézig
const VALL_L = V(-0.82, 0.4, 0.32), VALL_R = V(0.82, 0.4, 0.32);   // vállak a törzs koordinátáiban

// Pózok: kéz-célpontok (törzs-koordináta), könyv helye/dőlése, arc. A smooth-olt értékek követik a célt.
const P = {
  idle:    { hL: [-0.52, 0.0, 0.84], hR: [0.52, 0.0, 0.84], bk: [0, -0.02, 0.9], bkR: [-0.12, 0, 0], szem: 1, sy: 0, ssz: 0, mosoly: 1, nyit: 0, nx: 0, ny: 0, fRx: 0, fRz: 0, tRx: 0, farok: 1 },
  olvas:   { hL: [-0.54, 0.34, 0.86], hR: [0.54, 0.34, 0.86], bk: [0, 0.3, 0.97], bkR: [-0.55, 0, 0], szem: 0.82, sy: 0, ssz: 0, mosoly: 0.7, nyit: 0, nx: 0, ny: -0.6, fRx: 0.2, fRz: 0, tRx: 0.04, farok: 0.6 },
  beszel:  { hL: [-0.54, 0.34, 0.86], hR: [0.54, 0.34, 0.86], bk: [0, 0.3, 0.97], bkR: [-0.5, 0, 0], szem: 0.95, sy: 0.02, ssz: 0, mosoly: 1, nyit: 0, nx: 0, ny: -0.2, fRx: 0.08, fRz: 0, tRx: 0, farok: 1.2 },
  orul:    { hL: [-1.3, 1.45, 0.4], hR: [1.3, 1.45, 0.4], bk: [0, 0.2, 1.0], bkR: [-0.2, 0, 0], szem: 0.58, sy: 0.1, ssz: -0.12, mosoly: 1, nyit: 1, nx: 0, ny: 0.1, fRx: -0.12, fRz: 0, tRx: -0.05, farok: 3 },
  szomoru: { hL: [-0.42, 0.3, 0.8], hR: [0.42, 0.3, 0.8], bk: [0, 0.3, 0.9], bkR: [-0.25, 0, 0], szem: 0.82, sy: -0.03, ssz: 0.45, mosoly: -1, nyit: 0, nx: 0, ny: -0.55, fRx: 0.3, fRz: 0, tRx: 0.12, farok: 0.15 },
  gondol:  { hL: [-0.58, -0.1, 0.84], hR: [0.5, 0.75, 0.84], bk: [-0.5, -0.05, 0.92], bkR: [-0.1, 0.45, 0.15], szem: 1, sy: 0.05, ssz: 0.14, mosoly: 0.2, nyit: 0, nx: 0.7, ny: 0.6, fRx: 0, fRz: -0.16, tRx: 0, farok: 0.5 },
  tanit:   { hL: [-0.5, -0.1, 0.86], hR: [1.1, 1.0, 1.0], bk: [-0.5, -0.05, 0.92], bkR: [-0.1, 0.5, 0], szem: 1, sy: 0.04, ssz: 0, mosoly: 1, nyit: 0.3, nx: 0.35, ny: 0, fRx: -0.03, fRz: 0.1, tRx: 0, farok: 1.4 },
  figyel:  { hL: [-0.5, -0.1, 0.86], hR: [1.12, 1.0, 0.3], bk: [-0.5, -0.05, 0.92], bkR: [-0.1, 0.5, 0], szem: 1.12, sy: 0.06, ssz: 0, mosoly: 0.3, nyit: 0.25, nx: 0.3, ny: 0.05, fRx: 0, fRz: -0.2, tRx: 0, farok: 0.7 },
  alszik:  { hL: [-0.5, -0.25, 0.7], hR: [0.5, -0.25, 0.7], bk: [0, -0.2, 0.85], bkR: [0.2, 0, 0], szem: 0.06, sy: -0.03, ssz: 0, mosoly: 0.5, nyit: 0, nx: 0, ny: 0, fRx: 0.32, fRz: 0, tRx: 0.08, farok: 0.2 },
};
// Új gesztusok: az alap-póz módosítása; az idő-függő mozgást a dinoFrissit adja hozzá
const ujP = (alap, o) => Object.assign(JSON.parse(JSON.stringify(P[alap])), o);
P.integet = ujP("idle", { hR: [1.05, 1.25, 0.5], mosoly: 1, nyit: 0.3, fRz: 0.08, farok: 1.6 });
P.tapsol = ujP("idle", { hL: [-0.3, 0.4, 1.05], hR: [0.3, 0.4, 1.05], szem: 0.7, mosoly: 1, nyit: 0.5, farok: 2 });
P.tancol = ujP("orul", { hL: [-1.1, 1.0, 0.5], hR: [1.1, 1.0, 0.5], szem: 0.7, nyit: 0.6, farok: 3.2 });
P.forog = ujP("orul", { hL: [-1.2, 0.5, 0.2], hR: [1.2, 0.5, 0.2], szem: 0.6, nyit: 0.8, farok: 3.5 });
P.edz = ujP("idle", { hL: [-1.05, 0.85, 0.55], hR: [1.05, 0.85, 0.55], sy: -0.05, ssz: -0.3, mosoly: 1, nyit: 0, fRx: -0.1, tRx: -0.08, farok: 1.5 });
P.fut = ujP("idle", { hL: [-0.55, 0.2, 0.9], hR: [0.55, 0.2, 0.9], szem: 0.9, mosoly: 0.8, nyit: 0.4, tRx: 0.16, fRx: 0.05, farok: 3 });
P.bolint = ujP("idle", { mosoly: 1, szem: 0.8, farok: 1.2 });
P.razza = ujP("szomoru", { mosoly: 0.3, ssz: 0.2, ny: 0, farok: 0.4 });
P.bator = ujP("idle", { hR: [0.95, 1.25, 0.75], hL: [-0.5, 0.0, 0.84], sy: -0.04, ssz: -0.2, mosoly: 1, nyit: 0.2, fRx: -0.08, farok: 2 });
P.nyujtozik = ujP("idle", { hL: [-1.0, 1.55, 0.2], hR: [1.0, 1.55, 0.2], szem: 0.35, mosoly: 0.4, nyit: 1, fRx: -0.35, tRx: -0.12, farok: 0.8 });
P.szalutal = ujP("idle", { hR: [0.62, 1.45, 0.75], mosoly: 1, sy: -0.03, ssz: -0.15, fRx: -0.06, farok: 1.4 });
P.csodalkozik = ujP("idle", { hL: [-0.85, 0.75, 0.75], hR: [0.85, 0.75, 0.75], szem: 1.28, sy: 0.12, ssz: -0.05, mosoly: 0, nyit: 1, fRx: -0.1, farok: 1.8 });
export const DINO_ALLAPOTOK = Object.keys(P);

export function epitDino(anyag) {
  const g = new THREE.Group();
  const bor = anyag("#10b36b", { roughness: 0.5, clearcoat: 0.45 }), borSotet = anyag("#0c9a5a", { roughness: 0.5, clearcoat: 0.45 }), has = anyag("#fff0c4", { roughness: 0.7, clearcoat: 0.12 });
  const narancs = anyag("#ff8a1f"), feher = anyag("#ffffff", { roughness: 0.12, clearcoat: 1 }), tinta = anyag("#16233a", { roughness: 0.15, clearcoat: 1 });
  const keret = anyag("#33406b", { roughness: 0.25, metalness: 0.25 });
  const D = { g, kar: [], lab: [], szem: [], szemoldok: [] };

  // lábak és nagy lábfejek
  for (const s of [-1, 1]) {
    const l = new THREE.Group(); l.position.set(s * 0.46, 0, 0.1); g.add(l); D.lab.push(l);
    const cs = new THREE.Mesh(new THREE.CapsuleGeometry(0.25, 0.3, 6, 16), bor); cs.position.y = 0.42; l.add(cs);
    const lab = new THREE.Mesh(new THREE.SphereGeometry(0.38, 28, 20), borSotet); lab.scale.set(1, 0.52, 1.35); lab.position.set(0, 0.17, 0.2); l.add(lab);
    for (const dx of [-0.17, 0, 0.17]) { const k = new THREE.Mesh(new THREE.SphereGeometry(0.075, 12, 10), has); k.position.set(dx, 0.15, 0.62); k.scale.set(1, 0.8, 1.1); l.add(k); }
  }

  // test (squash-pivot a talajon)
  const nyuj = new THREE.Group(); g.add(nyuj); D.nyuj = nyuj;
  const torzs = new THREE.Group(); torzs.position.y = 1.3; nyuj.add(torzs); D.torzs = torzs;
  const test = new THREE.Mesh(new THREE.SphereGeometry(0.92, 40, 30), bor); test.scale.set(1, 1.12, 0.96); torzs.add(test);
  const hasMesh = new THREE.Mesh(new THREE.SphereGeometry(0.78, 36, 26), has); hasMesh.scale.set(0.82, 0.95, 0.5); hasMesh.position.set(0, -0.06, 0.5); torzs.add(hasMesh);
  // hátlemezek (narancs háromszögek), a farok felé csökkenő méretben
  [[0.0, 1.0, -0.55, 0.26], [0.0, 0.55, -0.82, 0.3], [0.0, 0.05, -0.97, 0.28], [0.0, -0.45, -0.95, 0.22]].forEach(([x, y, z, m]) => {
    const c = new THREE.Mesh(new THREE.ConeGeometry(m * 0.7, m * 1.5, 14), narancs); c.position.set(x, y, z); c.rotation.x = -0.9 - (0.9 - y) * 0.12; torzs.add(c);
  });
  // farok (3 gömb), jobbra-hátra kunkorodik
  const farok = new THREE.Group(); farok.position.set(0.1, -0.55, -0.7); torzs.add(farok); D.farok = farok;
  [[0.15, -0.05, -0.4, 0.5], [0.55, 0.02, -0.82, 0.36], [0.98, 0.18, -1.12, 0.24]].forEach(([x, y, z, r]) => { const m = new THREE.Mesh(new THREE.SphereGeometry(r, 24, 18), bor); m.position.set(x, y, z); farok.add(m); });
  const farokCsucs = new THREE.Mesh(new THREE.ConeGeometry(0.1, 0.26, 12), narancs); farokCsucs.position.set(1.17, 0.28, -1.22); farokCsucs.rotation.set(-0.5, 0.2, -0.9); farok.add(farokCsucs);

  // fej
  const fej = new THREE.Group(); fej.position.set(0, 1.2, 0.16); torzs.add(fej); D.fej = fej;
  const koponya = new THREE.Mesh(new THREE.SphereGeometry(0.98, 44, 32), bor); koponya.scale.set(1.06, 0.96, 1.0); fej.add(koponya);
  const orr = new THREE.Mesh(new THREE.SphereGeometry(0.56, 32, 24), bor); orr.scale.set(0.92, 0.62, 0.82); orr.position.set(0, -0.28, 0.74); fej.add(orr);
  for (const s of [-1, 1]) { const n = new THREE.Mesh(new THREE.SphereGeometry(0.045, 10, 8), tinta); n.position.set(s * 0.15, -0.12, 1.22); fej.add(n); }
  [[0, 1.0, -0.05, 0.2], [0, 0.88, -0.42, 0.22], [0, 0.62, -0.72, 0.18]].forEach(([x, y, z, m], i) => { const c = new THREE.Mesh(new THREE.ConeGeometry(m * 0.75, m * 1.6, 12), narancs); c.position.set(x, y, z); c.rotation.x = -0.35 - i * 0.45; fej.add(c); });
  for (const s of [-1, 1]) { const p = new THREE.Mesh(new THREE.SphereGeometry(0.14, 20, 14), new THREE.MeshBasicMaterial({ color: "#ff7fa3", transparent: true, opacity: 0.7 })); p.scale.set(1.2, 0.72, 0.2); p.position.set(s * 0.72, -0.18, 0.66); p.rotation.y = s * 0.7; fej.add(p); }
  // szemek, pupillák, csillanás
  for (const s of [-1, 1]) {
    const cs = new THREE.Group(); cs.position.set(s * 0.45, 0.3, 0.8);
    const fe = new THREE.Mesh(new THREE.SphereGeometry(0.33, 32, 24), feher); fe.scale.set(1.05, 1.15, 0.5); cs.add(fe);
    const pup = new THREE.Group(); pup.position.z = 0.09; cs.add(pup);
    const pu = new THREE.Mesh(new THREE.SphereGeometry(0.205, 24, 18), tinta); pu.scale.set(1, 1.05, 0.5); pup.add(pu);
    const k = new THREE.Mesh(new THREE.SphereGeometry(0.07, 12, 10), new THREE.MeshBasicMaterial({ color: "#ffffff" })); k.position.set(0.075, 0.085, 0.08); pup.add(k);
    const k2 = new THREE.Mesh(new THREE.SphereGeometry(0.026, 10, 8), new THREE.MeshBasicMaterial({ color: "#ffffff" })); k2.position.set(-0.06, -0.05, 0.075); pup.add(k2);
    fej.add(cs); D.szem.push({ csoport: cs, pup });
    // szemüveg-keret + halvány lencse
    const gy = new THREE.Mesh(new THREE.TorusGeometry(0.45, 0.04, 12, 44), keret); gy.position.set(s * 0.45, 0.3, 1.0); fej.add(gy);
    const lencse = new THREE.Mesh(new THREE.CircleGeometry(0.44, 32), new THREE.MeshBasicMaterial({ color: "#bfe6ff", transparent: true, opacity: 0.12 })); lencse.position.set(s * 0.45, 0.3, 1.01); fej.add(lencse);
    const szar = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 0.85, 8), keret); szar.rotation.x = Math.PI / 2; szar.position.set(s * 0.9, 0.3, 0.58); fej.add(szar);
    const b = new THREE.Mesh(new THREE.CapsuleGeometry(0.04, 0.24, 4, 10), anyag("#1c5a3f", { clearcoat: 0.3 })); b.position.set(s * 0.45, 0.92, 0.88); fej.add(b); D.szemoldok.push(b);
  }
  const hid = new THREE.Mesh(new THREE.TorusGeometry(0.075, 0.03, 8, 16, Math.PI), keret); hid.position.set(0, 0.36, 1.01); fej.add(hid);
  // száj: mosoly (tórusz-ív) és nyitott száj (fél korong + nyelv)
  const szajCs = new THREE.Group(); szajCs.position.set(0, -0.36, 1.2); fej.add(szajCs);
  const mosoly = new THREE.Mesh(new THREE.TorusGeometry(0.27, 0.036, 10, 28, Math.PI), anyag("#16233a", { clearcoat: 0.4 })); mosoly.rotation.z = Math.PI; szajCs.add(mosoly); D.mosoly = mosoly;
  const szaj = new THREE.Group(); szajCs.add(szaj); D.szaj = szaj;
  szaj.add(new THREE.Mesh(new THREE.CircleGeometry(0.29, 28, Math.PI, Math.PI), new THREE.MeshBasicMaterial({ color: "#4a1220" })));
  const nyelv = new THREE.Mesh(new THREE.CircleGeometry(0.13, 20, Math.PI, Math.PI), new THREE.MeshBasicMaterial({ color: "#ff6f8e" })); nyelv.position.set(0, -0.12, 0.004); szaj.add(nyelv);
  szaj.scale.set(1, 0.001, 1);

  // karok (egyenes, rövid „T-rex” kar), a kéz-célpont felé fordítva
  for (const s of [-1, 1]) {
    const k = new THREE.Group(); k.position.copy(s < 0 ? VALL_L : VALL_R); torzs.add(k);
    const cs = new THREE.Mesh(new THREE.CapsuleGeometry(0.14, KAR_HOSSZ - 0.28, 6, 14), bor); cs.position.y = -KAR_HOSSZ / 2 + 0.04; k.add(cs);
    const kez = new THREE.Mesh(new THREE.SphereGeometry(0.2, 22, 16), bor); kez.position.y = -KAR_HOSSZ - 0.02; k.add(kez);
    for (const dx of [-0.08, 0.08]) { const k2 = new THREE.Mesh(new THREE.ConeGeometry(0.045, 0.12, 8), has); k2.position.set(dx, -KAR_HOSSZ - 0.2, 0.05); k2.rotation.x = Math.PI; k.add(k2); }
    D.kar.push({ g: k, s });
  }

  // könyv: két lapfél, a gerincnél hajlik; kívül kék borító (jól elüt a zöld bőrtől és a krémszínű hastól), a lapok szegélye krémszínű
  const c = document.createElement("canvas"); c.width = 128; c.height = 160;
  const x = c.getContext("2d"); x.fillStyle = "#3a5bd9"; x.fillRect(0, 0, 128, 160); x.strokeStyle = "#ffd36b"; x.lineWidth = 5; x.strokeRect(10, 10, 108, 140);
  x.fillStyle = "#ffd36b"; x.beginPath(); for (let i = 0; i < 10; i++) { const r = i % 2 ? 13 : 28, w = i * Math.PI / 5 - Math.PI / 2; x.lineTo(64 + Math.cos(w) * r, 80 + Math.sin(w) * r); } x.fill();
  const lapTex = new THREE.CanvasTexture(c); lapTex.colorSpace = THREE.SRGBColorSpace;
  const konyv = new THREE.Group(); torzs.add(konyv); D.konyv = konyv;
  const lapSzin = anyag("#fffaf0");
  for (const s of [-1, 1]) {
    const h = new THREE.Group(); h.rotation.y = s * 0.38; konyv.add(h);
    const lap = new THREE.Mesh(new RoundedBoxGeometry(0.47, 0.66, 0.1, 2, 0.02), lapSzin); lap.position.set(s * 0.26, 0, -0.07); h.add(lap);
    const bor_ = new THREE.Mesh(new RoundedBoxGeometry(0.52, 0.72, 0.05, 3, 0.025), new THREE.MeshStandardMaterial({ map: lapTex, roughness: 0.5 })); bor_.position.set(s * 0.26, 0, 0.0); h.add(bor_);
  }

  // puha árnyék
  const cv = document.createElement("canvas"); cv.width = cv.height = 128;
  const ctx = cv.getContext("2d"), gr = ctx.createRadialGradient(64, 64, 4, 64, 64, 62); gr.addColorStop(0, "rgba(0,0,0,.42)"); gr.addColorStop(1, "rgba(0,0,0,0)"); ctx.fillStyle = gr; ctx.fillRect(0, 0, 128, 128);
  const arnyek = new THREE.Mesh(new THREE.PlaneGeometry(3.2, 3.2), new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(cv), transparent: true, depthWrite: false }));
  arnyek.rotation.x = -Math.PI / 2; arnyek.position.y = 0.01; g.add(arnyek); D.arnyek = arnyek;

  // gondolat-pöttyök, könnycsepp
  D.pottyok = [0, 1, 2].map((i) => { const m = new THREE.Mesh(new THREE.SphereGeometry(0.08 + i * 0.025, 14, 10), new THREE.MeshBasicMaterial({ color: "#ffffff" })); m.position.set(1.2 + i * 0.22, 3.25 + i * 0.18, 0.2); m.visible = false; g.add(m); return m; });
  D.konnyek = new THREE.Mesh(new THREE.SphereGeometry(0.08, 12, 10), anyag("#7fd0ff", { roughness: 0.05 })); D.konnyek.scale.set(0.8, 1.2, 0.8); D.konnyek.visible = false; fej.add(D.konnyek);
  D.hatar = { hL: V(...P.idle.hL), hR: V(...P.idle.hR) };
  return D;
}

function karBeallit(k, vall, cel) {
  const d = cel.clone().sub(vall), hossz = d.length();
  if (hossz < 1e-4) return;
  d.divideScalar(hossz);
  k.g.quaternion.setFromUnitVectors(V(0, -1, 0), d);
  k.g.scale.y = THREE.MathUtils.clamp(hossz / (KAR_HOSSZ + 0.2), 0.7, 1.12);
}

// p: a példány (p.el.dataset.a az állapot, p.dp a simított póz), ido/dt: ms / s, mutato: {x,y,aktiv}, rect: az elem helye
export function dinoFrissit(D, p, ido, dt, mutato, rect) {
  const el = p.el, a = P[el.dataset.a] ? el.dataset.a : "idle";
  if (!p.dp) { p.dp = JSON.parse(JSON.stringify(P.idle)); p.dState = ""; p.dN = ""; p.dT0 = ido; p.dPis = 2; p.dPisT = -1; p.dNez = { x: 0, y: 0 }; }
  if (a !== p.dState || el.dataset.n !== p.dN) { p.dState = a; p.dN = el.dataset.n; p.dT0 = ido; }
  const t = (ido - p.dT0) / 1000, ossz = ido / 1000, cel = JSON.parse(JSON.stringify(P[a]));
  let ugras = 0, nyom = 0, konyvDobas = 0, fy = 0, gx = 0, gyaw = 0, roll = 0, futas = 0;
  if (a === "orul") {
    const c = t % 1.6, u = c / 0.85;
    if (u < 1) { ugras = Math.sin(Math.PI * u) * 0.34; nyom = u < 0.14 ? u / 0.14 : u > 0.86 ? (u - 0.86) / 0.14 : -0.2 * Math.sin(Math.PI * u); konyvDobas = Math.sin(Math.PI * u); }
    cel.hL[1] += Math.sin(ossz * 13) * 0.12; cel.hR[1] -= Math.sin(ossz * 13) * 0.12;
  } else if (a === "szomoru") { cel.fRz = Math.sin(t * 9) * 0.03 * Math.max(0, 1 - t); }
  else if (a === "beszel") { cel.nyit = 0.1 + 0.6 * Math.abs(Math.sin(ossz * 9.1)) * (0.6 + 0.4 * Math.sin(ossz * 3.3)); cel.nx = Math.sin(ossz * 1.3) * 0.25; }
  else if (a === "olvas") { cel.nx = Math.sin(ossz * 1.6) * 0.8; }
  else if (a === "integet") { cel.hR[0] += Math.sin(ossz * 11) * 0.3; cel.hR[1] += Math.sin(ossz * 5.5) * 0.06; }
  else if (a === "tapsol") { const c = Math.abs(Math.sin(ossz * 7)); cel.hL[0] = -0.08 - 0.4 * c; cel.hR[0] = 0.08 + 0.4 * c; ugras = 0.07 * c; }
  else if (a === "tancol") { const w = Math.sin(ossz * 4.2); gx = w * 0.24; roll = w * 0.13; ugras = Math.abs(Math.sin(ossz * 4.2)) * 0.13; cel.hL[1] = 1.0 + Math.sin(ossz * 8.4) * 0.5; cel.hR[1] = 1.0 - Math.sin(ossz * 8.4) * 0.5; cel.fRz = w * 0.12; }
  else if (a === "forog") { const u = Math.min(1, t / 1.15); gyaw = (1 - Math.pow(1 - u, 3)) * Math.PI * 2; ugras = Math.sin(Math.PI * Math.min(1, t / 0.9)) * 0.42; nyom = t < 0.15 ? t / 0.15 : 0; }
  else if (a === "edz") { const e = Math.max(0, Math.sin(ossz * 5.5)); cel.hL[1] += e * 0.14; cel.hR[1] += e * 0.14; nyom = 0.25 * e; cel.fRx -= e * 0.05; }
  else if (a === "fut") { const f = Math.sin(ossz * 11); futas = f; ugras = Math.abs(f) * 0.1; cel.hL[2] = 0.9 + f * 0.4; cel.hR[2] = 0.9 - f * 0.4; cel.hL[1] = 0.2 + Math.max(0, f) * 0.3; cel.hR[1] = 0.2 + Math.max(0, -f) * 0.3; roll = f * 0.05; }
  else if (a === "bolint") { cel.fRx = 0.04 + Math.sin(t * 10) * 0.16 * Math.max(0, 1 - t / 0.9); cel.hR[1] = 0.0; }
  else if (a === "razza") { fy = Math.sin(t * 11) * 0.4 * Math.max(0, 1 - t / 1.1); cel.fRz = Math.sin(t * 11) * 0.03 * Math.max(0, 1 - t); }
  else if (a === "bator") { const e = Math.max(0, Math.sin(t * 7)) * Math.max(0, 1 - t / 1.4); cel.hR[1] += e * 0.28; nyom = 0.25 * e; ugras = 0.05 * e; }
  else if (a === "nyujtozik") { const e = Math.min(1, t / 0.8); cel.nyit = 0.2 + 0.8 * Math.sin(Math.min(1, t / 1.6) * Math.PI); cel.fRx = -0.05 - 0.3 * e; cel.szem = 0.9 - 0.55 * Math.sin(Math.min(1, t / 1.6) * Math.PI); }
  else if (a === "szalutal") { cel.hR[0] += Math.sin(t * 9) * 0.04 * Math.max(0, 1 - t / 0.5); }
  else if (a === "csodalkozik") { nyom = -0.12 * Math.max(0, 1 - t / 0.35); ugras = 0.05 * Math.max(0, 1 - t / 0.25); cel.szem = 1.28 + Math.sin(ossz * 14) * 0.03; }   // a szeme végigfut a soron
  // pislogás
  p.dPis -= dt; if (p.dPis <= 0) { p.dPisT = 0; p.dPis = 2.5 + Math.random() * 3; }
  let pis = 1; if (p.dPisT >= 0) { p.dPisT += dt; pis = Math.max(0.05, Math.abs(1 - Math.sin(Math.min(1, p.dPisT / 0.16) * Math.PI))); if (p.dPisT > 0.16) p.dPisT = -1; }
  // simítás
  const k = 1 - Math.exp(-dt * 10);
  for (const key of Object.keys(cel)) {
    if (Array.isArray(cel[key])) cel[key].forEach((v, i) => (p.dp[key][i] = sima(p.dp[key][i], v, k)));
    else p.dp[key] = sima(p.dp[key], cel[key], k);
  }
  const Q = p.dp;
  // tekintet az egérre
  const cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 3;
  const tx = mutato.aktiv ? Math.max(-1, Math.min(1, (mutato.x - cx) / 400)) : 0, ty = mutato.aktiv ? Math.max(-1, Math.min(1, (cy - mutato.y) / 400)) : 0;
  p.dNez.x = sima(p.dNez.x, tx, k * 0.6); p.dNez.y = sima(p.dNez.y, ty, k * 0.6);

  // --- modell beállítása
  const lel = Math.sin(ossz * 2.2) * 0.5 + 0.5;
  D.g.position.set(gx, ugras, 0); D.g.rotation.y = gyaw;
  D.nyuj.scale.set(1 + nyom * 0.08 - lel * 0.006, 1 - nyom * 0.14 + lel * 0.014 + (ugras > 0.05 ? 0.07 : 0), 1 + nyom * 0.08 - lel * 0.006);
  D.torzs.rotation.set(Q.tRx, p.dNez.x * 0.12, Math.sin(ossz * 1.1) * 0.02 + roll);
  D.fej.rotation.set(Q.fRx - p.dNez.y * 0.16, p.dNez.x * 0.35 + fy, Q.fRz + Math.sin(ossz * 1.3) * 0.015);
  for (const sz of D.szem) {
    sz.csoport.scale.y = Math.max(0.06, Q.szem * pis);
    sz.pup.position.set((Q.nx + p.dNez.x * 0.45) * 0.13, (Q.ny + p.dNez.y * 0.35) * 0.13, 0.09);
  }
  D.szemoldok.forEach((b, i) => { const s = i === 0 ? -1 : 1; b.position.y = 0.92 + Q.sy + (a === "gondol" && s === -1 ? 0.08 : 0); b.rotation.z = Math.PI / 2 + (s === -1 ? 1 : -1) * Q.ssz; });
  D.mosoly.scale.y = Q.mosoly; D.mosoly.position.y = Q.mosoly < 0 ? -0.12 : 0; D.mosoly.visible = Q.nyit < 0.2;
  D.szaj.scale.y = Math.max(0.001, Q.nyit); D.szaj.visible = Q.nyit > 0.04;
  // karok + könyv
  const hL = V(...Q.hL), hR = V(...Q.hR);
  if (konyvDobas > 0) { const w = Math.min(1, konyvDobas * 1.6), y = Q.bk[1] + 0.05 + konyvDobas * 0.32; hL.lerp(V(-0.62, y, 1.02), w); hR.lerp(V(0.62, y, 1.02), w); }   // ugrás közben két kézzel emeli a könyvet
  karBeallit(D.kar[0], VALL_L, hL); karBeallit(D.kar[1], VALL_R, hR);
  D.konyv.position.set(Q.bk[0], Q.bk[1] + konyvDobas * 0.32, Q.bk[2] + 0.2);
  D.konyv.rotation.set(Q.bkR[0] - konyvDobas * 0.25, Q.bkR[1], Q.bkR[2]);
  D.lab.forEach((l, i) => { l.position.y = a === "fut" ? Math.max(0, i ? -futas : futas) * 0.28 : ugras > 0.05 ? 0.07 : 0; });
  D.farok.rotation.y = Math.sin(ossz * (2.5 + Q.farok * 2.2)) * 0.16 * Q.farok; D.farok.rotation.z = Math.sin(ossz * 1.7) * 0.03;
  D.pottyok.forEach((m, i) => { m.visible = a === "gondol"; if (m.visible) m.scale.setScalar(0.5 + 0.5 * Math.max(0, Math.sin(ossz * 3.2 - i * 0.9))); });
  D.konnyek.visible = a === "szomoru"; if (D.konnyek.visible) { const f = (t * 0.9) % 1; D.konnyek.position.set(-0.55, 0.05 - f * 0.5, 0.78); D.konnyek.scale.setScalar(0.8 * (1 - f * 0.4)); }
  D.arnyek.scale.setScalar(1 - ugras * 0.35); D.arnyek.material.opacity = 1 - ugras * 0.45;
}
