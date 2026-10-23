// Krillion voice dive. Prompts and answer judging come from the API; the
// catalogs never ship to the browser.

// ---------- Scoring ----------
const TIERS = [
  {name: 'Plankton', pts: 10, emoji: '🦐', c: 'var(--t0)'},
  {name: 'Too Clever', pts: 15, emoji: '🤓', c: 'var(--t1)'},
  {name: 'Schooler', pts: 30, emoji: '🐟', c: 'var(--t2)'},
  {name: 'Rare', pts: 60, emoji: '🐙', c: 'var(--t3)'},
  {name: 'Deep Cut', pts: 85, emoji: '🦑', c: 'var(--t4)'},
  {name: 'One in a Krillion', pts: 100, emoji: '💎', c: 'var(--t5)'}];
// Popular mode: same answer tiers, payouts reversed
const TIERS_POP = [
  {name: 'Top Answer', pts: 100, emoji: '💎', c: 'var(--t5)'},
  {name: 'Crowd Favorite', pts: 85, emoji: '🦑', c: 'var(--t4)'},
  {name: 'Common', pts: 60, emoji: '🐙', c: 'var(--t3)'},
  {name: 'Uncommon', pts: 30, emoji: '🐟', c: 'var(--t2)'},
  {name: 'Long Shot', pts: 15, emoji: '🤓', c: 'var(--t1)'},
  {name: 'Lone Wolf', pts: 10, emoji: '🦐', c: 'var(--t0)'}];
const MODES = {
  rare: {label: 'Rare wins', tiers: TIERS, best: 5, head: 'The obvious answer <em>sinks.</em>',
    lede: 'Each prompt is read aloud. Say the rarest true answer you can think of. Every point takes you four metres deeper.',
    reveal: 'Krillion answer'},
  popular: {label: 'Popular wins', tiers: TIERS_POP, best: 0, head: 'Swim with the <em>school.</em>',
    lede: 'Each prompt is read aloud. Say the answer most people would say first. The crowd’s favorite pays 100; the oddball pays 10.',
    reveal: 'Top answer'}};
let scoring = 'rare';
try { if (localStorage.getItem('kv-mode') === 'popular') scoring = 'popular'; } catch (e) {}
let TS = MODES[scoring].tiers;
const BANDS = [[0, 'Shallows'], [600, 'Schooler'], [1350, 'Thermocline'], [2250, 'Deep Cut'], [3300, 'Trench']];
const SPEED_MAX = .5; // up to +50% of tier points for an instant answer
const ROUND_MS = 25000, PENALTY_MS = 3000;

// ---------- Helpers ----------
const STOP = new Set('um uh er erm hmm uhm oh like maybe i think say guess how about what the a an is it its lets let me go with ok okay so well and of im ill my answer'.split(' '));
const norm = s => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[’'`]/g, '').replace(/[^a-z0-9]+/g, ' ').trim();
const words = s => norm(s).split(' ').filter(w => w && !STOP.has(w));
const $ = id => document.getElementById(id);
const store = {
  get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }};
const todayKey = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const bandFor = m => BANDS.reduce((b, [t, n]) => m >= t ? n : b, 'Shallows');
const fmt = n => n.toLocaleString('en-US');
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

// Categories played recently, most recent first, so practice dives stay fresh
const RECENT_KEY = 'kv-recent', RECENT_MAX = 60;
const recentSlugs = () => store.get(RECENT_KEY) || [];
function rememberPlayed(slugs) { store.set(RECENT_KEY, [...new Set([...slugs, ...recentSlugs()])].slice(0, RECENT_MAX)); }

// "Krillion answer: X · +4 more" opens the full list on click
function revealHTML(label, list) {
  if (!list || !list.length) return '';
  if (list.length === 1) return `${label}: <b>${esc(list[0])}</b>`;
  return `<button type="button" class="reveal" aria-expanded="false">${label}: <b>${esc(list[0])}</b> <span class="more">· +${list.length - 1} more</span></button>`
    + `<span class="revealList" hidden>${list.map(esc).join(' · ')}</span>`;
}
document.addEventListener('click', e => {
  const b = e.target.closest('.reveal'); if (!b) return;
  const open = b.getAttribute('aria-expanded') !== 'true';
  b.setAttribute('aria-expanded', open); b.nextElementSibling.hidden = !open;
});

