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
    lede: 'Say the rarest true answer you can think of. Every point takes you four metres deeper.',
    reveal: 'Krillion answer'},
  popular: {label: 'Popular wins', tiers: TIERS_POP, best: 0, head: 'Swim with the <em>school.</em>',
    lede: 'Say the answer most people would say first. The crowd’s favorite pays 100; the oddball pays 10.',
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
const bandFor = m => BANDS.reduce((b, [t, n]) => m >= t ? n : b, 'Shallows');
const fmt = n => n.toLocaleString('en-US');
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

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
  if (window.Ocean) Ocean.goTo(m);  // the fish dives (or swims back up) to match
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

// ---------- Question voice ----------
// The player picks a Gemini voice and accent. The server records each question
// in that voice the first time it is asked for, then serves it from disk.
let voiceCfg = store.get('kv-voice'), voiceOpts = null;
// Reading questions aloud is opt-in (Settings): off by default
let speakOn = store.get('kv-speak') === true;
function applySpeak() {
  $('speakToggle').checked = speakOn;
  $('voiceFields').disabled = !speakOn;
  $('repeatBtn').hidden = !speakOn;
  $('readyHow').textContent = speakOn ? 'Each question is read aloud, then your air starts.' : 'Each question appears with 25 seconds of air.';
}
const accentLang = () => (voiceOpts && voiceOpts.accents.find(a => a.id === voiceCfg.accent) || {}).lang || 'en-US';
const clipUrl = slug => `api/audio?slug=${encodeURIComponent(slug)}&voice=${encodeURIComponent(voiceCfg.voice)}&accent=${voiceCfg.accent}`;
async function loadVoices() {
  try { voiceOpts = await api('/api/voices'); } catch (e) { $('voiceHint').textContent = 'Voices are unavailable; questions use your browser’s voice.'; return; }
  if (!voiceCfg || !voiceOpts.voices.some(v => v.id === voiceCfg.voice)) voiceCfg = voiceOpts.default;
  $('voiceSel').innerHTML = voiceOpts.voices.map(v => `<option value="${v.id}">${v.id} · ${v.character}, ${v.gender}</option>`).join('');
  $('accentSel').innerHTML = voiceOpts.accents.map(a => `<option value="${a.id}">${a.label}</option>`).join('');
  $('voiceSel').value = voiceCfg.voice; $('accentSel').value = voiceCfg.accent;
}
function chooseVoice() {
  voiceCfg = {voice: $('voiceSel').value, accent: $('accentSel').value}; store.set('kv-voice', voiceCfg);
  $('voiceHint').textContent = `Questions will be read by ${voiceCfg.voice} with ${/^[AEIOU]/.test($('accentSel').selectedOptions[0].text) ? 'an' : 'a'} ${$('accentSel').selectedOptions[0].text} accent.`;
}
async function previewVoice() {
  if (!voiceOpts) return;
  if (!actx) { try { actx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) {} }
  if (actx && actx.state === 'suspended') actx.resume();
  const b = $('previewBtn'); b.disabled = true; b.textContent = 'Loading…';
  stopVoice();
  const buf = await loadClip(`api/preview?voice=${encodeURIComponent(voiceCfg.voice)}&accent=${voiceCfg.accent}`);
  if (buf) await playBuffer(buf); else await say('Welcome to Krillion. Here comes your first question.');
  b.disabled = false; b.textContent = 'Preview';
}

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
  const buf = voiceCfg ? await loadClip(clipUrl(p.slug)) : null;
  if (!buf) return say(p.prompt + '.');
  return playBuffer(buf);
}
function playBuffer(buf) {
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
    const u = new SpeechSynthesisUtterance(text); u.rate = 1.03;
    const lang = voiceCfg ? accentLang() : 'en-US', vs = speechSynthesis.getVoices();
    const match = vs.find(v => v.lang.replace('_', '-') === lang) || voice;
    if (match) { u.voice = match; u.lang = match.lang; }
    let done = false; const fin = () => { if (!done) { done = true; clearTimeout(t); res(); } };
    u.onend = fin; u.onerror = fin;
    const t = setTimeout(fin, 1800 + text.length * 85); // some browsers never fire onend
    speechSynthesis.speak(u);
  });
}

