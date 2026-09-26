/**
 * app.js — MAYA Web App
 * Fixed: gapless TTS scheduling, TTS→orb amplitude, mic→orb amplitude, null guards
 */

// ── DOM refs ─────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const micBtn           = $('micBtn');
const micHint          = $('micHint');
const statusDot        = $('statusDot');
const statusText       = $('statusText');
const headerTime       = $('headerTime');
const transcriptEl     = $('transcriptScroll');
const cardContainer    = $('cardContainer');
const cardTypeBadge    = $('cardTypeBadge');
const historyList      = $('historyList');
const clearHistoryBtn  = $('clearHistoryBtn');
const emergencyOverlay = $('emergencyOverlay');
const emergencyCancelBtn = $('emergencyCancelBtn');
const settingsBtn      = $('settingsBtn');
const settingsModal    = $('settingsModal');
const settingsClose    = $('settingsClose');

// ── State ────────────────────────────────────────────────────────────────────
let ws          = null;
let orb         = null;
let micCtx      = null;
let playCtx     = null;
let workletNode = null;
let micStream   = null;
let micAnalyser = null;
let ttsAnalyser = null;
let ttsGain     = null;
let _nextPlayTime  = 0;
let ttsPlaying  = false;
let micAmpFrame = null;
let ttsAmpFrame = null;
let ttsAmpBuf   = null;
let sessionActive = false;

// ── Live clock ────────────────────────────────────────────────────────────────
function tickClock() {
  const now = new Date();
  const h = now.getHours().toString().padStart(2,'0');
  const m = now.getMinutes().toString().padStart(2,'0');
  if (headerTime) headerTime.textContent = `${h}:${m}`;
}
tickClock(); setInterval(tickClock, 10000);

// ── Orb init ──────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => { orb = new MayaOrb('orbCanvas'); });

// ── Status ────────────────────────────────────────────────────────────────────
function setStatus(cls, text) {
  if (statusDot)  statusDot.className   = `status-dot ${cls}`;
  if (statusText) statusText.textContent = text;
}