async function api(path, body) {
  const r = await fetch(path, body ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : undefined);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

// The sea darkens with depth
function setDepth(m) {
  const f = Math.min(1, m / 4200);
  document.documentElement.style.setProperty('--sea', `hsl(${194 + f * 26} ${62 - f * 22}% ${19 - f * 15.5}%)`);
  $('gauge').innerHTML = `${fmt(m)} m<small>${bandFor(m)}</small>`;
}

// ---------- Audio ----------
let actx = null;
function tone(f, d = .12, type = 'sine', g = .12, at = 0) {
  if (!actx) return;
  const t = actx.currentTime + at, o = actx.createOscillator(), v = actx.createGain();
  o.type = type; o.frequency.setValueAtTime(f, t);
  v.gain.setValueAtTime(0, t); v.gain.linearRampToValueAtTime(g, t + .01); v.gain.exponentialRampToValueAtTime(.0001, t + d);
  o.connect(v).connect(actx.destination); o.start(t); o.stop(t + d + .02);
}
const chime = ti => { const notes = [523, 659, 784, 988, 1175, 1568]; for (let i = 0; i <= ti; i++) tone(notes[i], .22, 'sine', .1, i * .08); };
const buzz = () => { tone(180, .18, 'triangle', .14); tone(140, .22, 'triangle', .1, .08); };

// ---------- Reading the question ----------
// The question is the only thing the game speaks. Each category has a clip
// recorded ahead of time (Gemini TTS); browser speech is the fallback.
const clips = new Map();
let playing = null;
function loadClip(url) {
  if (!url || !actx) return Promise.resolve(null);
  if (!clips.has(url)) {
    clips.set(url, fetch(url).then(r => r.ok ? r.arrayBuffer() : Promise.reject(new Error(url)))
      .then(b => actx.decodeAudioData(b)).catch(() => null));
  }
  return clips.get(url);
}
async function speakPrompt(p) {
  const buf = await loadClip(p.audio);
  if (!buf) return say(p.prompt + '.');
  return new Promise(res => {
    const src = actx.createBufferSource(); src.buffer = buf; src.connect(actx.destination);
    let done = false; const fin = () => { if (!done) { done = true; clearTimeout(t); playing = null; res(); } };
    src.onended = fin; const t = setTimeout(fin, buf.duration * 1000 + 1500);
    playing = src; src.start();
  });
}
function stopVoice() {
  if (playing) { try { playing.stop(); } catch (e) {} playing = null; }
  if ('speechSynthesis' in window) speechSynthesis.cancel();
}

// Browser speech, used only when a recorded clip is missing
let voice = null;
function pickVoice() {
  if (!('speechSynthesis' in window)) return;
  const vs = speechSynthesis.getVoices();
  voice = vs.find(v => /^en[-_]US/i.test(v.lang) && /Samantha|Google US|Aria|Jenny|Natural|Ava/i.test(v.name))
    || vs.find(v => /^en[-_]US/i.test(v.lang)) || vs.find(v => /^en/i.test(v.lang)) || null;
}
if ('speechSynthesis' in window) { pickVoice(); speechSynthesis.onvoiceschanged = pickVoice; }
function say(text) {
  return new Promise(res => {
    if (!('speechSynthesis' in window)) { res(); return; }
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text); if (voice) u.voice = voice; u.rate = 1.03;
    let done = false; const fin = () => { if (!done) { done = true; clearTimeout(t); res(); } };
    u.onend = fin; u.onerror = fin;
    const t = setTimeout(fin, 1800 + text.length * 85); // some browsers never fire onend
    speechSynthesis.speak(u);
  });
}