// ---------- Speech recognition: push to talk ----------
// The mic only listens while Space or the Talk button is held, so players can
// talk an answer over first. Releasing stops (not aborts) recognition, so the
// last words still arrive as a final result.
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null, listening = false, wantListen = false, holding = false, micBlocked = !SR, lastInterim = 0;
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
  // Chrome ends a session after a silence; keep listening while the key is still held
  rec.onend = () => { listening = false; orb(); if (wantListen && holding && !micBlocked) setTimeout(startRec, 60); };
}
function startRec() { if (!rec || micBlocked) return; wantListen = true; if (listening) return; try { rec.start(); } catch (e) {} }
function stopRec() { wantListen = false; holding = false; talkUI(); if (rec && listening) { try { rec.abort(); } catch (e) {} } }
function releaseRec() { wantListen = false; if (rec && listening) { try { rec.stop(); } catch (e) {} } }

const canTalk = () => state === 'play' && phase === 'answer' && !judging && !micBlocked;
function talkUI() {
  const b = $('talkBtn'); b.classList.toggle('down', holding);
  b.disabled = !(state === 'play' && phase === 'answer' && !micBlocked);
  b.textContent = holding ? 'Listening…' : 'Hold to talk';
}
function talkDown() { if (holding || !canTalk()) return; holding = true; $('heard').textContent = ''; startRec(); talkUI(); orb(); }
function talkUp() { if (!holding) return; holding = false; releaseRec(); talkUI(); orb(); }

// ---------- Game ----------
let state = 'start', phase = 'idle', game = null, judging = false, token = 0;
const timer = {left: ROUND_MS, running: false, last: 0};

function orb() {
  const o = $('orb'); o.className = 'orb'; let s = '';
  if (state !== 'play') return;
  if (judging) { o.classList.add('checking'); s = 'Checking that answer…'; }
  else if (phase === 'speaking') { o.classList.add('speaking'); s = 'Reading the prompt…'; }
  else if (phase === 'answer' && micBlocked) { o.classList.add('blocked'); s = SR ? 'Mic is blocked here. Type, or use your keyboard’s dictation mic.' : 'This browser can’t listen. Type, or use your keyboard’s dictation mic.'; }
  else if (phase === 'answer' && holding && listening) { o.classList.add('listening'); s = 'Listening. Let go when you’ve answered.'; }
  else if (phase === 'answer' && holding) { o.classList.add('listening'); s = 'Starting the mic…'; }
  else if (phase === 'answer') { s = 'Hold Space or the Talk button to answer.'; }
  if (s) $('status').textContent = s;
  if ($('talkBtn')) talkUI();
}

function show(id) {
  ['start', 'ready', 'play', 'end'].forEach(s => $(s).hidden = s !== id);
  $('pips').hidden = id !== 'play';
  // Settings are for between dives: opening them mid-question would eat air
  $('settingsBtn').hidden = id === 'play';
  // The dive log sits beside the game while playing; the end screen has the full summary
  $('side').hidden = id !== 'play';
  document.querySelector('.app').classList.toggle('playing', id === 'play');
  if (window.Ocean) Ocean.layout();
}
function pips() {
  $('pips').innerHTML = game.prompts.map((_, i) => {
    const r = game.rounds[i]; const c = r ? (r.tier >= 0 ? TS[r.tier].c : 'var(--line)') : 'transparent';
    return `<span class="pip ${i === game.i ? 'now' : ''}" style="background:${c}"></span>`;
  }).join('');
}

// A generated dive waits here until the player presses Start. Backing out
// keeps it, so the next New dive reuses it instead of generating (and paying
// for) another set.
let readyPrompts = null;