// ── Transcript ────────────────────────────────────────────────────────────────
function addTranscript(role, content) {
  if (!content) return;
  const welcome = transcriptEl.querySelector('.transcript-welcome');
  if (welcome) welcome.remove();

  const div = document.createElement('div');
  div.className = `transcript-msg ${role}`;
  const now = new Date().toLocaleTimeString([], { hour:'2-digit', minute:'2-digit' });

  const avatar = role === 'user'
    ? `<div class="msg-avatar user-avatar">YOU</div>`
    : `<div class="msg-avatar ai-avatar"><svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.5"/><path d="M8 12h8M12 8v8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></div>`;

  div.innerHTML = `
    ${avatar}
    <div class="msg-content">
      <div class="msg-bubble">${escHtml(content)}</div>
      <div class="msg-time">${now}</div>
    </div>`;
  transcriptEl.appendChild(div);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

function escHtml(s) {
  return String(s||'')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

// ── Loading card (shown immediately while function executes) ────────────────────
const _FN_LABELS = {
  get_weather:'Fetching Weather', get_weather_forecast:'Fetching Forecast',
  get_time:'Checking Time', get_date:'Checking Date',
  set_alarm:'Setting Alarm', set_reminder:'Setting Reminder',
  play_music:'Loading Music', pause_music:'Pausing Music',
  get_health_summary:'Loading Health Data', log_health_metric:'Logging Health',
  emergency_alert:'Emergency Alert',
  get_medication_info:'Looking Up Medication',
};

function showLoadingCard(fname) {
  const label = _FN_LABELS[fname] || fname.replace(/_/g,' ').replace(/\b\w/g, c=>c.toUpperCase());
  cardContainer.innerHTML = `
    <div class="lc-wrap">
      <div class="lc-header">
        <div class="lc-pulse-ring"></div>
        <span class="lc-label">${label}</span>
        <div class="lc-dots"><span></span><span></span><span></span></div>
      </div>
      <div class="lc-lines">
        <div class="lc-line" style="width:75%"></div>
        <div class="lc-line" style="width:50%"></div>
        <div class="lc-line" style="width:65%"></div>
      </div>
    </div>`;
  cardTypeBadge.textContent = 'Processing…';
  cardTypeBadge.className   = 'card-type-badge loading';
}

// ── Card display ───────────────────────────────────────────────────────────────
function showCard(uiType, uiData, resultText) {
  if (!uiType || uiType === 'none') return;
  uiData = uiData || {};
  const html = CardRenderer.renderCard(uiType, uiData);
  if (!html) return;
  cardContainer.innerHTML = html;
  const badge = CardRenderer.getCardBadge(uiType);
  cardTypeBadge.textContent = badge.text;
  cardTypeBadge.className   = `card-type-badge ${badge.cls}`;
  addHistory(uiType, uiData, resultText);
  if (uiType === 'emergency') {
    emergencyOverlay.style.display = uiData.active ? 'flex' : 'none';
    if (uiData.active) startEmergencyAlarm(); else stopEmergencyAlarm();
  }
}

// ── Emergency alarm sound (Web Audio beeping siren) ───────────────────────────
// Uses the shared playCtx which is already unlocked by the mic-button user gesture.
let _alarmInterval = null;

function startEmergencyAlarm() {
  stopEmergencyAlarm();
  // Use the shared playCtx — already unlocked by the mic-button user gesture.
  // If it doesn't exist yet, create it (page has been activated so resume() will work).
  ensurePlayCtx();
  if (!playCtx) return;

  function _doAlarm() {
    if (!playCtx || playCtx.state === 'closed') return;

    function beep(freq, startAt, duration) {
      if (!playCtx || playCtx.state === 'closed') return;
      const osc  = playCtx.createOscillator();
      const gain = playCtx.createGain();
      osc.type = 'square';
      osc.frequency.setValueAtTime(freq, startAt);
      gain.gain.setValueAtTime(0.3, startAt);
      gain.gain.setValueAtTime(0.0, startAt + duration);
      osc.connect(gain);
      gain.connect(playCtx.destination);
      osc.start(startAt);
      osc.stop(startAt + duration);
    }

    function schedulePattern() {
      if (!playCtx || playCtx.state === 'closed') return;
      const t = playCtx.currentTime;
      for (let i = 0; i < 5; i++) {
        beep(880, t + i * 2.0,       0.8);
        beep(660, t + i * 2.0 + 0.9, 0.8);
      }
    }

    schedulePattern();
    _alarmInterval = setInterval(schedulePattern, 10000);
  }

  // resume() is async — only schedule beeps AFTER context is actually running
  if (playCtx.state === 'suspended') {
    playCtx.resume().then(_doAlarm);
  } else {
    _doAlarm();
  }
}

function stopEmergencyAlarm() {
  if (_alarmInterval) { clearInterval(_alarmInterval); _alarmInterval = null; }
  // playCtx is shared — don't close it, just stop scheduling new beeps
}

// ── History ────────────────────────────────────────────────────────────────────
function addHistory(uiType, uiData, resultText) {
  const empty = historyList.querySelector('.history-empty');
  if (empty) empty.remove();
  const html = CardRenderer.getHistoryItem(uiType, uiData||{}, resultText||'');
  const tmp  = document.createElement('div');
  tmp.innerHTML = html.trim();
  const item = tmp.firstElementChild;
  if (!item) return;
  item.dataset.uiType     = uiType;
  item.dataset.uiData     = JSON.stringify(uiData||{});
  item.dataset.resultText = resultText||'';
  historyList.insertBefore(item, historyList.firstChild);
  while (historyList.children.length > 20) historyList.removeChild(historyList.lastChild);
}

window._replayCard = function(uiType, el) {
  try { showCard(uiType, JSON.parse(el.dataset.uiData||'{}'), el.dataset.resultText||''); } catch {}
};

clearHistoryBtn.addEventListener('click', () => {
  historyList.innerHTML = `<div class="history-empty"><div class="empty-icon">⌛</div><p>No commands yet.<br>Say something to begin.</p></div>`;
});

// ═══════════════════════════════════════════════════════════════════════════
// TTS — gapless scheduled playback + analyser for orb
// ═══════════════════════════════════════════════════════════════════════════

function ensurePlayCtx() {
  if (playCtx && playCtx.state !== 'closed') return;
  playCtx       = new AudioContext({ sampleRate: 24000 });
  _nextPlayTime = 0;
  ttsGain     = playCtx.createGain();
  ttsAnalyser = playCtx.createAnalyser();
  ttsAnalyser.fftSize     = 1024;   // time-domain: fftSize samples per read
  ttsAnalyser.smoothingTimeConstant = 0.5;
  ttsAmpBuf   = new Uint8Array(ttsAnalyser.fftSize);
  ttsGain.connect(ttsAnalyser);
  ttsAnalyser.connect(playCtx.destination);
  _startTTSAmp();
}

function _startTTSAmp() {
  if (ttsAmpFrame) cancelAnimationFrame(ttsAmpFrame);
  function tick() {
    if (!ttsAnalyser || !ttsAmpBuf) { ttsAmpFrame = requestAnimationFrame(tick); return; }
    ttsAnalyser.getByteTimeDomainData(ttsAmpBuf);
    let sum = 0;
    for (let i = 0; i < ttsAmpBuf.length; i++) {
      const v = (ttsAmpBuf[i] - 128) / 128;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / ttsAmpBuf.length);
    // Always push TTS amplitude to orb — TTS is the AI's voice, orb should always react to it
    if (orb) orb.setAmplitude(Math.min(1, rms * 7));
    ttsAmpFrame = requestAnimationFrame(tick);
  }
  tick();
}

function enqueueTTS(arrayBuffer) {
  ensurePlayCtx();
  if (playCtx.state === 'suspended') playCtx.resume();
  const int16   = new Int16Array(arrayBuffer);
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768.0;
  const audioBuf = playCtx.createBuffer(1, float32.length, 24000);
  audioBuf.copyToChannel(float32, 0);
  const src = playCtx.createBufferSource();
  src.buffer = audioBuf;
  src.connect(ttsGain);
  const now  = playCtx.currentTime;
  const when = _nextPlayTime < now + 0.03 ? now + 0.03 : _nextPlayTime;
  src.start(when);
  _nextPlayTime = when + audioBuf.duration;
  ttsPlaying    = true;
  src.addEventListener('ended', () => {
    if (_nextPlayTime <= (playCtx?.currentTime ?? 0) + 0.06) {
      ttsPlaying = false;
      if (orb) orb.setAmplitude(0);
    }
  });
}

function flushTTS() {
  if (ttsGain && playCtx) {
    ttsGain.gain.cancelScheduledValues(playCtx.currentTime);
    ttsGain.gain.setValueAtTime(0, playCtx.currentTime);
    ttsGain.gain.linearRampToValueAtTime(1, playCtx.currentTime + 0.5);
  }
  _nextPlayTime = playCtx ? playCtx.currentTime + 0.06 : 0;
  ttsPlaying    = false;
  if (orb) orb.setAmplitude(0);
}

// ═══════════════════════════════════════════════════════════════════════════
// MIC BUTTON ANIMATION — mic amplitude drives the button, NOT the orb
// ═══════════════════════════════════════════════════════════════════════════

function _animateMicBtn(rms) {
  if (!micBtn || !sessionActive) return;
  // Soft glow only — no scale, no border change, no expanding ring.
  // Glow appears only when there is actual mic input (rms > noise floor).
  if (rms > 0.015) {
    const spread = Math.min(22, rms * 90).toFixed(0);
    const a1     = Math.min(0.6, rms * 3.2).toFixed(3);
    const a2     = Math.min(0.22, rms * 1.1).toFixed(3);
    micBtn.style.boxShadow = `0 0 ${spread}px rgba(0,212,255,${a1}), 0 0 ${+spread * 2}px rgba(0,212,255,${a2})`;
  } else {
    micBtn.style.boxShadow = '';
  }
}

function _resetMicBtn() {
  if (!micBtn) return;
  micBtn.style.boxShadow = '';
}

function startMicAmp(stream) {
  if (!micCtx) return;
  micAnalyser = micCtx.createAnalyser();
  micAnalyser.fftSize = 256;
  micAnalyser.smoothingTimeConstant = 0.15;  // very fast response
  const src = micCtx.createMediaStreamSource(stream);
  src.connect(micAnalyser);
  const buf = new Uint8Array(micAnalyser.frequencyBinCount); // 128 bins
  // For 16 kHz audio with fftSize=256: bin width = 62.5 Hz
  // Speech energy lives roughly in bins 4-50 (250 Hz – 3.1 kHz)
  // Averaging ALL 128 bins buries speech energy in silent high-freq bins.
  const SPEECH_LO = 4, SPEECH_HI = 52;
  function tick() {
    if (!micAnalyser) { micAmpFrame = requestAnimationFrame(tick); return; }
    micAnalyser.getByteFrequencyData(buf);
    let sum = 0;
    for (let i = SPEECH_LO; i < SPEECH_HI; i++) sum += buf[i];
    const avg = sum / (SPEECH_HI - SPEECH_LO) / 255; // normalised 0-1 over speech band
    // Mic drives the button visual ONLY — not the orb
    _animateMicBtn(avg);
    micAmpFrame = requestAnimationFrame(tick);
  }
  tick();
}

function stopMicAmp() {
  if (micAmpFrame) { cancelAnimationFrame(micAmpFrame); micAmpFrame = null; }
  _resetMicBtn();
  micAnalyser = null;
}

// ═══════════════════════════════════════════════════════════════════════════
// WEBSOCKET
// ═══════════════════════════════════════════════════════════════════════════

function openWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.binaryType = 'arraybuffer';

  ws.onopen = () => { setStatus('connecting','Connecting…'); if (orb) orb.setState('thinking'); };

  ws.onmessage = e => {
    if (e.data instanceof ArrayBuffer) { enqueueTTS(e.data); return; }
    let msg; try { msg = JSON.parse(e.data); } catch { return; }
    const t = msg.type;

    if (t === 'Welcome' || t === 'SettingsApplied') {
      setStatus('ready','Ready'); if (orb) orb.setState('idle');
    }
    else if (t === 'UserStartedSpeaking') {
      setStatus('listening','Listening…');
      if (orb) orb.setState('listening');
      flushTTS();
    }
    else if (t === 'AgentThinking') {
      setStatus('connecting','Thinking…');
      if (orb) { orb.setState('thinking'); orb.setAmplitude(0); }
    }
    else if (t === 'AgentStartedSpeaking') {
      setStatus('speaking','Speaking…'); if (orb) orb.setState('speaking');
    }
    else if (t === 'AgentFinishedSpeaking') {
      setStatus('ready','Ready');
      if (orb) { orb.setState('idle'); orb.setAmplitude(0); }
    }
    else if (t === 'ConversationText') {
      if (msg.content) addTranscript(msg.role === 'user' ? 'user' : 'assistant', msg.content);
      // Client-side emergency stop-word detection — fires immediately without
      // waiting for the AI function-call round-trip.
      if (msg.role === 'user' && _alarmInterval) {
        const _STOP_WORDS = [
          'cancel emergency','stop emergency','cancel sos','stop sos',
          'all clear','i am safe','i\'m safe','false alarm','never mind',
          'abort emergency','stop the alarm','silence alarm','cancel alert',
          'stop alert','it\'s ok','everything is fine','i am fine','stop it',
        ];
        const lower = (msg.content || '').toLowerCase();
        if (_STOP_WORDS.some(w => lower.includes(w))) {
          stopEmergencyAlarm();
          emergencyOverlay.style.display = 'none';
        }
      }
    }
    else if (t === 'UICardLoading') {
      showLoadingCard(msg.function_name || '');
    }
    else if (t === 'UICard') {
      showCard(msg.ui_type, msg.ui_data||{}, msg.result_text||'');
    }
    else if (t === 'Limit') {
      // public demo: session length, concurrency or daily budget reached
      if (msg.message) addTranscript('assistant', msg.message);
      stopSession();
    }
    else if (t === 'Error') {
      setStatus('error','Error'); console.error('MAYA:', msg.message);
      if (msg.message) addTranscript('assistant', `⚠ ${msg.message}`);
    }
  };

  ws.onerror = () => setStatus('error','Connection error');
  ws.onclose = () => { setStatus('error','Disconnected'); _onSessionEnd(); };
}

// ═══════════════════════════════════════════════════════════════════════════
// SESSION
// ═══════════════════════════════════════════════════════════════════════════

async function startSession() {
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
    });
  } catch {
    alert('Microphone access denied. Please allow microphone access and try again.');
    return;
  }
  micCtx = new AudioContext({ sampleRate: 16000 });
  if (micCtx.state === 'suspended') await micCtx.resume();
  try { await micCtx.audioWorklet.addModule('/pcm-processor.js'); }
  catch (err) { console.error('AudioWorklet load failed:', err); return; }

  const micSource = micCtx.createMediaStreamSource(micStream);
  workletNode = new AudioWorkletNode(micCtx, 'pcm-processor');
  micSource.connect(workletNode);
  workletNode.port.onmessage = e => { if (ws && ws.readyState === WebSocket.OPEN) ws.send(e.data); };

  startMicAmp(micStream);
  openWebSocket();
  sessionActive = true;
  micBtn.classList.add('active');
  micBtn.querySelector('.mic-icon').style.display  = 'none';
  micBtn.querySelector('.stop-icon').style.display = '';
  micHint.textContent = 'Session active — tap to stop';
  setStatus('connecting','Connecting…');
}

