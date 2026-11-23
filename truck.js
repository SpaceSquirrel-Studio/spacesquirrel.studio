// A tiny Kneady, on the demo truck. Hover the truck: it lights up and its button shows. Drag the
// truck or its button up and down to squash it, sideways to lean it. Click the button for its menu:
// Color, Lights, Door and Wheels.
//
// The truck is rendered in Blender as layers (truck/*.webp, made by the render and pack scripts):
// the truck with white paint and with black paint, the door at eight more angles, the front wheels
// at nine steering angles, and the light the headlights add. They are linear light one stop down;
// this script composes them in linear light (a paint color is black paint plus the color times
// the difference) and puts the stop back, so any color, the lights, the door and the wheels all
// come out as Blender would render them. Squash and lean are a 2D squash and slant of the result.
//
// The buttons are drawn as Kneady draws its own (Kneady's draw.py, _draw_buttons): a dark circle
// edged in the region's color, its icon in a lighter shade of that color with a dark edge, filled
// with the lighter shade under the mouse, filled with the color while a toggle is on, a small
// badge on the rim of a button that opens a menu, a name in a dark box under the mouse, and a
// menu's buttons in a ring round its own: the first at the top, then clockwise. Greg, 22 November
// 2026: "The buttons on the website should look like the default kneady buttons."
(function () {
  const stage = document.querySelector('.truck-stage');
  if (!stage) return;
  const ROOT = stage.dataset.src || 'truck/';
  // the truck's files are fetched with this script's own ?v=, so a new version of the page loads
  // the new renders, not ones the browser kept from before (GitHub Pages lets it keep them 10 minutes)
  const VERSION = (document.currentScript && new URL(document.currentScript.src).search) || '';
  const canvas = stage.querySelector('canvas');
  const ctx = canvas.getContext('2d');
  const svg = stage.querySelector('svg');
  const hint = stage.querySelector('.stage-hint');
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const NS = 'http://www.w3.org/2000/svg';

  // ----- Kneady's look -----
  const REGION = [0.95, 0.55, 0.2];                 // the truck's Body region in Blender
  const bright = REGION.map(c => Math.min(c + 0.25, 1));
  const rgb = (c, a = 1) => `rgba(${c.map(v => Math.round(v * 255)).join(',')},${a})`;
  const COLOR = rgb(REGION, 0.95), BRIGHT = rgb(bright), FULL = rgb(REGION);
  const DARK = 'rgba(13,13,15,0.95)', IDLE = 'rgba(20,20,23,0.8)', LABEL_FILL = 'rgba(13,13,15,0.8)';
  // The hovered truck is outlined, Kneady's Highlight: Outline, not filled (its default, Fill):
  // a fill in the region's color would hide the paint the Color button has just changed
  const OUTLINE_PX = 3.5;                           // the band round the truck, outside its edge
  const RADIUS_PX = 17;                             // Kneady's Medium (14 px) at a 1.2 interface scale
  const SPACING = 34 / 14, BADGE = 0.22, GRAPHIC = 0.78;
  const SPAN = 0.86, SHAFT = 0.15, HEAD = 0.46, HEAD_LENGTH = 0.3, EDGE = 0.085;

  // ----- the truck's state -----
  const S = { hue: 0, sat: 1, val: 0.873, lights: true, door: 0, steer: 0, sy: 1, lean: 0 };
  const SY_MIN = 0.6, SY_MAX = 1.3, LEAN_MAX = 0.3;
  let M = null;                                     // truck.json
  let W = 1000, H = 800;                            // the render's size; coordinates below are in it
  // The canvas reaches PAD of the render past the stage on every side (style.css), so a stretched
  // or leaning truck isn't cut off at the stage's edge. OX, OY: where the render starts in it.
  const PAD = 0.2;
  let OX = 0, OY = 0;

  // ----- loading and decoding the layers -----
  const LIN = new Float32Array(256);
  for (let i = 0; i < 256; i++) { const c = i / 255; LIN[i] = c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); }
  const ENC = new Uint8ClampedArray(4097);
  for (let i = 0; i <= 4096; i++) { const l = i / 4096; ENC[i] = Math.round(255 * (l <= 0.0031308 ? l * 12.92 : 1.055 * Math.pow(l, 1 / 2.4) - 0.055)); }
  const enc = l => ENC[l <= 0 ? 0 : l >= 1 ? 4096 : (l * 4096 + 0.5) | 0];

  function image(name) {
    const img = new Image();
    img.decoding = 'async';
    img.src = ROOT + name + '.webp' + VERSION;
    return img.decode().then(() => img);
  }
  // premultiplied linear color (3 a pixel) and alpha, from an image's straight sRGB bytes
  function decode(img, opaque) {
    const c = document.createElement('canvas');
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    const x = c.getContext('2d', { willReadFrequently: true });
    x.drawImage(img, 0, 0);
    const d = x.getImageData(0, 0, c.width, c.height).data, n = d.length / 4;
    const p = new Float32Array(n * 3), a = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const al = opaque ? 1 : d[4 * i + 3] / 255;
      a[i] = al;
      p[3 * i] = LIN[d[4 * i]] * al; p[3 * i + 1] = LIN[d[4 * i + 1]] * al; p[3 * i + 2] = LIN[d[4 * i + 2]] * al;
    }
    return { p, a, w: c.width, h: c.height };
  }
  const L = { doorA: [], doorB: [], wheels: [] };   // decoded layers, filled as they load

  // ----- composing -----
  let work = null, composed = null, tint = null, cImg = null, tImg = null, mask = null;
  function rect(r) { return { x: r[0], y: r[1], w: r[2], h: r[3] }; }
  function union(rs) {
    const x0 = Math.min(...rs.map(r => r.x)), y0 = Math.min(...rs.map(r => r.y));
    const x1 = Math.max(...rs.map(r => r.x + r.w)), y1 = Math.max(...rs.map(r => r.y + r.h));
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }
  function hsv(h, s, v) {                           // Blender's HSV node: the values come out linear
    h = ((h % 1) + 1) % 1 * 6; const i = Math.floor(h), f = h - i;
    const p = v * (1 - s), q = v * (1 - s * f), t = v * (1 - s * (1 - f));
    return [[v, t, p], [q, v, p], [p, v, t], [p, q, v], [t, p, v], [v, p, q]][i % 6];
  }
  // the two loaded frames a value 0..1 falls between, over n steps, and how far between them;
  // `frame(k)` gives frame k, or undefined while it is still loading
  function between(v, n, frame) {
    const f = Math.min(Math.max(v, 0), 1) * n;
    let i = Math.min(Math.floor(f), n - 1), t = f - i;
    let f0 = frame(i), f1 = frame(i + 1);
    if (f0 === undefined) { i = 0; while (i <= n && frame(i) === undefined) i++; f0 = frame(i); f1 = f0; t = 0; }
    if (f1 === undefined) { f1 = f0; t = 0; }
    return [f0, f1, t];
  }
  // the door's frame k: 0 is the truck itself (null), 1..8 its crops once loaded
  const doorFrame = k => k === 0 ? null : L.doorA[k - 1] && L.doorB[k - 1] ? [L.doorA[k - 1], L.doorB[k - 1]] : undefined;
  const wheelFrame = k => L.wheels[k];

  function compose() {
    if (!M || !L.A) return;
    const [cr, cg, cb] = hsv(S.hue, S.sat, S.val);
    const D = M.door, Wh = M.wheels, Li = M.lights;
    const [df0, df1, dt] = between(S.door, 8, doorFrame);
    const [w0, w1, wt] = between((S.steer + 1) / 2, 8, wheelFrame);
    const d0 = df0 && df0[0], d1 = df1 && df1[0], e0 = df0 && df0[1], e1 = df1 && df1[1];
    const doorOn = !!(d0 || d1);
    const out = cImg.data, tout = tImg.data, scale = M.scale;
    const start = 0.76, dd = 1 - start;
    const ww = work.w, wh = work.h;
    for (let y = 0; y < wh; y++) {
      const gy = y + work.y;
      for (let x = 0; x < ww; x++) {
        const gx = x + work.x, gi = gy * W + gx, oi = y * ww + x;
        let ar = L.A.p[3 * gi], ag = L.A.p[3 * gi + 1], ab = L.A.p[3 * gi + 2], al = L.A.a[gi];
        let br = L.B.p[3 * gi], bg = L.B.p[3 * gi + 1], bb = L.B.p[3 * gi + 2];
        // the door, between two of its frames (frame 0 is the truck itself)
        if (doorOn && gx >= D.x && gx < D.x + D.w && gy >= D.y && gy < D.y + D.h) {
          const di = (gy - D.y) * D.w + (gx - D.x), q = 3 * di, u = 1 - dt;
          // the first frame: the truck itself (frame 0) or a crop
          let a0r = ar, a0g = ag, a0b = ab, b0r = br, b0g = bg, b0b = bb, al0 = al;
          if (d0) { a0r = d0.p[q]; a0g = d0.p[q + 1]; a0b = d0.p[q + 2]; al0 = d0.a[di]; b0r = e0.p[q]; b0g = e0.p[q + 1]; b0b = e0.p[q + 2]; }
          let a1r = a0r, a1g = a0g, a1b = a0b, b1r = b0r, b1g = b0g, b1b = b0b, al1 = al0;
          if (d1) { a1r = d1.p[q]; a1g = d1.p[q + 1]; a1b = d1.p[q + 2]; al1 = d1.a[di]; b1r = e1.p[q]; b1g = e1.p[q + 1]; b1b = e1.p[q + 2]; }
          ar = a0r * u + a1r * dt; ag = a0g * u + a1g * dt; ab = a0b * u + a1b * dt;
          br = b0r * u + b1r * dt; bg = b0g * u + b1g * dt; bb = b0b * u + b1b * dt;
          al = al0 * u + al1 * dt;
        }
        // the paint: black paint plus the color times what white paint adds
        let r = br + cr * (ar - br), g = bg + cg * (ag - bg), b = bb + cb * (ab - bb);
        // the front wheels, over the truck
        if (w0 && gx >= Wh.x && gx < Wh.x + Wh.w && gy >= Wh.y && gy < Wh.y + Wh.h) {
          const wi = (gy - Wh.y) * Wh.w + (gx - Wh.x);
          const wa = w0.a[wi] + (w1.a[wi] - w0.a[wi]) * wt;
          if (wa > 0) {
            const k = 1 - wa;
            r = w0.p[3 * wi] + (w1.p[3 * wi] - w0.p[3 * wi]) * wt + r * k;
            g = w0.p[3 * wi + 1] + (w1.p[3 * wi + 1] - w0.p[3 * wi + 1]) * wt + g * k;
            b = w0.p[3 * wi + 2] + (w1.p[3 * wi + 2] - w0.p[3 * wi + 2]) * wt + b * k;
            al = wa + al * k;
          }
        }
        mask[oi] = al;
        // the light the headlights add
        if (S.lights && L.lights && gx >= Li.x && gx < Li.x + Li.w && gy >= Li.y && gy < Li.y + Li.h) {
          const li = 3 * ((gy - Li.y) * Li.w + (gx - Li.x));
          r += L.lights.p[li]; g += L.lights.p[li + 1]; b += L.lights.p[li + 2];
        }
        // the stop back, and the highlights rolled off as Khronos PBR Neutral rolls them
        r *= scale; g *= scale; b *= scale;
        let peak = r > g ? (r > b ? r : b) : (g > b ? g : b);
        const glow = peak > 1 ? 1 : peak;
        const oa = al > glow ? al : glow;
        if (peak > start) {
          const np = 1 - dd * dd / (peak + dd - start), k = np / peak;
          const mix = 1 - 1 / (0.15 * (peak - np) + 1);
          r = (r * k) * (1 - mix) + np * mix; g = (g * k) * (1 - mix) + np * mix; b = (b * k) * (1 - mix) + np * mix;
        }
        const o = 4 * oi;
        if (oa > 0.002) {
          const inv = 1 / oa;
          out[o] = enc(r * inv); out[o + 1] = enc(g * inv); out[o + 2] = enc(b * inv); out[o + 3] = oa * 255 + 0.5;
        } else out[o + 3] = 0;
        tout[o + 3] = al * 255 + 0.5;
      }
    }
    composed.getContext('2d').putImageData(cImg, 0, 0);
    tint.getContext('2d').putImageData(tImg, 0, 0);
    outlineFor();
  }
  // the outline: the truck's shape grown by the band, less the shape itself
  const MARGIN = 16;
  let outline = null;
  function outlineFor() {
    if (!tint) return;
    if (!outline) { outline = document.createElement('canvas'); outline.width = work.w + 2 * MARGIN; outline.height = work.h + 2 * MARGIN; }
    const o = outline.getContext('2d'), w = Math.min(OUTLINE_PX * unit, MARGIN - 1);
    o.globalCompositeOperation = 'source-over';
    o.clearRect(0, 0, outline.width, outline.height);
    for (let i = 0; i < 24; i++) {
      const a = i * Math.PI / 12;
      o.drawImage(tint, MARGIN + Math.cos(a) * w, MARGIN + Math.sin(a) * w);
    }
    o.globalCompositeOperation = 'destination-out';
    o.drawImage(tint, MARGIN, MARGIN);
    o.globalCompositeOperation = 'source-over';
  }

  // ----- drawing: the truck squashed and leaned about where it meets the ground -----
  const ground = () => ({ x: M.truck.center[0], y: M.truck.ground });
  function squash() { const sy = S.sy; return [Math.pow(sy, -0.35), sy]; }   // squashed, it spreads a little
  function toScreen(p) {
    const G = ground(), [sx, sy] = squash();
    return { x: G.x + sx * (p.x - G.x) - S.lean * (p.y - G.y), y: G.y + sy * (p.y - G.y) };
  }
  function fromScreen(p) {
    const G = ground(), [sx, sy] = squash();
    const y = G.y + (p.y - G.y) / sy;
    return { x: G.x + (p.x - G.x + S.lean * (y - G.y)) / sx, y };
  }
  let drawQueued = false;
  function draw() {
    drawQueued = false;
    if (!composed) return;
    const G = ground(), [sx, sy] = squash();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    // a soft shadow where the wheels meet the ground
    const tr = M.truck.rect, rx = tr[2] * 0.5 * sx, ry = 30;
    ctx.save();
    ctx.translate(OX + G.x, OY + G.y - 8); ctx.scale(1, ry / rx);
    const sh = ctx.createRadialGradient(0, 0, 0, 0, 0, rx);
    sh.addColorStop(0, 'rgba(0,0,0,0.55)'); sh.addColorStop(0.6, 'rgba(0,0,0,0.25)'); sh.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = sh; ctx.beginPath(); ctx.arc(0, 0, rx, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
    ctx.setTransform(sx, 0, -S.lean, sy, OX + G.x - sx * G.x + S.lean * G.y, OY + G.y - sy * G.y);
    ctx.drawImage(composed, work.x, work.y);
    if (active && !drag && outline) ctx.drawImage(outline, work.x - MARGIN, work.y - MARGIN);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    drawButtons();
  }
  function redraw() { if (!drawQueued) { drawQueued = true; requestAnimationFrame(draw); } }
  let composeQueued = false;
  function recompose() {
    if (composeQueued) return;
    composeQueued = true;
    requestAnimationFrame(() => { composeQueued = false; compose(); draw(); });
  }

  // ----- the buttons, as Kneady draws them -----
  const BUTTONS = {
    main:   { name: 'Shape', across: true, up: true, menu: true },
    color:  { name: 'Color', across: true },
    lights: { name: 'Lights', toggle: true },
    door:   { name: 'Door', across: true, click: true },
    wheels: { name: 'Wheels', across: true },
  };
  const RING = ['color', 'lights', 'door', 'wheels'];  // the first at the top, then clockwise
  let unit = 1;                                         // canvas units in a CSS pixel
  const radius = () => RADIUS_PX * unit;
  function centers() {
    const c = toScreen({ x: M.truck.center[0], y: M.truck.center[1] });
    const out = { main: c };
    if (menuOpen) {
      const ring = radius() * SPACING;
      RING.forEach((k, i) => {
        const a = -Math.PI / 2 + i * Math.PI * 2 / RING.length;
        out[k] = { x: c.x + Math.cos(a) * ring, y: c.y + Math.sin(a) * ring };
      });
    }
    return out;
  }
  function lit(k) { return k === 'lights' ? S.lights : k === 'door' ? S.door > 0.5 : false; }
  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const a in attrs) e.setAttribute(a, attrs[a]);
    if (parent) parent.appendChild(e);
    return e;
  }
  // an arrow along x from -SPAN to SPAN with a head at each end, in -1..1, turned for up
  function arrow(vertical) {
    const s = SHAFT / 2, h = HEAD / 2, b = SPAN - HEAD_LENGTH;
    const pts = [[-SPAN, 0], [-b, h], [-b, s], [b, s], [b, h], [SPAN, 0], [b, -h], [b, -s], [-b, -s], [-b, -h]];
    return pts.map(([x, y]) => vertical ? [y, x] : [x, y]);
  }
  function icon(g, def, on, filled, size) {
    const ink = filled ? DARK : BRIGHT;
    if (def.toggle) {
      // a ring, with a dot in it while on (Kneady's switch_glyph)
      if (!filled) el('circle', { r: 0.6 * size, fill: 'none', stroke: DARK, 'stroke-width': 0.36 * size }, g);
      el('circle', { r: 0.6 * size, fill: 'none', stroke: ink, 'stroke-width': 0.2 * size }, g);
      if (on) {
        if (!filled) el('circle', { r: 0.34 * size, fill: DARK }, g);
        el('circle', { r: 0.26 * size, fill: ink }, g);
      }
      return;
    }
    const shapes = [];
    if (def.up) shapes.push(arrow(true));
    if (def.across) shapes.push(arrow(false));
    const pts = sh => sh.map(([x, y]) => `${(x * size).toFixed(2)},${(y * size).toFixed(2)}`).join(' ');
    if (!filled) shapes.forEach(sh => el('polygon', { points: pts(sh), fill: DARK, stroke: DARK, 'stroke-width': 2 * EDGE * size, 'stroke-linejoin': 'round' }, g));
    shapes.forEach(sh => el('polygon', { points: pts(sh), fill: ink }, g));
  }
  function label(g, text, c, place, under) {
    const r = radius(), scale = r / 14, size = 11 * scale;
    const t = el('text', { 'font-size': size, 'font-weight': 600, fill: '#fff', 'text-anchor': 'middle', 'dominant-baseline': 'central' }, null);
    t.textContent = text;
    g.appendChild(t);
    const w = t.getComputedTextLength() + 10 * scale, h = size + 7 * scale, gap = 6 * scale;
    let x = c.x, y = c.y + r + gap + h / 2;
    if (place === 'above') y = c.y - r - gap - h / 2;
    if (place === 'right') { x = c.x + r + gap + w / 2; y = c.y; }
    if (place === 'left') { x = c.x - r - gap - w / 2; y = c.y; }
    const box = el('rect', { x: x - w / 2, y: y - h / 2, width: w, height: h, rx: 3 * scale, fill: LABEL_FILL,
                             stroke: under ? BRIGHT : COLOR, 'stroke-width': scale }, null);
    g.insertBefore(box, t);
    t.setAttribute('x', x); t.setAttribute('y', y);
  }
  function drawButtons() {
    svg.replaceChildren();
    if (!M || !active || drag || !shown) return;
    const root = el('g', { transform: `translate(${OX},${OY})` }, svg);
    const r = radius(), scale = r / 14, cs = centers();
    for (const k in cs) {
      const c = cs[k], def = BUTTONS[k], on = lit(k), under = hover === k;
      const filled = under || on;
      const g = el('g', { transform: `translate(${c.x.toFixed(1)},${c.y.toFixed(1)})` }, root);
      el('circle', { r, fill: under ? BRIGHT : on ? FULL : IDLE,
                     stroke: under && on ? 'rgba(255,255,255,0.9)' : filled ? BRIGHT : COLOR,
                     'stroke-width': (under && on ? 2.5 : 1.5) * scale }, g);
      icon(g, def, on, filled, r * GRAPHIC);
      if (def.menu) {
        const a = Math.SQRT1_2 * r;
        el('circle', { cx: a, cy: -a, r: Math.max(BADGE * r, 3 * scale), fill: BRIGHT, stroke: DARK, 'stroke-width': scale }, g);
      }
    }
    // the name of the one under the mouse; an open menu's own button has none (ringed all round)
    if (hover && cs[hover] && !(hover === 'main' && menuOpen)) {
      const place = { color: 'above', lights: 'right', door: 'below', wheels: 'left' }[hover] || 'below';
      label(el('g', {}, root), BUTTONS[hover].name, cs[hover], place, true);
    }
  }

  // ----- hover, as Kneady does it: the truck, its button, its menu -----
  let active = false, shown = true, hover = null, menuOpen = false, hideTimer = 0, drag = null;
  function toCanvas(e) {                            // a pointer, in the render's coordinates
    const b = canvas.getBoundingClientRect();
    return { x: (e.clientX - b.left) / b.width * canvas.width - OX, y: (e.clientY - b.top) / b.height * canvas.height - OY };
  }
  function onTruck(p) {
    const q = fromScreen(p);
    const x = Math.round(q.x) - work.x, y = Math.round(q.y) - work.y;
    return x >= 0 && y >= 0 && x < work.w && y < work.h && mask[y * work.w + x] > 0.5;
  }
  function hit(p) {
    const cs = centers(), r = radius();
    for (const k of [...(menuOpen ? RING : []), 'main']) {
      const c = cs[k];
      if (c && Math.hypot(p.x - c.x, p.y - c.y) <= r + 2 * unit) return k;
    }
    // an open menu holds the hover in the disc its ring fills
    if (menuOpen && Math.hypot(p.x - cs.main.x, p.y - cs.main.y) <= r * SPACING + r + 6 * unit) return 'truck';
    return onTruck(p) ? 'truck' : null;
  }
  function setHint(text) { if (hint && hint.textContent !== text) hint.textContent = text; }
  function hintFor() {
    if (!active) return 'Hover over the truck';
    if (menuOpen) return 'Drag Color, Door or Wheels sideways. Click Lights or Door.';
    return 'Drag up or down to squash, sideways to lean. Click the button for more.';
  }
  function setActive(on) {
    clearTimeout(hideTimer);
    if (on === active) return;
    active = on;
    if (!on) { menuOpen = false; hover = null; }
    stage.classList.toggle('is-active', on);
    setHint(hintFor());
    redraw();
  }
  function setMenu(on) { menuOpen = on; setHint(hintFor()); redraw(); }

  // ----- dragging: one direction per drag, decided after 6 pixels, as Kneady does -----
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  stage.addEventListener('pointermove', e => {
    if (!M) return;
    const p = toCanvas(e);
    if (drag) {
      const dx = (p.x - drag.p.x) / unit, dy = (p.y - drag.p.y) / unit;  // CSS pixels
      if (!drag.axis && Math.hypot(dx, dy) > 6) {
        drag.axis = BUTTONS[drag.k] && !BUTTONS[drag.k].up ? 'x' : Math.abs(dx) > Math.abs(dy) ? 'x' : 'y';
        if (drag.k === 'lights') drag.axis = null;
        else redraw();                              // the buttons and the highlight hide while hauling
      }
      if (!drag.axis) return;
      const k = drag.k, s = drag.s;
      if (k === 'main' || k === 'truck') {
        if (drag.axis === 'y') S.sy = clamp(s.sy * Math.exp(-dy / 180), SY_MIN, SY_MAX);
        else S.lean = clamp(s.lean + dx / 420, -LEAN_MAX, LEAN_MAX);
        redraw();
      } else {
        if (k === 'color') S.hue = s.hue + dx / 400;
        if (k === 'door') S.door = clamp(s.door + dx / 220, 0, 1);
        if (k === 'wheels') S.steer = clamp(s.steer + dx / 160, -1, 1);
        recompose();
      }
      stage.dataset.axis = drag.axis;
      return;
    }
    if (e.pointerType === 'mouse') {
      const h = hit(p);
      setActive(h !== null);
      const b = h && h !== 'truck' ? h : null;
      if (b !== hover) { hover = b; redraw(); }
      stage.classList.toggle('on-button', !!b);
    }
  });
  stage.addEventListener('pointerleave', () => { if (!drag) hideTimer = setTimeout(() => setActive(false), 150); });
  stage.addEventListener('pointerdown', e => {
    if (!M) return;
    const p = toCanvas(e), h = hit(p);
    if (!h) { if (menuOpen) setMenu(false); if (e.pointerType !== 'mouse') setActive(false); return; }
    if (!active) setActive(true);
    hover = h === 'truck' ? null : h;
    drag = { k: h, p, axis: null, s: { ...S } };
    try { stage.setPointerCapture(e.pointerId); } catch (_) { /* a pointer the browser no longer has */ }
    stage.classList.add('is-dragging');
  });
  function endDrag(e) {
    if (!drag) return;
    const tap = !drag.axis && e && e.type === 'pointerup', k = drag.k;
    drag = null; stage.dataset.axis = '';
    stage.classList.remove('is-dragging');
    if (tap) {
      if (k === 'main') setMenu(!menuOpen);
      else if (k === 'lights') { S.lights = !S.lights; recompose(); }
      else if (k === 'door') animateDoor(S.door > 0.5 ? 0 : 1);
      else if (k === 'truck' && menuOpen) setMenu(false);
    }
    if (e && e.pointerType === 'mouse') {
      const h = hit(toCanvas(e));
      setActive(h !== null); hover = h && h !== 'truck' ? h : null;
    }
    redraw();
  }
  stage.addEventListener('pointerup', endDrag);
  stage.addEventListener('pointercancel', endDrag);

  // the door swings, clicked
  let doorAnim = 0;
  function animateDoor(to) {
    cancelAnimationFrame(doorAnim);
    if (still) { S.door = to; recompose(); return; }
    const from = S.door, t0 = performance.now(), dur = 520;
    const step = now => {
      const t = Math.min(1, (now - t0) / dur), k = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      S.door = from + (to - from) * k;
      compose(); draw();
      if (t < 1) doorAnim = requestAnimationFrame(step);
    };
    doorAnim = requestAnimationFrame(step);
  }

  // ----- the keyboard: arrows squash and lean; Enter opens the menu; 1 to 4 work its buttons -----
  stage.addEventListener('focus', () => setActive(true));
  stage.addEventListener('blur', () => setActive(false));
  stage.addEventListener('keydown', e => {
    const k = e.key; let used = true, again = false;
    if (k === 'ArrowUp') S.sy = clamp(S.sy * 1.08, SY_MIN, SY_MAX);
    else if (k === 'ArrowDown') S.sy = clamp(S.sy / 1.08, SY_MIN, SY_MAX);
    else if (k === 'ArrowRight') S.lean = clamp(S.lean + 0.05, -LEAN_MAX, LEAN_MAX);
    else if (k === 'ArrowLeft') S.lean = clamp(S.lean - 0.05, -LEAN_MAX, LEAN_MAX);
    else if (k === 'Enter' || k === ' ') setMenu(!menuOpen);
    else if (k === 'Escape') setMenu(false);
    else if (k === '1') { S.hue += 1 / 8; again = true; }
    else if (k === '2') { S.lights = !S.lights; again = true; }
    else if (k === '3') animateDoor(S.door > 0.5 ? 0 : 1);
    else if (k === '4') { S.steer = S.steer > 0.5 ? -1 : S.steer < -0.5 ? 0 : 1; again = true; }
    else used = false;
    if (used) { e.preventDefault(); if (again) recompose(); else redraw(); }
  });

  // ----- sizes follow the stage: the buttons stay Kneady's size on screen -----
  function resize() {
    const b = canvas.getBoundingClientRect();
    if (b.width) unit = canvas.width / b.width;
    outlineFor();
    redraw();
  }
  new ResizeObserver(resize).observe(canvas);

  // ----- start: the truck as it first shows, then the door's and the wheels' other frames -----
  fetch(ROOT + 'truck.json' + VERSION).then(r => r.json()).then(async m => {
    M = m; [W, H] = m.size;
    M.door = rect(m.door.rect); M.wheels = rect(m.wheels.rect); M.lights = rect(m.lights.rect);
    M.door.frames = m.door.frames; M.wheels.frames = m.wheels.frames;
    S.hue = m.paint[0]; S.sat = m.paint[1]; S.val = m.paint[2];
    OX = Math.round(W * PAD); OY = Math.round(H * PAD);
    canvas.width = W + 2 * OX; canvas.height = H + 2 * OY;
    svg.setAttribute('viewBox', `0 0 ${canvas.width} ${canvas.height}`);
    const tr = rect(m.truck.rect);
    work = union([{ x: tr.x - 4, y: tr.y - 4, w: tr.w + 8, h: tr.h + 8 }, M.door, M.wheels, M.lights]);
    work.x = Math.max(0, work.x); work.y = Math.max(0, work.y);
    work.w = Math.min(W - work.x, work.w); work.h = Math.min(H - work.y, work.h);
    composed = document.createElement('canvas'); composed.width = work.w; composed.height = work.h;
    tint = document.createElement('canvas'); tint.width = work.w; tint.height = work.h;
    cImg = new ImageData(work.w, work.h); tImg = new ImageData(work.w, work.h);
    for (let i = 0; i < work.w * work.h; i++) {
      tImg.data[4 * i] = REGION[0] * 255; tImg.data[4 * i + 1] = REGION[1] * 255; tImg.data[4 * i + 2] = REGION[2] * 255;
    }
    mask = new Float32Array(work.w * work.h);
    const [a, b, w4, li] = await Promise.all(['base_A', 'base_B', 'wheels_4', 'lights'].map(image));
    L.A = decode(a); L.B = decode(b); L.wheels[4] = decode(w4); L.lights = decode(li, true);
    resize(); compose(); draw();
    stage.classList.add('is-ready');
    setHint(hintFor());
    // the rest, in the background
    for (let k = 1; k <= 8; k++) {
      Promise.all([image('door_A_' + k), image('door_B_' + k)]).then(([da, db]) => { L.doorA[k - 1] = decode(da); L.doorB[k - 1] = decode(db); });
    }
    for (let k = 0; k <= 8; k++) if (k !== 4) image('wheels_' + k).then(img => { L.wheels[k] = decode(img); });
  }).catch(() => { /* the poster stays */ });

  // for tests: set the state, hover a button, open the menu
  window.SS_TRUCK = { S, set: o => { Object.assign(S, o); compose(); draw(); }, hover: k => { active = true; hover = k; draw(); },
                      menu: on => { active = true; setMenu(on); }, ready: () => !!(M && L.A),
                      state: () => ({ ...S, menuOpen, active, hover, unit, center: M && M.truck.center, ring: radius() * SPACING,
                                      ox: OX, oy: OY, cw: canvas.width, ch: canvas.height }),
                      time: () => { const t = performance.now(); compose(); return performance.now() - t; } };
})();
