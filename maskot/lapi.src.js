// Lapi, a Tanoda 3D kabalája: egy kerek, mosolygós könyv diplomaosztó-sapkával (Pixar-hangulat: fényes anyag, lágy fény, nagy szemek).
// Egyetlen WebGL-környezet rendereli, és minden `.csira` elembe másolja a képet (2D canvas). Ha a WebGL nem megy, a régi SVG marad.
// Állapotok (data-a): idle | orul | szomoru | beszel | gondol | alszik   –   újraindítás: data-n változása.
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { epitDino, dinoFrissit } from "./dino.js";

const MERET = 360;           // a renderelt kép oldala (px)
const KEPKOCKA_MS = 1000 / 30;
let R = null, scene, camera, lapi, dino, resz, arnyek, gondolPontok, konnyek, kesz = false;
const peldanyok = new Set();
const mutato = { x: 0, y: 0, aktiv: false };

function anyag(szin, o = {}) {
  return new THREE.MeshPhysicalMaterial({ color: szin, roughness: 0.38, metalness: 0, clearcoat: 0.9, clearcoatRoughness: 0.18, ...o });
}

function epit() {
  const g = new THREE.Group();            // a talajon áll (y = 0)
  const zold = anyag("#18c25b"), sotet = anyag("#0f8f45"), krem = anyag("#ffe9bd", { roughness: 0.75, clearcoat: 0.1 });
  const feher = anyag("#ffffff", { roughness: 0.12, clearcoat: 1 }), tinta = anyag("#16233a", { roughness: 0.15, clearcoat: 1 });
  const arany = anyag("#ffc93d", { roughness: 0.25, metalness: 0.35 }), kek = anyag("#2a3f7a");
  const resz = {};

  // lábak + cipők
  resz.lab = [];
  for (const s of [-1, 1]) {
    const l = new THREE.Group(); l.position.set(s * 0.42, 0, 0.08);
    const cs = new THREE.Mesh(new THREE.CapsuleGeometry(0.1, 0.3, 6, 14), krem); cs.position.y = 0.42; l.add(cs);
    const cipo = new THREE.Mesh(new THREE.SphereGeometry(0.27, 24, 18), anyag("#ff7a59")); cipo.scale.set(1.05, 0.58, 1.35); cipo.position.set(0, 0.15, 0.1); l.add(cipo);
    g.add(l); resz.lab.push(l);
  }

  // test (a könyv): a pivot a talpnál van, így a „nyúlás-összenyomódás” természetes
  const nyuj = new THREE.Group(); g.add(nyuj); resz.nyuj = nyuj;
  const test = new THREE.Group(); test.position.y = 1.3; test.rotation.y = 0.5; nyuj.add(test); resz.test = test;
  const el = new THREE.Mesh(new RoundedBoxGeometry(1.72, 1.52, 0.15, 5, 0.07), zold); el.position.z = 0.36; test.add(el);
  const hat = new THREE.Mesh(new RoundedBoxGeometry(1.72, 1.52, 0.15, 5, 0.07), zold); hat.position.z = -0.36; test.add(hat);
  const gerinc = new THREE.Mesh(new RoundedBoxGeometry(0.17, 1.52, 0.88, 5, 0.07), sotet); gerinc.position.x = -0.78; test.add(gerinc);
  const lapok = new THREE.Mesh(new RoundedBoxGeometry(1.5, 1.4, 0.64, 3, 0.03), krem); lapok.position.x = 0.02; test.add(lapok);
  for (const z of [-0.18, 0, 0.18]) { const v = new THREE.Mesh(new THREE.BoxGeometry(0.02, 1.34, 0.012), anyag("#e8d6ab", { roughness: 0.9, clearcoat: 0 })); v.position.set(0.78, 0, z); test.add(v); }
  const szalag = new THREE.Mesh(new RoundedBoxGeometry(0.1, 0.5, 0.02, 2, 0.01), anyag("#ff5d6c")); szalag.position.set(0.3, -0.92, 0.2); szalag.rotation.z = 0.12; test.add(szalag);

  // arc az elülső borítón (z ≈ 0.435)
  const arc = new THREE.Group(); arc.position.z = 0.44; test.add(arc); resz.arc = arc;
  resz.szem = [];
  for (const s of [-1, 1]) {
    const cs = new THREE.Group(); cs.position.set(s * 0.37, 0.2, 0);
    const fe = new THREE.Mesh(new THREE.SphereGeometry(0.255, 32, 24), feher); fe.scale.set(1, 1.12, 0.45); cs.add(fe);
    const pup = new THREE.Group(); pup.position.z = 0.08; cs.add(pup);
    const pu = new THREE.Mesh(new THREE.SphereGeometry(0.15, 24, 18), tinta); pu.scale.set(1, 1.05, 0.5); pup.add(pu);
    const k = new THREE.Mesh(new THREE.SphereGeometry(0.05, 12, 10), new THREE.MeshBasicMaterial({ color: "#ffffff" })); k.position.set(0.05, 0.06, 0.07); pup.add(k);
    const k2 = new THREE.Mesh(new THREE.SphereGeometry(0.024, 10, 8), new THREE.MeshBasicMaterial({ color: "#ffffff" })); k2.position.set(-0.05, -0.05, 0.065); pup.add(k2);
    arc.add(cs); resz.szem.push({ csoport: cs, pup, fe });
  }
  resz.szemoldok = [];
  for (const s of [-1, 1]) {
    const b = new THREE.Mesh(new THREE.CapsuleGeometry(0.035, 0.2, 4, 10), anyag("#173d28", { clearcoat: 0.3 })); b.position.set(s * 0.37, 0.58, 0.02);
    arc.add(b); resz.szemoldok.push(b);
  }
  for (const s of [-1, 1]) {
    const p = new THREE.Mesh(new THREE.SphereGeometry(0.13, 20, 14), new THREE.MeshBasicMaterial({ color: "#ff7fa3", transparent: true, opacity: 0.75 }));
    p.scale.set(1.15, 0.7, 0.15); p.position.set(s * 0.66, -0.12, 0.0); arc.add(p);
  }
  const mosoly = new THREE.Mesh(new THREE.TorusGeometry(0.17, 0.03, 10, 28, Math.PI), anyag("#16233a", { clearcoat: 0.4 })); mosoly.rotation.z = Math.PI; mosoly.position.set(0, -0.06, 0.01); arc.add(mosoly); resz.mosoly = mosoly;
  const szaj = new THREE.Group(); szaj.position.set(0, -0.02, 0.01); arc.add(szaj); resz.szaj = szaj;
  const felkor = new THREE.Mesh(new THREE.CircleGeometry(0.21, 28, Math.PI, Math.PI), new THREE.MeshBasicMaterial({ color: "#4a1220" })); szaj.add(felkor);
  const nyelv = new THREE.Mesh(new THREE.CircleGeometry(0.11, 20, Math.PI, Math.PI), new THREE.MeshBasicMaterial({ color: "#ff6f8e" })); nyelv.position.set(0, -0.1, 0.004); szaj.add(nyelv);
  szaj.scale.set(1, 0.001, 1);

  // karok (vállpont a könyv szélén), fehér „kesztyű” kéz
  resz.kar = [];
  for (const s of [-1, 1]) {
    const v = new THREE.Group(); v.position.set(s * 0.96, -0.05, 0.05); test.add(v);
    const cs = new THREE.Mesh(new THREE.CapsuleGeometry(0.095, 0.34, 6, 12), krem); cs.position.set(s * 0.12, -0.2, 0); cs.rotation.z = s * 0.35; v.add(cs);
    const ke = new THREE.Mesh(new THREE.SphereGeometry(0.15, 20, 16), feher); ke.position.set(s * 0.22, -0.43, 0.02); v.add(ke);
    resz.kar.push({ v, s });
  }

  // diplomaosztó-sapka
  const sapka = new THREE.Group(); sapka.position.set(0.02, 0.76, 0); sapka.rotation.z = -0.1; test.add(sapka); resz.sapka = sapka;
  const alap = new THREE.Mesh(new THREE.CylinderGeometry(0.46, 0.5, 0.28, 32), kek); alap.position.y = 0.1; sapka.add(alap);
  const lap = new THREE.Mesh(new RoundedBoxGeometry(1.2, 0.07, 1.2, 3, 0.03), kek); lap.position.y = 0.27; lap.rotation.y = Math.PI / 4; sapka.add(lap);
  const gomb = new THREE.Mesh(new THREE.SphereGeometry(0.075, 16, 12), arany); gomb.position.y = 0.33; sapka.add(gomb);
  const zsinor = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.62, 6), arany); zsinor.position.set(0.31, 0.2, 0.31); zsinor.rotation.z = -0.5; zsinor.rotation.x = 0.1; sapka.add(zsinor);
  const bojt = new THREE.Mesh(new THREE.SphereGeometry(0.07, 14, 10), arany); bojt.position.set(0.5, -0.07, 0.4); bojt.scale.set(1, 1.5, 1); sapka.add(bojt);
  resz.bojt = bojt;

  // gondolat-pöttyök és könnycsepp (alapból rejtve)
  gondolPontok = [];
  for (let i = 0; i < 3; i++) {
    const p = new THREE.Mesh(new THREE.SphereGeometry(0.07 + i * 0.02, 14, 10), new THREE.MeshBasicMaterial({ color: "#ffffff" }));
    p.position.set(1.05 + i * 0.2, 2.75 + i * 0.16, 0.2); p.visible = false; g.add(p); gondolPontok.push(p);
  }
  konnyek = new THREE.Mesh(new THREE.SphereGeometry(0.07, 12, 10), anyag("#7fd0ff", { transmission: 0, roughness: 0.05 })); konnyek.scale.set(0.8, 1.2, 0.8); konnyek.visible = false; arc.add(konnyek);

  // puha árnyék a talajon
  const c = document.createElement("canvas"); c.width = c.height = 128;
  const x = c.getContext("2d"), gr = x.createRadialGradient(64, 64, 4, 64, 64, 62); gr.addColorStop(0, "rgba(0,0,0,.42)"); gr.addColorStop(1, "rgba(0,0,0,0)"); x.fillStyle = gr; x.fillRect(0, 0, 128, 128);
  arnyek = new THREE.Mesh(new THREE.PlaneGeometry(2.6, 2.6), new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false }));
  arnyek.rotation.x = -Math.PI / 2; arnyek.position.y = 0.01; g.add(arnyek);
  return { g, resz };
}