// ---------- Speech recognition ----------
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null, listening = false, wantListen = false, micBlocked = !SR, lastInterim = 0;
function setupRec() {
  if (!SR || rec) return;
  rec = new SR(); rec.lang = 'en-US'; rec.continuous = true; rec.interimResults = true; rec.maxAlternatives = 4;
  rec.onstart = () => { listening = true; orb(); };
  rec.onresult = e => {
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i];
      if (r.isFinal) { const alts = []; for (let j = 0; j < r.length; j++) alts.push(r[j].transcript); heard(alts, false); }
      else { lastInterim = Date.now(); if (state === 'play') $('heard').textContent = '“' + r[0].transcript.trim() + '…”'; }
    }
  };
  rec.onerror = e => {
    if (['not-allowed', 'service-not-allowed', 'audio-capture'].includes(e.error)) {
      micBlocked = true; wantListen = false; orb(); if (state === 'play') $('typeInput').focus();
    }
  };
  rec.onend = () => { listening = false; orb(); if (wantListen && !micBlocked) setTimeout(startRec, 120); };
}
function startRec() { if (!rec || micBlocked) return; wantListen = true; if (listening) return; try { rec.start(); } catch (e) {} }
function stopRec() { wantListen = false; if (rec && listening) { try { rec.abort(); } catch (e) {} } }

// ---------- Game ----------
let state = 'start', phase = 'idle', game = null, judging = false, token = 0;
const timer = {left: ROUND_MS, running: false, last: 0};

function orb() {
  const o = $('orb'); o.className = 'orb'; let s = '';
  if (state !== 'play') return;
  if (judging) { o.classList.add('checking'); s = 'Checking that answer…'; }
  else if (phase === 'speaking') { o.classList.add('speaking'); s = 'Reading the prompt…'; }
  else if (phase === 'answer' && micBlocked) { o.classList.add('blocked'); s = SR ? 'Mic is blocked here. Type, or use your keyboard’s dictation mic.' : 'This browser can’t listen. Type, or use your keyboard’s dictation mic.'; }
  else if (phase === 'answer' && listening) { o.classList.add('listening'); s = 'Listening. Say your answer.'; }
  else if (phase === 'answer') { s = 'Starting the mic…'; }
  if (s) $('status').textContent = s;
}

function show(id) { ['start', 'play', 'end'].forEach(s => $(s).hidden = s !== id); $('pips').hidden = id !== 'play'; }
function pips() {
  $('pips').innerHTML = game.prompts.map((_, i) => {
    const r = game.rounds[i]; const c = r ? (r.tier >= 0 ? TS[r.tier].c : 'var(--line)') : 'transparent';
    return `<span class="pip ${i === game.i ? 'now' : ''}" style="background:${c}"></span>`;
  }).join('');
}

async function startGame(mode) {
  state = 'play';
  if (!actx) { try { actx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) {} }
  if (actx && actx.state === 'suspended') actx.resume();
  if ('speechSynthesis' in window) { speechSynthesis.cancel(); pickVoice(); }
  setupRec();
  if (navigator.wakeLock) navigator.wakeLock.request('screen').catch(() => {});
  TS = MODES[scoring].tiers;
  let d;
  const recent = mode === 'daily' ? '' : `&recent=${encodeURIComponent(recentSlugs().join(','))}`;
  try { d = await api(`/api/dive?mode=${mode === 'daily' ? 'daily' : 'practice'}&date=${todayKey()}${recent}`); }
  catch (e) { state = 'start'; $('lede').textContent = 'Could not reach the game server. Is it running?'; return; }
  game = {mode, scoring, date: d.date, prompts: d.prompts, i: 0, rounds: [], score: 0};
  await loadClip(game.prompts[0] && game.prompts[0].audio);
  setDepth(0); show('play'); playRound();
}

