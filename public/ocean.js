// The ocean behind the game. A pink fish dives deeper with every scored answer,
// and the camera follows it down through five bands of life:
//   Shallows (0 m)       light rays and swaying kelp
//   Schooler (600 m)     coral fans and schools of little fish
//   Thermocline (1350 m) pulsing jellyfish
//   Deep Cut (2250 m)    anglerfish with glowing lures
//   Trench (3300 m)      tube worms and glowing specks
// Everything is drawn in code on one canvas; with reduced motion the scene holds
// still and jumps to the new depth.
//
// The game talks to it through window.Ocean:
//   Ocean.goTo(metres)          dive (or rise) to a depth
//   Ocean.celebrate(points, m)  react to a scored answer
//   Ocean.miss()                react to a wrong answer
//   Ocean.layout()              the page layout changed
(() => {
  const BANDS = [[0, 'Shallows'], [600, 'Schooler'], [1350, 'Thermocline'], [2250, 'Deep Cut'], [3300, 'Trench']];
  const PX_PER_M = 1.1;          // how far the world scrolls per metre of depth
  const MAX_M = 5600;
  const FISH_Y = 0.42;           // the fish sits this far down the screen
  const TAU = Math.PI * 2;

  const cv = document.getElementById('ocean');
  const cx = cv.getContext('2d');
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;

  let W = 0, H = 0, dpr = 1, contentW = 560;
  let cam = 0, camVel = 0;       // camera depth (m) and its speed (m/s)
  let dive = null;               // {from, to, start, dur}
  let time = 0, last = performance.now();
  let wobble = 0;                // seconds of "no!" head-shake left
  const bubbles = [], sparkles = [], popups = [], snow = [];

  // Seeded random numbers, so the world looks the same every visit
  function rng(seed) {
    return () => {
      seed = seed + 0x6D2B79F5 | 0;
      let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  const bandAt = m => BANDS.reduce((b, [d], i) => (m >= d ? i : b), 0);
  const ease = k => (k < .5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2);

  // ---------- The world, generated once ----------
  const world = (() => {
    const r = rng(11);
    const plants = [], schools = [], jellies = [], anglers = [];
    for (let m = 30; m < MAX_M; m += 60 + r() * 80) {
      plants.push({m, side: r() < .5 ? 0 : 1, off: 8 + r() * 80, band: bandAt(m), n: 2 + (r() * 4 | 0),
        h: 46 + r() * 70, ph: r() * TAU, hue: r()});
    }
    const fishHues = [190, 45, 330, 160, 20, 270];
    for (let m = 90; m < 3400; m += 170 + r() * 220) {
      schools.push({m, n: 5 + (r() * 7 | 0), dir: r() < .5 ? -1 : 1, speed: 22 + r() * 26, x0: r() * 3000,
        hue: fishHues[r() * fishHues.length | 0], size: 4.5 + r() * 3, ph: r() * TAU, seed: r() * 1e9 | 0});
    }
    for (let m = 1250; m < MAX_M; m += 210 + r() * 230) {
      jellies.push({m, x: r(), ph: r() * TAU, hue: [290, 200, 330, 180][r() * 4 | 0], s: 13 + r() * 12});
    }
    for (let m = 2250; m < MAX_M; m += 420 + r() * 380) {
      anglers.push({m, x0: r() * 3000, dir: r() < .5 ? -1 : 1, speed: 9 + r() * 9, s: 16 + r() * 8});
    }
    return {plants, schools, jellies, anglers};
  })();

  // ---------- Sizing ----------
  function size() {
    dpr = Math.min(devicePixelRatio || 1, 2);
    W = innerWidth; H = innerHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    cx.setTransform(dpr, 0, 0, dpr, 0, 0);
    snow.length = 0;
    for (let i = 0; i < 70; i++) snow.push({x: Math.random() * W, y: Math.random() * H, r: Math.random() * 1.5 + .4, v: Math.random() * 12 + 4, a: Math.random() * .3 + .08});
    layout();
  }
  function layout() {
    const app = document.querySelector('.app');
    if (app) contentW = app.getBoundingClientRect().width;
  }
  // The fish swims in the left margin when there is room, else near the edge
  function fishPos() {
    const gutter = (W - contentW) / 2;
    const x = gutter > 130 ? gutter * .5 : Math.max(40, W * .1);
    return {x, y: H * FISH_Y};
  }
  const yOf = m => (m - cam) * PX_PER_M + H * FISH_Y;

  // ---------- Drawing helpers ----------
  function wavyLine(x, y, h, sway, width, color) {
    cx.strokeStyle = color; cx.lineWidth = width; cx.lineCap = 'round';
    cx.beginPath(); cx.moveTo(x, y);
    cx.quadraticCurveTo(x + sway * .6, y - h * .55, x + sway, y - h);
    cx.stroke();
  }
  function glow(x, y, r, color, a) {
    const g = cx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, color.replace('A', a)); g.addColorStop(1, color.replace('A', 0));
    cx.fillStyle = g; cx.beginPath(); cx.arc(x, y, r, 0, TAU); cx.fill();
  }
  function star(x, y, r, rot) {
    cx.beginPath();
    for (let i = 0; i < 8; i++) {
      const rr = i % 2 ? r * .38 : r, a = rot + i * Math.PI / 4;
      cx[i ? 'lineTo' : 'moveTo'](x + Math.cos(a) * rr, y + Math.sin(a) * rr);
    }
    cx.closePath(); cx.fill();
  }

  // ---------- Layers ----------
  function lightRays() {
    if (cam > 900) return;
    const a = (1 - cam / 900) * .09;
    for (let i = 0; i < 6; i++) {
      const x = (i + .5) / 6 * W + Math.sin(time * .15 + i) * 40;
      const g = cx.createLinearGradient(0, 0, 0, H);
      g.addColorStop(0, `rgba(220,255,250,${a})`); g.addColorStop(1, 'rgba(220,255,250,0)');
      cx.fillStyle = g;
      cx.beginPath(); cx.moveTo(x - 30, -10); cx.lineTo(x + 30, -10); cx.lineTo(x + 140, H); cx.lineTo(x + 20, H); cx.closePath(); cx.fill();
    }
    // The surface shimmer above the starting depth
    const sy = yOf(-300);
    if (sy > -20) {
      cx.strokeStyle = 'rgba(230,255,252,.35)'; cx.lineWidth = 2; cx.beginPath();
      for (let x = 0; x <= W; x += 12) cx[x ? 'lineTo' : 'moveTo'](x, sy + Math.sin(x / 40 + time * 1.5) * 4);
      cx.stroke();
    }
  }

  function plants() {
    for (const p of world.plants) {
      const y = yOf(p.m);
      if (y < -160 || y > H + 40) continue;
      const x = p.side ? W - p.off : p.off;
      const sw = Math.sin(time * .9 + p.ph);
      if (p.band === 0) {                       // kelp with leaves
        for (let i = 0; i < p.n; i++) {
          const bx = x + (i - p.n / 2) * 7, h = p.h * (.7 + i * .12), s = sw * 14 + i * 3;
          const c = `hsl(${120 + p.hue * 40} 45% ${30 + i * 4}%)`;
          wavyLine(bx, y, h, s, 4, c);
          cx.fillStyle = c;
          for (let k = 1; k < 4; k++) {
            const ly = y - h * k / 4, lx = bx + s * k / 4;
            cx.beginPath(); cx.ellipse(lx + 5, ly, 7, 2.6, -.5 + sw * .2, 0, TAU); cx.fill();
          }
        }
      } else if (p.band === 1) {                // branching coral and sea grass
        const c = `hsl(${p.hue < .5 ? 12 + p.hue * 30 : 330 + p.hue * 20} 70% 62%)`;
        for (let i = 0; i < p.n; i++) {
          const bx = x + (i - p.n / 2) * 10, h = p.h * .6;
          wavyLine(bx, y, h, sw * 3 + (i - 1) * 6, 3.5, c);
          wavyLine(bx + (i - 1) * 3, y - h * .5, h * .4, sw * 2 - 8, 2.5, c);
          cx.fillStyle = c; cx.beginPath(); cx.arc(bx + sw * 3 + (i - 1) * 6, y - h, 3, 0, TAU); cx.fill();
        }
        wavyLine(x + 14, y, p.h * .5, sw * 10, 2, 'hsl(150 40% 38%)');
      } else if (p.band === 2) {                // anemones
        const c = `hsl(${280 + p.hue * 60} 60% 62%)`;
        cx.fillStyle = `hsl(${280 + p.hue * 60} 40% 32%)`;
        cx.beginPath(); cx.ellipse(x, y, 14, 7, 0, 0, TAU); cx.fill();
        for (let i = 0; i < 9; i++) {
          const a = -Math.PI * (.15 + .7 * i / 8);
          const tx = x + Math.cos(a) * 26, ty = y - 4 + Math.sin(a) * 26 - 6;
          cx.strokeStyle = c; cx.lineWidth = 3; cx.lineCap = 'round';
          cx.beginPath(); cx.moveTo(x + Math.cos(a) * 6, y - 4);
          cx.quadraticCurveTo(tx + Math.sin(time * 2 + i + p.ph) * 6, ty + 8, tx + Math.sin(time * 2.2 + i + p.ph) * 8, ty);
          cx.stroke();
        }
      } else if (p.band === 3) {                // dark kelp with glowing tips
        for (let i = 0; i < p.n; i++) {
          const bx = x + (i - p.n / 2) * 8, h = p.h * .9, s = sw * 10;
          wavyLine(bx, y, h, s, 3, 'hsl(200 35% 20%)');
          glow(bx + s, y - h, 9, 'rgba(95,227,210,A)', .55 + Math.sin(time * 2 + i + p.ph) * .3);
        }
      } else {                                  // tube worms by a warm vent
        glow(x, y - 10, 46, 'rgba(255,140,90,A)', .12);
        for (let i = 0; i < p.n + 1; i++) {
          const bx = x + (i - p.n / 2) * 9, h = p.h * (.4 + (i % 3) * .15);
          cx.fillStyle = 'hsl(40 25% 82%)'; cx.fillRect(bx - 2.5, y - h, 5, h);
          cx.fillStyle = 'hsl(352 80% 58%)';
          cx.beginPath(); cx.ellipse(bx + sw * 2, y - h - 4, 5, 6 + Math.sin(time * 3 + i) * 1.5, 0, 0, TAU); cx.fill();
        }
      }
    }
  }

  function smallFish(x, y, s, dir, hue, wag) {
    cx.save(); cx.translate(x, y); cx.scale(dir, 1);
    cx.fillStyle = `hsl(${hue} 70% 62%)`;
    cx.beginPath(); cx.ellipse(0, 0, s * 1.6, s, 0, 0, TAU); cx.fill();
    cx.beginPath(); cx.moveTo(-s * 1.4, 0); cx.lineTo(-s * 2.6, -s * (.8 + wag)); cx.lineTo(-s * 2.6, s * (.8 - wag)); cx.closePath(); cx.fill();
    cx.fillStyle = '#fff'; cx.beginPath(); cx.arc(s * .8, -s * .2, s * .32, 0, TAU); cx.fill();
    cx.restore();
  }

  function schools() {
    for (const s of world.schools) {
      const y0 = yOf(s.m);
      if (y0 < -80 || y0 > H + 80) continue;
      const span = W + 400;
      const xh = (((s.x0 + time * s.speed * s.dir) % span) + span) % span - 200;
      const r = rng(s.seed);
      for (let i = 0; i < s.n; i++) {
        const dx = -i * 16 * s.dir + (r() - .5) * 14, dy = (r() - .5) * 46 + Math.sin(time * 1.4 + i + s.ph) * 4;
        smallFish(xh + dx, y0 + dy, s.size, s.dir, s.hue, Math.sin(time * 9 + i) * .3);
      }
    }
  }

  function jellies() {
    for (const j of world.jellies) {
      const y = yOf(j.m) + Math.sin(time * .6 + j.ph) * 14;
      if (y < -90 || y > H + 90) continue;
      const x = j.x * W + Math.sin(time * .2 + j.ph) * 30;
      const pulse = 1 + Math.sin(time * 2.4 + j.ph) * .12;
      glow(x, y, j.s * 2.6, `hsla(${j.hue},90%,70%,A)`, .18);
      cx.strokeStyle = `hsla(${j.hue},80%,78%,.55)`; cx.lineWidth = 1.5;
      for (let i = 0; i < 5; i++) {
        const tx = x + (i - 2) * j.s * .3;
        cx.beginPath(); cx.moveTo(tx, y);
        for (let k = 1; k <= 4; k++) cx.lineTo(tx + Math.sin(time * 2 + k + i) * 4, y + k * j.s * .55);
        cx.stroke();
      }
      cx.fillStyle = `hsla(${j.hue},80%,75%,.75)`;
      cx.beginPath(); cx.ellipse(x, y, j.s * pulse, j.s * .8 / pulse, 0, Math.PI, TAU); cx.closePath(); cx.fill();
      cx.fillStyle = 'rgba(255,255,255,.35)';
      cx.beginPath(); cx.ellipse(x - j.s * .3, y - j.s * .4, j.s * .25, j.s * .12, -.4, 0, TAU); cx.fill();
    }
  }

  function anglers() {
    for (const a of world.anglers) {
      const y = yOf(a.m);
      if (y < -90 || y > H + 90) continue;
      const span = W + 400;
      const x = (((a.x0 + time * a.speed * a.dir) % span) + span) % span - 200;
      cx.save(); cx.translate(x, y); cx.scale(a.dir, 1);
      const s = a.s;
      // the lure, then the fish
      const lx = s * 1.7, ly = -s * 1.5 + Math.sin(time * 2) * 3;
      cx.strokeStyle = 'hsl(220 20% 30%)'; cx.lineWidth = 2;
      cx.beginPath(); cx.moveTo(s * .3, -s * .7); cx.quadraticCurveTo(s * 1.2, -s * 2, lx, ly); cx.stroke();
      glow(lx, ly, 22, 'rgba(255,240,150,A)', .7 + Math.sin(time * 3) * .2);
      cx.fillStyle = '#fff6b0'; cx.beginPath(); cx.arc(lx, ly, 3, 0, TAU); cx.fill();
      cx.fillStyle = 'hsl(225 25% 18%)';
      cx.beginPath(); cx.ellipse(0, 0, s * 1.4, s, 0, 0, TAU); cx.fill();
      cx.beginPath(); cx.moveTo(-s * 1.2, 0); cx.lineTo(-s * 2.2, -s * .8); cx.lineTo(-s * 2.2, s * .8); cx.closePath(); cx.fill();
      cx.fillStyle = '#e8f0ff';
      for (let i = 0; i < 5; i++) {   // little teeth
        cx.beginPath(); cx.moveTo(s * .55 + i * s * .17, s * .15); cx.lineTo(s * .63 + i * s * .17, s * .45); cx.lineTo(s * .71 + i * s * .17, s * .15); cx.fill();
      }
      cx.fillStyle = '#fff'; cx.beginPath(); cx.arc(s * .7, -s * .35, s * .22, 0, TAU); cx.fill();
      cx.fillStyle = '#111'; cx.beginPath(); cx.arc(s * .75, -s * .35, s * .11, 0, TAU); cx.fill();
      cx.restore();
    }
  }

  function bandMarkers() {
    cx.font = '500 11px "JetBrains Mono", ui-monospace, monospace';
    cx.textAlign = 'right';
    for (const [d, name] of BANDS.slice(1)) {
      const y = yOf(d);
      if (y < -20 || y > H + 20) continue;
      cx.fillStyle = 'rgba(200,240,235,.32)';
      cx.fillText(`— ${name.toUpperCase()} · ${d.toLocaleString('en-US')} m —`, W - 24, y);
    }
    cx.textAlign = 'left';
  }

  function marineSnow(dt) {
    // Specks drift up gently, and stream past when the camera dives
    for (const p of snow) {
      p.y -= (p.v + camVel * PX_PER_M) * dt;
      p.x += Math.sin(p.y / 60) * .15;
      if (p.y < -4) { p.y = H + 4; p.x = Math.random() * W; }
      if (p.y > H + 4) { p.y = -4; p.x = Math.random() * W; }
      const deep = Math.min(1, cam / 3300);
      cx.fillStyle = deep > .6 && p.r > 1.4 ? `rgba(95,227,210,${p.a + .25})` : `rgba(210,245,240,${p.a})`;
      cx.beginPath(); cx.arc(p.x, p.y, p.r, 0, TAU); cx.fill();
    }
  }

  function bubbleLayer(dt) {
    if (!still && Math.random() < dt * 1.6) addBubble(Math.random() * W, H + 10, 2 + Math.random() * 4);
    for (let i = bubbles.length - 1; i >= 0; i--) {
      const b = bubbles[i];
      b.y -= (b.vy + camVel * PX_PER_M * .6) * dt;
      b.x += Math.sin(time * 3 + b.ph) * .4;
      if (b.y < -20) { bubbles.splice(i, 1); continue; }
      cx.strokeStyle = 'rgba(220,255,250,.55)'; cx.lineWidth = 1.2;
      cx.beginPath(); cx.arc(b.x, b.y, b.r, 0, TAU); cx.stroke();
      cx.fillStyle = 'rgba(255,255,255,.5)';
      cx.beginPath(); cx.arc(b.x - b.r * .35, b.y - b.r * .35, b.r * .25, 0, TAU); cx.fill();
    }
  }
  function addBubble(x, y, r) {
    if (bubbles.length < 160) bubbles.push({x, y, r, vy: 30 + r * 9 + Math.random() * 20, ph: Math.random() * TAU});
  }

  // ---------- The fish ----------
  function fish(dt) {
    const {x, y: y0} = fishPos();
    const y = y0 + Math.sin(time * 1.6) * 5;
    const diving = Math.abs(camVel) > 30;
    if (diving && Math.random() < dt * 22) addBubble(x - 10 + Math.random() * 6, y - 8, 1.5 + Math.random() * 3.5);
    let tilt = Math.max(-.7, Math.min(.7, camVel / 380));
    if (wobble > 0) { tilt += Math.sin(time * 34) * .3 * wobble; wobble = Math.max(0, wobble - dt * 1.4); }
    const wag = Math.sin(time * (diving ? 16 : 6)) * (diving ? .45 : .25);
    // A soft light around the fish keeps it visible in the dark
    glow(x, y, 70, 'rgba(255,170,190,A)', .08 + Math.min(.14, cam / 25000));
    cx.save(); cx.translate(x, y); cx.rotate(tilt);
    // tail
    cx.fillStyle = '#ff6f8f';
    cx.save(); cx.translate(-22, 0); cx.rotate(wag);
    cx.beginPath(); cx.moveTo(0, 0); cx.quadraticCurveTo(-14, -18, -20, -14); cx.quadraticCurveTo(-12, 0, -20, 14); cx.quadraticCurveTo(-14, 18, 0, 0); cx.fill();
    cx.restore();
    // dorsal fin
    cx.beginPath(); cx.moveTo(-8, -15); cx.quadraticCurveTo(2, -30, 10, -15); cx.fill();
    // body
    const g = cx.createLinearGradient(0, -18, 0, 18);
    g.addColorStop(0, '#ff9fb3'); g.addColorStop(1, '#ff6f8f');
    cx.fillStyle = g; cx.beginPath(); cx.ellipse(0, 0, 27, 19, 0, 0, TAU); cx.fill();
    cx.fillStyle = 'rgba(255,240,244,.55)'; cx.beginPath(); cx.ellipse(2, 7, 17, 8, 0, 0, TAU); cx.fill();
    // side fin, flapping
    cx.fillStyle = '#ff7f9c';
    cx.save(); cx.translate(-2, 4); cx.rotate(.5 + Math.sin(time * 7) * .35);
    cx.beginPath(); cx.ellipse(-6, 0, 8, 4, 0, 0, TAU); cx.fill(); cx.restore();
    // eye, cheek, smile
    cx.fillStyle = '#fff'; cx.beginPath(); cx.arc(13, -5, 7.5, 0, TAU); cx.fill();
    cx.fillStyle = '#1d2433'; cx.beginPath(); cx.arc(14.5, -4.5, 4.2, 0, TAU); cx.fill();
    cx.fillStyle = '#fff'; cx.beginPath(); cx.arc(16, -6.2, 1.5, 0, TAU); cx.fill();
    cx.fillStyle = 'rgba(255,120,150,.6)'; cx.beginPath(); cx.ellipse(12, 6, 4.5, 2.6, 0, 0, TAU); cx.fill();
    cx.strokeStyle = '#7a2a3d'; cx.lineWidth = 1.6; cx.lineCap = 'round';
    cx.beginPath(); cx.arc(21, 3, 3.2, .2, Math.PI * .8); cx.stroke();
    cx.restore();
  }

  // ---------- Celebrations ----------
  // Motion uses the capped step (dt); lifetimes count real time (age), so
  // popups and sparkles fade on schedule even when the browser drops frames.
  function effects(dt, age) {
    for (let i = sparkles.length - 1; i >= 0; i--) {
      const s = sparkles[i];
      s.life -= age; if (s.life <= 0) { sparkles.splice(i, 1); continue; }
      s.vy += 40 * dt; s.x += s.vx * dt; s.y += s.vy * dt; s.rot += dt * 4;
      cx.globalAlpha = Math.min(1, s.life / s.max * 1.6);
      if (s.kind === 'diamond') {
        cx.fillStyle = s.color;
        cx.beginPath(); cx.moveTo(s.x, s.y - s.r); cx.lineTo(s.x + s.r * .7, s.y); cx.lineTo(s.x, s.y + s.r); cx.lineTo(s.x - s.r * .7, s.y); cx.closePath(); cx.fill();
        cx.fillStyle = 'rgba(255,255,255,.7)'; cx.beginPath(); cx.moveTo(s.x, s.y - s.r); cx.lineTo(s.x + s.r * .25, s.y - s.r * .1); cx.lineTo(s.x - s.r * .25, s.y - s.r * .1); cx.fill();
      } else {
        cx.fillStyle = s.color; star(s.x, s.y, s.r, s.rot);
      }
      cx.globalAlpha = 1;
    }
    cx.textAlign = 'center';
    for (let i = popups.length - 1; i >= 0; i--) {
      const p = popups[i];
      p.life -= age; if (p.life <= 0) { popups.splice(i, 1); continue; }
      p.y -= 26 * dt;
      cx.globalAlpha = Math.min(1, p.life / .6);
      cx.font = `800 ${p.size}px Unbounded, system-ui, sans-serif`;
      cx.fillStyle = p.color; cx.fillText(p.text, p.x, p.y);
      cx.globalAlpha = 1;
    }
    cx.textAlign = 'left';
  }
  function burst(n, kind, colors, speed) {
    const {x, y} = fishPos();
    for (let i = 0; i < n; i++) {
      const a = Math.random() * TAU, v = speed * (.4 + Math.random() * .8);
      sparkles.push({x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v - speed * .3, r: 3 + Math.random() * 4,
        rot: Math.random() * TAU, kind, color: colors[i % colors.length], life: 1.2 + Math.random() * .8, max: 2});
    }
  }

  // ---------- Loop ----------
  function frame(now) {
    const age = Math.max(0, (now - last) / 1000), dt = Math.min(.05, age); last = now; time += dt;
    const prev = cam;
    if (dive) {
      const k = Math.min(1, (now - dive.start) / dive.dur);
      cam = dive.from + (dive.to - dive.from) * ease(k);
      if (k >= 1) dive = null;
    }
    camVel = dt > 0 ? (cam - prev) / dt : 0;
    cx.clearRect(0, 0, W, H);
    lightRays(); plants(); jellies(); anglers(); schools(); bandMarkers();
    marineSnow(dt); bubbleLayer(dt); fish(dt); effects(dt, age);
    if (!still) requestAnimationFrame(frame);
  }
  const redraw = () => { if (still) { last = performance.now(); frame(last); } };

  window.Ocean = {
    goTo(m) {
      m = Math.max(0, Math.min(MAX_M, m));
      if (still) { cam = m; dive = null; redraw(); return; }
      const dist = Math.abs(m - cam);
      if (dist < 1) return;
      // Deeper dives take longer; going back to the surface is quick
      const dur = m < cam ? 1300 : Math.min(3200, 900 + dist * 2.4);
      dive = {from: cam, to: m, start: performance.now(), dur};
    },
    celebrate(points, metres) {
      const {x, y} = fishPos();
      popups.push({text: `+${metres} m`, x, y: y - 34, life: 1.8, size: 15, color: '#e9f7f6'});
      if (still) { redraw(); return; }
      for (let i = 0; i < 6 + points / 10; i++) addBubble(x + (Math.random() - .5) * 30, y, 2 + Math.random() * 5);
      if (points >= 60) burst(points >= 85 ? 26 : 14, 'star', ['#5fe3d2', '#c8b8ff', '#fff6b0'], 120);
      if (points >= 100) {
        burst(30, 'diamond', ['#ff8a9e', '#8fd0ff', '#5fe3d2'], 170);
        popups.push({text: '💎 One in a Krillion', x, y: y + 52, life: 2.4, size: 13, color: '#ff8a9e'});
      }
    },
    miss() {
      wobble = .7;
      const {x, y} = fishPos();
      popups.push({text: 'blub', x: x + 26, y: y - 26, life: 1.1, size: 12, color: 'rgba(233,247,246,.8)'});
      if (!still) for (let i = 0; i < 4; i++) addBubble(x + 24, y - 6, 2 + Math.random() * 3);
      redraw();
    },
    layout() { layout(); redraw(); },
  };

  addEventListener('resize', () => { size(); redraw(); });
  size();
  if (still) redraw(); else requestAnimationFrame(t => { last = t; frame(t); });
})();