function inicializal() {
  const vaszon = document.createElement("canvas");
  R = new THREE.WebGLRenderer({ canvas: vaszon, alpha: true, antialias: true, premultipliedAlpha: true });
  R.setPixelRatio(1); R.setSize(MERET, MERET, false); R.setClearColor(0x000000, 0);
  R.toneMapping = THREE.ACESFilmicToneMapping; R.toneMappingExposure = 0.88;
  scene = new THREE.Scene();
  const pm = new THREE.PMREMGenerator(R); scene.environment = pm.fromScene(new RoomEnvironment(), 0.04).texture; scene.environmentIntensity = 0.5;
  camera = new THREE.PerspectiveCamera(27, 1, 0.1, 50); camera.position.set(0.1, 2.0, 8.2); camera.lookAt(0, 1.58, 0);
  const kulcs = new THREE.DirectionalLight("#fff1dd", 2.3); kulcs.position.set(-3.5, 6, 5); scene.add(kulcs);
  const tolto = new THREE.DirectionalLight("#bcd6ff", 0.7); tolto.position.set(4, 2, 4); scene.add(tolto);
  const pereme = new THREE.DirectionalLight("#9affc4", 1.6); pereme.position.set(3, 4, -5); scene.add(pereme);
  const m = epit(); lapi = m.g; resz = m.resz; scene.add(lapi);
  dino = epitDino(anyag); scene.add(dino.g);
  kesz = true;
}