async function playRound() {
  const my = ++token, p = game.prompts[game.i];
  p.revealing = api(`/api/reveal?slug=${encodeURIComponent(p.slug)}`).catch(() => null);
  phase = 'speaking'; judging = false;
  $('roundLabel').textContent = `Prompt ${game.i + 1} of ${game.prompts.length} · ${MODES[game.scoring].label}`;
  const pt = $('promptText'); pt.textContent = 'Listen closely…'; pt.classList.add('veiled');
  $('heard').textContent = ''; $('misses').innerHTML = ''; $('resultBox').hidden = true; $('typeInput').value = '';
  game.tried = new Set(); timer.left = ROUND_MS; timer.running = false; drawAir(); pips(); orb();
  stopRec();
  const next = game.prompts[game.i + 1]; if (next) loadClip(next.audio);
  await speakPrompt(p);
  if (my !== token) return;
  phase = 'answer'; orb(); startTimer(); startRec();
  if (micBlocked) $('typeInput').focus({preventScroll: true});
}

function startTimer() { timer.running = true; timer.last = performance.now(); requestAnimationFrame(tick); }
function tick(now) {
  if (!timer.running || state !== 'play') return;
  const dt = now - timer.last; timer.last = now;
  if (!judging) timer.left -= dt;
  if (timer.left <= 0) {
    timer.left = 0; drawAir();
    // Let a half-spoken answer finish before running out of air
    if (Date.now() - lastInterim > 1300 && !judging) { endRound(null, 'time'); return; }
  }
  drawAir(); requestAnimationFrame(tick);
}
function drawAir() {
  const f = Math.max(0, timer.left / ROUND_MS);
  $('fill').style.transform = `scaleX(${f})`; $('bar').classList.toggle('low', timer.left < 6000);
  $('airSec').textContent = (timer.left / 1000).toFixed(1) + ' s';
}

async function heard(alts, typed) {
  const raw = (alts[0] || '').trim();
  if (state !== 'play' || phase !== 'answer' || judging || !raw) return;
  $('heard').textContent = '“' + raw + '”';
  const n = norm(raw), wc = n.split(' ').length;
  if (!typed && wc <= 4) {
    if (/\b(skip|pass)\b/.test(n)) { endRound(null, 'skip'); return; }
    if (/\b(repeat|say again|say that again|read it again)\b/.test(n)) { repeat(); return; }
  }
  if (!words(raw).length) return;
  judging = true; orb();
  const my = token, p = game.prompts[game.i];
  let r = null;
  try { r = await api('/api/judge', {slug: p.slug, alts}); } catch (e) {}
  judging = false;
  if (my !== token || state !== 'play') return;
  if (r && r.hit) { endRound({tier: r.hit.tier, display: r.hit.name}); return; }
  orb();
  // Long unmatched speech is usually chatter, not a wrong answer
  if (!typed && words(raw).length > 3) return;
  wrong(raw);
}
function wrong(raw) {
  const key = words(raw).join(' ');
  if (game.tried.has(key)) return; game.tried.add(key);
  timer.left = Math.max(0, timer.left - PENALTY_MS); buzz();
  const b = $('bar'); b.classList.remove('hit'); void b.offsetWidth; b.classList.add('hit');
  const chip = document.createElement('span'); chip.className = 'miss'; chip.textContent = '✕ ' + raw; $('misses').appendChild(chip);
}
async function repeat() {
  if (state !== 'play' || phase !== 'answer') return;
  const my = token; timer.running = false; stopRec(); phase = 'speaking'; orb();
  await speakPrompt(game.prompts[game.i]); if (my !== token) return;
  phase = 'answer'; orb(); startTimer(); startRec();
}