// New dive: generate the questions, then wait on the ready screen. This click
// is also the user gesture browsers need before audio and the mic can start.
async function newDive() {
  if (!actx) { try { actx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) {} }
  if (actx && actx.state === 'suspended') actx.resume();
  if ('speechSynthesis' in window) { speechSynthesis.cancel(); pickVoice(); }
  setupRec();
  const btns = [$('beginBtn'), $('againBtn')];
  if (!readyPrompts) {
    // The server usually has a dive prepared; if not, generating takes 20-50 seconds.
    btns.forEach(b => { b.disabled = true; b.textContent = 'Generating new questions…'; });
    const v = voiceCfg ? `?voice=${encodeURIComponent(voiceCfg.voice)}&accent=${voiceCfg.accent}` : '';
    let d;
    try {
      const r = await fetch('/api/dive' + v);
      d = await r.json();
      if (!r.ok) throw new Error(d.error || 'failed');
    } catch (e) {
      home();
      btns.forEach(b => { b.disabled = false; b.textContent = 'New dive'; });
      $('lede').textContent = (e && e.message && e.message !== 'failed' && !/fetch/i.test(e.message)) ? e.message : 'Couldn’t reach the game server. Is it running?';
      return;
    }
    readyPrompts = d.prompts;
    btns.forEach(b => { b.disabled = false; b.textContent = 'New dive'; });
  }
  // Load the first question's recording while the player gets ready
  if (speakOn && voiceCfg && readyPrompts[0]) loadClip(clipUrl(readyPrompts[0].slug));
  state = 'ready'; setDepth(0);
  $('readyTitle').textContent = `${readyPrompts.length} new questions`;
  show('ready'); window.scrollTo(0, 0); $('goBtn').focus();
}

// Start: the dive begins and the first question is read
function beginDive() {
  if (state !== 'ready' || !readyPrompts) return;
  if (actx && actx.state === 'suspended') actx.resume();
  if (navigator.wakeLock) navigator.wakeLock.request('screen').catch(() => {});
  TS = MODES[scoring].tiers;
  game = {scoring, prompts: readyPrompts, i: 0, rounds: [], score: 0};
  readyPrompts = null;
  state = 'play';
  renderSide(); setDepth(0); show('play'); playRound();
}

// The answer list for a brand-new category takes about a minute to build.
// Wait a little for it; if it's still building, the reveal is left out.
async function revealFor(slug) {
  for (let i = 0; i < 4; i++) {
    let r = null;
    try { r = await api(`/api/reveal?slug=${encodeURIComponent(slug)}`); } catch (e) { return null; }
    if (!r.pending) return r;
    $('status').textContent = 'Finding the krillion answers…';
    await new Promise(res => setTimeout(res, 1500));
  }
  return null;
}

async function playRound() {
  const my = ++token, p = game.prompts[game.i];
  p.revealing = null;  // fetched at the end of the round, when the answer list is likelier to be ready
  phase = 'speaking'; judging = false;
  $('roundLabel').textContent = `Prompt ${game.i + 1} of ${game.prompts.length} · ${MODES[game.scoring].label}`;
  const pt = $('promptText');
  if (speakOn) { pt.textContent = 'Listen closely…'; pt.classList.add('veiled'); }
  else { pt.textContent = p.prompt; pt.classList.remove('veiled'); }
  $('heard').textContent = ''; $('misses').innerHTML = ''; $('resultBox').hidden = true; $('typeInput').value = '';
  game.tried = new Set(); timer.left = ROUND_MS; timer.running = false; drawAir(); pips(); orb();
  stopRec();
  if (speakOn) {
    // Record the next question while this one is answered (just in time)
    const next = game.prompts[game.i + 1]; if (next && voiceCfg) loadClip(clipUrl(next.slug));
    await speakPrompt(p);
    if (my !== token) return;
  }
  phase = 'answer'; orb(); startTimer();
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
  if (r && r.hit) { endRound({tier: r.hit.tier, display: r.hit.name, ladder: r.hit.ladder}); return; }
  orb();
  wrong(raw);
}
function wrong(raw) {
  const key = words(raw).join(' ');
  if (game.tried.has(key)) return; game.tried.add(key);
  timer.left = Math.max(0, timer.left - PENALTY_MS); buzz();
  if (window.Ocean) Ocean.miss();
  const b = $('bar'); b.classList.remove('hit'); void b.offsetWidth; b.classList.add('hit');
  const chip = document.createElement('span'); chip.className = 'miss'; chip.textContent = '✕ ' + raw; $('misses').appendChild(chip);
}
async function repeat() {
  if (!speakOn || state !== 'play' || phase !== 'answer') return;
  const my = token; timer.running = false; stopRec(); phase = 'speaking'; orb();
  await speakPrompt(game.prompts[game.i]); if (my !== token) return;
  phase = 'answer'; orb(); startTimer();
}