// ----------------------------------------------------------------------------------- állapotok
const CEL = {
  idle:    { szem: 1, szemoldY: 0, szemoldSzog: 0, mosoly: 1, nyit: 0, kar: 0.5, ferde: 0, elore: 0, nezY: 0, nezX: 0 },
  orul:    { szem: 0.62, szemoldY: 0.09, szemoldSzog: -0.12, mosoly: 1, nyit: 1, kar: 2.4, ferde: 0, elore: -0.04, nezY: 0.02, nezX: 0 },
  szomoru: { szem: 0.8, szemoldY: -0.03, szemoldSzog: 0.42, mosoly: -1, nyit: 0, kar: 0.1, ferde: 0, elore: 0.16, nezY: -0.07, nezX: 0 },
  beszel:  { szem: 1, szemoldY: 0.02, szemoldSzog: 0, mosoly: 1, nyit: 0, kar: 0.7, ferde: 0, elore: 0, nezY: 0, nezX: 0 },
  gondol:  { szem: 1, szemoldY: 0.05, szemoldSzog: 0.12, mosoly: 0.2, nyit: 0, kar: 0.35, ferde: 0.15, elore: 0, nezY: 0.09, nezX: 0.1 },
  alszik:  { szem: 0.07, szemoldY: -0.03, szemoldSzog: 0, mosoly: 0.5, nyit: 0, kar: 0.2, ferde: 0.05, elore: 0.06, nezY: 0, nezX: 0 },
};
const sima = (a, b, k) => a + (b - a) * k;