async function endRound(hit, why) {
  const my = ++token; timer.running = false; phase = 'done'; judging = false; stopRec(); orb();
  const p = game.prompts[game.i], M = MODES[game.scoring];
  const rv = await p.revealing; if (my !== token) return;
  const bestList = rv ? (game.scoring === 'rare' ? rv.krillion : rv.top) : [];
  const base = hit ? TS[hit.tier].pts : 0, bonus = hit ? Math.round(base * SPEED_MAX * Math.max(0, timer.left) / ROUND_MS) : 0;
  const r = {q: p.prompt, krill: bestList[0] || '', krills: bestList, tier: hit ? hit.tier : -1, answer: hit ? hit.display : null, base, bonus, pts: base + bonus};
  const pt = $('promptText'); pt.textContent = p.prompt; pt.classList.remove('veiled');
  game.rounds.push(r); game.score += r.pts; setDepth(game.score * 4); pips();
  const box = $('resultBox'); box.hidden = false;
  if (hit) {
    const t = TS[hit.tier]; chime(Math.round(t.pts / 20));
    box.innerHTML = `<div class="result" style="color:${t.c}"><div class="tn">${t.name}</div><div class="tp">${esc(hit.display)} · ${t.pts} + ${bonus} speed = ${r.pts} pts · +${r.pts * 4} m</div>${bestList.length ? `<div class="tp">${revealHTML(hit.tier === M.best ? 'All ' + M.reveal.toLowerCase() + 's' : M.reveal, bestList)}</div>` : ''}</div>`;
    $('status').textContent = 'Got it.';
  } else {
    box.innerHTML = `<div class="result" style="color:var(--muted)"><div class="tn">${why === 'skip' ? 'Skipped' : 'Out of air'}</div><div class="tp">${revealHTML(M.reveal, bestList)}</div></div>`;
    $('status').textContent = '';
  }
  // Results are shown, not spoken: a beat to read them, then the next question
  await new Promise(res => setTimeout(res, hit ? 2400 : 3200)); if (my !== token) return;
  game.i++;
  if (game.i < game.prompts.length) playRound(); else finish();
}

function finish() {
  state = 'end'; const m = game.score * 4, band = bandFor(m);
  rememberPlayed(game.prompts.map(p => p.slug));
  const key = 'kv-' + game.scoring + '-' + game.date;
  // The first daily dive of the day counts; replays don't overwrite it
  if (game.mode === 'daily' && !store.get(key)) store.set(key, {score: game.score, rounds: game.rounds});
  $('endLabel').textContent = `${game.mode === 'daily' ? `Daily dive · ${game.date}` : 'Practice dive'} · ${MODES[game.scoring].label}`;
  $('endDepth').innerHTML = `${fmt(m)}<span>m</span>`; $('endBand').textContent = band;
  renderLog(game.rounds);
  $('share').textContent = shareText(game.mode, game.date, m, band, game.rounds, game.scoring);
  stopRec(); show('end'); window.scrollTo(0, 0);
}
function renderLog(rounds) {
  const M = MODES[game.scoring || 'rare'];
  $('log').innerHTML = rounds.map(r => {
    const t = r.tier >= 0 ? M.tiers[r.tier] : null, bonus = r.bonus || 0;
    return `<div class="r"><div class="q">${esc(r.q)}</div><div class="pts" style="color:${t ? t.c : 'var(--muted)'}">${t ? '+' + r.pts : '0'}</div><div class="a">${t ? `${esc(r.answer)} · ${t.name}${bonus ? ` · +${bonus} speed` : ''}` : 'No answer'}</div>${r.krill ? `<div class="k">${revealHTML(r.tier === M.best ? 'All ' + M.reveal.toLowerCase() + 's' : M.reveal, r.krills || [r.krill])}</div>` : ''}</div>`;
  }).join('');
}
const shareText = (mode, date, m, band, rounds, sc = 'rare') =>
  `1 in a Krillion · voice · ${MODES[sc].label} · ${mode === 'daily' ? date : 'practice'}\n${fmt(m)} m · ${band}\n${rounds.map(r => r.tier >= 0 ? MODES[sc].tiers[r.tier].emoji : '⬛').join('')}`;