async function endRound(hit, why) {
  const my = ++token; timer.running = false; phase = 'done'; judging = false; stopRec(); orb();
  const p = game.prompts[game.i], M = MODES[game.scoring];
  const rv = await revealFor(p.slug); if (my !== token) return;
  const bestList = rv ? (game.scoring === 'rare' ? rv.krillion : rv.top) : [];
  const base = hit ? TS[hit.tier].pts : 0, bonus = hit ? Math.round(base * SPEED_MAX * Math.max(0, timer.left) / ROUND_MS) : 0;
  const r = {q: p.prompt, slug: p.slug, pending: !rv, krill: bestList[0] || '', krills: bestList, tier: hit ? hit.tier : -1, answer: hit ? hit.display : null, base, bonus, pts: base + bonus};
  const pt = $('promptText'); pt.textContent = p.prompt; pt.classList.remove('veiled');
  game.rounds.push(r); game.score += r.pts; setDepth(game.score * 4); pips();
  renderSide();
  if (r.pending) watchReveal(game, r);
  const box = $('resultBox'); box.hidden = false;
  if (hit) {
    const t = TS[hit.tier];
    const lad = hit.ladder;
    const rankText = lad ? (lad.rank ? ` · #${lad.rank} of ${lad.total}` : ' · not on the list') : '';
    box.innerHTML = `<div class="result" style="color:${t.c}"><div class="tn">${t.name}</div><div class="tp">${esc(hit.display)}${rankText} · ${t.pts} + ${bonus} speed = ${r.pts} pts · +${r.pts * 4} m</div>${bestList.length ? `<div class="tp">${revealHTML(hit.tier === M.best ? 'All ' + M.reveal.toLowerCase() + 's' : M.reveal, bestList)}</div>` : ''}</div>`;
    $('status').textContent = 'Got it.';
    // The fish falls through a slice of the answer list and slots in at the
    // answer's rank; the celebration fires as it lands. Without room for the
    // ladder (narrow screens) it celebrates straight away.
    const land = () => { chime(Math.round(t.pts / 20)); if (window.Ocean) Ocean.celebrate(t.pts, r.pts * 4); };
    const played = lad && window.Ocean ? await Ocean.slot(ladderFor(lad, hit, land)) : false;
    if (my !== token) return;
    if (!played) { land(); await new Promise(res => setTimeout(res, 2400)); }
    else await new Promise(res => setTimeout(res, 300));
    if (my !== token) return;
  } else {
    box.innerHTML = `<div class="result" style="color:var(--muted)"><div class="tn">${why === 'skip' ? 'Skipped' : 'Out of air'}</div><div class="tp">${revealHTML(M.reveal, bestList)}</div></div>`;
    $('status').textContent = '';
    // Results are shown, not spoken: a beat to read them, then the next question
    await new Promise(res => setTimeout(res, 3200)); if (my !== token) return;
  }
  game.i++;
  if (game.i < game.prompts.length) playRound(); else finish();
}

// What the ocean needs to draw the ranking ladder: canvas can't read CSS
// variables, so tier colours are resolved here.
function ladderFor(lad, hit, onLand) {
  const css = getComputedStyle(document.documentElement);
  const color = c => (c.startsWith('var(') ? css.getPropertyValue(c.slice(4, -1)).trim() : c) || '#5fe3d2';
  const colors = {}, labels = {};
  TS.forEach((x, i) => { colors[i] = color(x.c); labels[i] = x.name; });
  return {rows: lad.rows, position: lad.position, rank: lad.rank, answer: hit.display, tier: hit.tier,
    color: colors[hit.tier], colors, labels, onLand};
}

function finish() {
  state = 'end'; const m = game.score * 4, band = bandFor(m);
  $('endLabel').textContent = `Dive complete · ${MODES[game.scoring].label}`;
  $('endDepth').innerHTML = `${fmt(m)}<span>m</span>`; $('endBand').textContent = band;
  renderLog(game.rounds);
  $('share').textContent = shareText(m, band, game.rounds, game.scoring);
  stopRec(); show('end'); window.scrollTo(0, 0);
}
// Every winning answer for a question: all One in a Krillion answers in Rare
// mode, all top answers in Popular mode.
function winnersHTML(r, M) {
  const label = M.reveal + 's';
  if (r.pending) return `<span class="winners pending">Finding ${label.toLowerCase()}…</span>`;
  const list = r.krills && r.krills.length ? r.krills : (r.krill ? [r.krill] : []);
  if (!list.length) return '';
  return `<span class="winners">${label}: ${list.map(n => `<b>${esc(n)}</b>`).join(' · ')}</span>`;
}