function ujPeldany(el) {
  const vaszon = document.createElement("canvas"); vaszon.style.cssText = "width:100%;height:100%;display:block;pointer-events:none";
  const ctx = vaszon.getContext("2d");
  const p = { el, vaszon, ctx, t0: performance.now(), pose: { ...CEL.idle }, allapot: "", n: "", pislog: 2 + Math.random() * 2, pislogT: -1, nezSima: { x: 0, y: 0 } };
  el.querySelectorAll("svg").forEach((s) => (s.style.display = "none"));
  el.appendChild(vaszon);
  el.style.cursor = "pointer";
  el.addEventListener("pointerdown", () => { el.dataset.a = "orul"; el.dataset.n = String(performance.now()); window.dispatchEvent(new CustomEvent("lapi-kattint")); setTimeout(() => { if (el.dataset.a === "orul") el.dataset.a = "idle"; }, 900); });
  peldanyok.add(p);
  return p;
}

const LAPI_ALIAS = { olvas: "idle", tanit: "idle", figyel: "gondol", integet: "orul", tapsol: "orul", tancol: "orul", forog: "orul", edz: "orul", fut: "orul", bolint: "orul", bator: "orul", szalutal: "orul", csodalkozik: "orul", nyujtozik: "idle", razza: "szomoru" };   // a dínó új állapotai Lapinál
function lapiKocka(p, ido, dt) {
  const el = p.el, a = CEL[el.dataset.a] ? el.dataset.a : (LAPI_ALIAS[el.dataset.a] || "idle");
  if (a !== p.allapot || el.dataset.n !== p.n) { p.allapot = a; p.n = el.dataset.n; p.t0 = ido; }
  const t = (ido - p.t0) / 1000, ossz = ido / 1000;
  const cel = { ...CEL[a] };
  let ugras = 0, nyom = 0;                                  // ugrás magassága, összenyomódás (+: lapul)
  if (a === "orul") {
    const c = t % 1.5, u = c / 0.8;
    if (u < 1) { ugras = Math.sin(Math.PI * Math.min(1, u)) * 0.5; nyom = u < 0.14 ? u / 0.14 : u > 0.86 ? (u - 0.86) / 0.14 : -0.2 * Math.sin(Math.PI * u); }
    cel.kar = 2.3 + Math.sin(ossz * 14) * 0.25;
  } else if (a === "szomoru") { cel.ferde = Math.sin(t * 9) * 0.03 * Math.max(0, 1 - t); }
  else if (a === "beszel") { cel.nyit = 0.12 + 0.62 * Math.abs(Math.sin(ossz * 9.3)) * (0.6 + 0.4 * Math.sin(ossz * 3.1)); cel.elore = Math.sin(ossz * 4) * 0.02; }
  // pislogás
  p.pislog -= dt; if (p.pislog <= 0) { p.pislogT = 0; p.pislog = 2.5 + Math.random() * 3; }
  let pis = 1; if (p.pislogT >= 0) { p.pislogT += dt; pis = Math.max(0.05, Math.abs(1 - Math.sin(Math.min(1, p.pislogT / 0.16) * Math.PI))); if (p.pislogT > 0.16) p.pislogT = -1; }
  // simítás a célhoz
  const k = 1 - Math.exp(-dt * 11);
  for (const kulcs of Object.keys(cel)) p.pose[kulcs] = sima(p.pose[kulcs], cel[kulcs], k);
  const P = p.pose;
  // tekintet: az egérre / ujjra néz
  const rect = el.getBoundingClientRect(), cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 3;
  const tx = mutato.aktiv ? Math.max(-1, Math.min(1, (mutato.x - cx) / 400)) : 0, ty = mutato.aktiv ? Math.max(-1, Math.min(1, (cy - mutato.y) / 400)) : 0;
  p.nezSima.x = sima(p.nezSima.x, tx, k * 0.6); p.nezSima.y = sima(p.nezSima.y, ty, k * 0.6);

  // --- a modell beállítása
  const l = lapi, r = resz, lel = Math.sin(ossz * 2.2) * 0.5 + 0.5;
  l.position.y = ugras; l.rotation.set(0, 0, 0);
  const sy = 1 - nyom * 0.14 + lel * 0.012 + (ugras > 0.05 ? 0.07 : 0), sxz = 1 + nyom * 0.08 - lel * 0.006 - (ugras > 0.05 ? 0.035 : 0);
  r.nyuj.scale.set(sxz, sy, sxz);
  r.test.rotation.set(P.elore - p.nezSima.y * 0.12, 0.5 + p.nezSima.x * 0.3, P.ferde + Math.sin(ossz * 1.1) * 0.025);
  for (const sz of r.szem) {
    sz.csoport.scale.y = Math.max(0.06, P.szem * pis);
    sz.pup.position.set((P.nezX + p.nezSima.x * 0.5) * 0.14, (P.nezY + p.nezSima.y * 0.4) * 0.14, 0.08);
  }
  r.szemoldok.forEach((b, i) => { const s = i === 0 ? -1 : 1; b.position.y = 0.58 + P.szemoldY + (a === "gondol" && s === -1 ? 0.07 : 0); b.rotation.z = Math.PI / 2 + (s === -1 ? 1 : -1) * P.szemoldSzog; });
  r.mosoly.scale.y = P.mosoly; r.mosoly.position.y = P.mosoly < 0 ? -0.16 : -0.06; r.mosoly.visible = P.nyit < 0.2;
  r.szaj.scale.y = Math.max(0.001, P.nyit); r.szaj.visible = P.nyit > 0.04;
  r.kar.forEach((q) => { q.v.rotation.z = q.s * (P.kar + Math.sin(ossz * 1.6 + q.s) * 0.04); });
  r.lab.forEach((q, i) => { q.position.y = ugras > 0.05 ? 0.06 : 0; });
  r.sapka.rotation.z = -0.1 + Math.sin(ossz * 2.2 + 1) * 0.015 + (a === "orul" ? Math.sin(t * 18) * 0.03 : 0);
  r.bojt.position.x = 0.5 + Math.sin(ossz * 2.6) * 0.025;
  gondolPontok.forEach((q, i) => { q.visible = a === "gondol"; if (q.visible) q.scale.setScalar(0.5 + 0.5 * Math.max(0, Math.sin(ossz * 3.2 - i * 0.9))); });
  konnyek.visible = a === "szomoru"; if (konnyek.visible) { const f = (t * 0.9) % 1; konnyek.position.set(-0.5, 0.0 - f * 0.45, 0.07); konnyek.scale.setScalar(0.8 * (1 - f * 0.4)); }
  arnyek.scale.setScalar(1 - ugras * 0.35); arnyek.material.opacity = 1 - ugras * 0.45;

  R.render(scene, camera);
  const w = Math.round(rect.width * Math.min(2, devicePixelRatio || 1)), h = Math.round(rect.height * Math.min(2, devicePixelRatio || 1));
  if (p.vaszon.width !== w || p.vaszon.height !== h) { p.vaszon.width = w; p.vaszon.height = h; }
  p.ctx.clearRect(0, 0, w, h); p.ctx.drawImage(R.domElement, 0, 0, w, h);
}