function stopSession() {
  sessionActive = false;
  if (ws && ws.readyState === WebSocket.OPEN) ws.close();
  ws = null;
  _onSessionEnd();
}

function _onSessionEnd() {
  sessionActive = false;
  if (micStream)   { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
  if (workletNode) { workletNode.disconnect(); workletNode = null; }
  if (micCtx)      { micCtx.close(); micCtx = null; }
  stopMicAmp();
  flushTTS();
  micBtn.classList.remove('active');
  micBtn.querySelector('.mic-icon').style.display  = '';
  micBtn.querySelector('.stop-icon').style.display = 'none';
  micHint.textContent = 'Tap to speak with MAYA';
  setStatus('','Offline');
  if (orb) { orb.setState('idle'); orb.setAmplitude(0); }
}

micBtn.addEventListener('click', async () => {
  if (sessionActive) stopSession(); else await startSession();
});

emergencyCancelBtn.addEventListener('click', () => {
  stopEmergencyAlarm();
  emergencyOverlay.style.display = 'none';
  // Also trigger the server-side cancel so contacts are notified
  fetch('/function', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: 'cancel_emergency', args: {} }),
  }).catch(() => {});
});
settingsBtn.addEventListener('click',  () => { settingsModal.style.display = 'flex'; });
settingsClose.addEventListener('click', () => { settingsModal.style.display = 'none'; });
settingsModal.addEventListener('click', e => { if (e.target === settingsModal) settingsModal.style.display = 'none'; });