// The dive log beside the game: newest first, so the question just played is on top
function renderSide() {
  if (!game) return;
  const M = MODES[game.scoring];
  $('sideEmpty').hidden = game.rounds.length > 0;
  $('sideList').innerHTML = game.rounds.map(r => {
    const t = r.tier >= 0 ? M.tiers[r.tier] : null;
    const said = t ? `<span style="color:${t.c}">${esc(r.answer)} · ${t.name} · +${r.pts}</span>` : '<span style="color:var(--muted)">No answer</span>';
    return `<li class="sideItem"><div class="sq">${esc(r.q)}</div><div class="sa">${said}</div><div>${winnersHTML(r, M)}</div></li>`;
  }).reverse().join('');
}

// A brand-new question's answer list can still be building when the round
// ends. Keep checking, and fill in its winning answers once they're ready.
async function watchReveal(g, r) {
  for (let i = 0; i < 60 && r.pending; i++) {
    await new Promise(res => setTimeout(res, 4000));
    if (game !== g) return;
    let rv = null;
    try { rv = await api(`/api/reveal?slug=${encodeURIComponent(r.slug)}`); } catch (e) { continue; }
    if (rv.pending) continue;
    r.krills = g.scoring === 'rare' ? rv.krillion : rv.top; r.krill = r.krills[0] || ''; r.pending = false;
    renderSide();
    if (state === 'end') renderLog(g.rounds);
  }
}

function renderLog(rounds) {
  const M = MODES[game.scoring || 'rare'];
  $('log').innerHTML = rounds.map(r => {
    const t = r.tier >= 0 ? M.tiers[r.tier] : null, bonus = r.bonus || 0;
    return `<div class="r"><div class="q">${esc(r.q)}</div><div class="pts" style="color:${t ? t.c : 'var(--muted)'}">${t ? '+' + r.pts : '0'}</div><div class="a">${t ? `${esc(r.answer)} · ${t.name}${bonus ? ` · +${bonus} speed` : ''}` : 'No answer'}</div><div class="k">${winnersHTML(r, M)}</div></div>`;
  }).join('');
}
const shareText = (m, band, rounds, sc = 'rare') =>
  `1 in a Krillion · voice · ${MODES[sc].label}\n${fmt(m)} m · ${band}\n${rounds.map(r => r.tier >= 0 ? MODES[sc].tiers[r.tier].emoji : '⬛').join('')}`;

function home() {
  token++; state = 'start'; stopRec(); timer.running = false; stopVoice();
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
$('beginBtn').onclick = newDive;
$('againBtn').onclick = newDive;
$('goBtn').onclick = beginDive;
$('backBtn').onclick = home;
$('voiceSel').onchange = chooseVoice; $('accentSel').onchange = chooseVoice;
$('previewBtn').onclick = previewVoice;
$('speakToggle').onchange = () => {
  speakOn = $('speakToggle').checked; store.set('kv-speak', speakOn);
  if (!speakOn) stopVoice();
  applySpeak();
};
applySpeak();

// Settings dialog: the gear opens it; Escape, the close button or a click on
// the backdrop closes it.
const settings = $('settings');
$('settingsBtn').onclick = () => settings.showModal();
settings.addEventListener('click', e => { if (e.target === settings) settings.close(); });
settings.addEventListener('close', () => { stopVoice(); $('settingsBtn').focus(); });

// Push to talk: hold Space anywhere except while typing, or hold the button
const typing = el => el && (el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.tagName === 'TEXTAREA');
addEventListener('keydown', e => {
  if (e.code !== 'Space' || typing(document.activeElement) || state !== 'play' || settings.open) return;
  e.preventDefault(); if (!e.repeat) talkDown();
});
addEventListener('keyup', e => { if (e.code === 'Space' && holding) { e.preventDefault(); talkUp(); } });
addEventListener('blur', talkUp);  // switching windows mid-hold must not leave the mic open
const tb = $('talkBtn');
tb.addEventListener('pointerdown', e => { e.preventDefault(); tb.setPointerCapture(e.pointerId); talkDown(); });
['pointerup', 'pointercancel', 'lostpointercapture'].forEach(t => tb.addEventListener(t, talkUp));
tb.addEventListener('contextmenu', e => e.preventDefault());
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


setMode(scoring); home(); loadVoices();