function masol(p, rect) {
  const w = Math.round(rect.width * Math.min(2, devicePixelRatio || 1)), h = Math.round(rect.height * Math.min(2, devicePixelRatio || 1));
  if (p.vaszon.width !== w || p.vaszon.height !== h) { p.vaszon.width = w; p.vaszon.height = h; }
  p.ctx.clearRect(0, 0, w, h); p.ctx.drawImage(R.domElement, 0, 0, w, h);
}

// a kabala fajtája az oldal beállításából jön: <html data-kabala="dino|lapi"> (alap: dínó)
const KAMERA = { lapi: [[0.1, 2.0, 8.2], [0, 1.58, 0]], dino: [[0.1, 2.1, 8.7], [0, 1.72, 0]] };
function kepkocka(p, ido, dt) {
  const tipus = document.documentElement.dataset.kabala === "lapi" ? "lapi" : "dino";
  lapi.visible = tipus === "lapi"; dino.g.visible = tipus === "dino";
  const [pos, nez] = KAMERA[tipus]; camera.position.set(...pos); camera.lookAt(...nez);
  if (tipus === "lapi") return lapiKocka(p, ido, dt);
  const rect = p.el.getBoundingClientRect();
  dinoFrissit(dino, p, ido, dt, mutato, rect);
  R.render(scene, camera);
  masol(p, rect);
}