function home() {
  token++; state = 'start'; stopRec(); timer.running = false; stopVoice();
  const t = store.get('kv-' + scoring + '-' + todayKey()), box = $('todayBox');
  if (t) {
    const m = t.score * 4; box.hidden = false;
    box.innerHTML = `<div><div class="eyebrow">Today's dive · ${MODES[scoring].label}</div><div style="font:700 18px/1.3 var(--fd);margin-top:6px">${fmt(m)} m · ${bandFor(m)}</div><div style="letter-spacing:2px;margin-top:2px">${t.rounds.map(r => r.tier >= 0 ? TS[r.tier].emoji : '⬛').join('')}</div></div><button class="btn ghost" id="seeToday" type="button">See log</button>`;
    $('seeToday').onclick = () => {
      state = 'end'; game = {mode: 'daily', scoring, date: todayKey(), rounds: t.rounds, score: t.score};
      $('endLabel').textContent = `Daily dive · ${todayKey()} · ${MODES[scoring].label}`;
      $('endDepth').innerHTML = `${fmt(m)}<span>m</span>`; $('endBand').textContent = bandFor(m);
      renderLog(t.rounds); $('share').textContent = shareText('daily', todayKey(), m, bandFor(m), t.rounds, scoring); show('end');
    };
    $('beginBtn').textContent = 'Replay today’s prompts';
  } else { box.hidden = true; $('beginBtn').textContent = 'Begin today’s dive'; }
  setDepth(0); show('start');
}

// ---------- Wiring ----------
function setMode(m) {
  scoring = m; TS = MODES[m].tiers; try { localStorage.setItem('kv-mode', m); } catch (e) {}
  $('headline').innerHTML = MODES[m].head; $('lede').textContent = MODES[m].lede;
  $('modeRare').setAttribute('aria-checked', m === 'rare'); $('modePop').setAttribute('aria-checked', m === 'popular');
  $('tierTable').innerHTML = [...TS].sort((a, b) => a.pts - b.pts).map(t => `<div><span class="dot" style="background:${t.c}"></span>${t.name}</div><div class="p">${t.pts} pts</div><div class="m">${t.pts * 4} m</div>`).join('');
  if (state === 'start') home();
}
$('modeRare').onclick = () => setMode('rare'); $('modePop').onclick = () => setMode('popular');
if (!SR) $('micNote').innerHTML = '<strong>Heads up:</strong> this browser can’t listen for answers. Prompts are still read aloud; answer with your keyboard’s dictation mic. Chrome, Edge and Safari can listen.';
$('beginBtn').onclick = () => startGame('daily');
$('practiceBtn').onclick = () => startGame('practice');
$('againBtn').onclick = () => startGame('practice');
$('homeBtn').onclick = home;
$('repeatBtn').onclick = repeat;
$('skipBtn').onclick = () => { if (state === 'play' && phase === 'answer') endRound(null, 'skip'); };
$('typeForm').addEventListener('submit', e => { e.preventDefault(); const v = $('typeInput').value.trim(); if (!v) return; $('typeInput').value = ''; heard([v], true); });
$('copyBtn').onclick = () => {
  const txt = $('share').textContent, b = $('copyBtn');
  const ok = () => { b.textContent = 'Copied'; setTimeout(() => b.textContent = 'Copy result', 1600); };
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(ok, selectShare); else selectShare();
};
function selectShare() { const r = document.createRange(); r.selectNodeContents($('share')); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }

// ---------- Marine snow ----------
(() => {
  const cv = $('snow'), cx = cv.getContext('2d'); let W, H, pts = [];
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  function size() {
    const d = devicePixelRatio || 1; W = cv.width = innerWidth * d; H = cv.height = innerHeight * d;
    pts = Array.from({length: 70}, () => ({x: Math.random() * W, y: Math.random() * H, r: (Math.random() * 1.6 + .4) * d, v: (Math.random() * .25 + .08) * d, a: Math.random() * .35 + .1}));
  }
  function draw() {
    cx.clearRect(0, 0, W, H);
    for (const p of pts) {
      if (!still) { p.y -= p.v; p.x += Math.sin(p.y / 60) * .15; if (p.y < -4) { p.y = H + 4; p.x = Math.random() * W; } }
      cx.fillStyle = `rgba(210,245,240,${p.a})`; cx.beginPath(); cx.arc(p.x, p.y, p.r, 0, 7); cx.fill();
    }
    if (!still) requestAnimationFrame(draw);
  }
  addEventListener('resize', size); size(); draw();
})();

setMode(scoring); home();