async function populateMicDevices() {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const sel = $('micSelect');
    devices.filter(d => d.kind === 'audioinput').forEach(d => {
      const opt = document.createElement('option');
      opt.value = d.deviceId;
      opt.textContent = d.label || `Microphone ${sel.children.length + 1}`;
      sel.appendChild(opt);
    });
  } catch {}
}
populateMicDevices();

window._spCmd = async function(name, args) {
  try {
    const r = await fetch('/function', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, args, function_call_id: 'ui' }),
    });
    const data = await r.json();
    if (data.ui_type === 'spotify' && data.ui_data) {
      const d = data.ui_data;
      const existingCard = cardContainer.querySelector('.sp-now-card');
      if (existingCard && d.action !== 'play') {
        // Update in-place — keeps position in feed, no jump/flash
        window._updateSpotifyCard(existingCard, d);
        // Track changed → old lyrics are stale, remove them
        if (d.action === 'next' || d.action === 'previous') {
          const old = cardContainer.querySelector('.lyrics-card');
          if (old) {
            if (old._lyrRaf) cancelAnimationFrame(old._lyrRaf);
            clearInterval(old._lyrTimer);
            old.remove();
          }
        }
      } else {
        // New play, or no card in view yet — full replace
        showCard('spotify', d, data.result || '');
      }
    } else if (data.ui_type && data.ui_type !== 'none') {
      showCard(data.ui_type, data.ui_data || {}, data.result || '');
    }
  } catch (err) { console.error('Spotify cmd:', err); }
};

// Public demo: say up front what this deployment can and cannot do.
fetch('/config').then(r => r.json()).then(cfg => {
  if (cfg.mode !== 'public') return;
  const note = document.getElementById('demoNote');
  if (!note) return;
  const mins = Math.round((cfg.session_seconds || 180) / 60);
  note.textContent = `Web demo: sessions last ${mins} minutes and nothing you say is kept. Spotify, Telegram, SOS and the motion sensor run on MAYA's home device.`;
  note.hidden = false;
}).catch(() => {});