let utolso = 0, futVan = false;
function hurok(ido) {
  if (!document.hidden && ido - utolso >= KEPKOCKA_MS) {
    const dt = Math.min(0.1, (ido - utolso) / 1000); utolso = ido;
    for (const p of [...peldanyok]) {
      if (!p.el.isConnected) { peldanyok.delete(p); continue; }
      const r = p.el.getBoundingClientRect();
      if (r.width < 2 || r.bottom < -50 || r.top > innerHeight + 50) continue;
      kepkocka(p, ido, dt);
    }
  }
  requestAnimationFrame(hurok);
}

function felvesz() {
  document.querySelectorAll(".csira:not([data-m])").forEach((el) => {
    if (!kesz) { try { inicializal(); } catch (e) { console.warn("Lapi 3D nem indul, marad az SVG:", e); window.__lapi3d = "nincs"; document.documentElement.classList.add("k3d-nincs"); return; } }
    el.dataset.m = "1"; ujPeldany(el);
  });
  if (kesz && !futVan) { futVan = true; requestAnimationFrame(hurok); }
}
window.addEventListener("pointermove", (e) => { mutato.x = e.clientX; mutato.y = e.clientY; mutato.aktiv = true; }, { passive: true });
window.addEventListener("pointerleave", () => (mutato.aktiv = false));
new MutationObserver(felvesz).observe(document.body, { childList: true, subtree: true });
felvesz();
if (kesz) window.__lapi3d = "indul";
