/**
 * cards.js — all UI card renderers for MAYA web app
 * Each renderer returns an HTML string and is called with ui_data from the server.
 */

// ── Weather icons map (OpenWeather icon codes) ─────────────────────────────
const _WX_ICON = {
  '01d':'☀️','01n':'🌙','02d':'⛅','02n':'🌥️',
  '03d':'☁️','03n':'☁️','04d':'☁️','04n':'☁️',
  '09d':'🌧️','09n':'🌧️','10d':'🌦️','10n':'🌧️',
  '11d':'⛈️','11n':'⛈️','13d':'❄️','13n':'❄️',
  '50d':'🌫️','50n':'🌫️',
};

// Fallback from condition string
const _COND_ICON = {
  Clear:'☀️', Clouds:'☁️', Rain:'🌧️', Drizzle:'🌦️',
  Thunderstorm:'⛈️', Snow:'❄️', Mist:'🌫️', Fog:'🌫️',
  Haze:'🌫️', Smoke:'🌫️',
};

function _wxIcon(icon, condition) {
  return _WX_ICON[icon] || _COND_ICON[condition] || '🌡️';
}

// ── Mood emoji map ─────────────────────────────────────────────────────────
const _MOOD_EMOJI = {
  happy:'😊', great:'😄', excellent:'🌟', good:'🙂', okay:'😐',
  neutral:'😐', tired:'😴', sad:'😢', anxious:'😰', stressed:'😤',
  angry:'😠', sick:'🤒', energetic:'⚡',
};

// ── Health type config ─────────────────────────────────────────────────────
const _HEALTH_CFG = {
  sleep:      { icon:'💤', color:'var(--accent-purple)', label:'SLEEP LOGGED' },
  water:      { icon:'💧', color:'var(--accent-cyan)',   label:'WATER LOGGED' },
  mood:       { icon:'🧠', color:'var(--accent-green)',  label:'MOOD LOGGED' },
  symptom:    { icon:'🌡️', color:'var(--accent-amber)',  label:'SYMPTOM NOTED' },
  exercise:   { icon:'🏃', color:'var(--accent-green)',  label:'EXERCISE LOGGED' },
  medication: { icon:'💊', color:'var(--accent-pink)',   label:'MEDICATION TAKEN' },
};

// ── Spotify action display ─────────────────────────────────────────────────
const _SP_ACTION = {
  play:        { label:'NOW PLAYING' },
  play_artist: { label:'PLAYING ARTIST' },
  pause:       { label:'PAUSED' },
  resume:      { label:'NOW PLAYING' },
  next:        { label:'NOW PLAYING' },
  previous:    { label:'NOW PLAYING' },
  volume:      { label:'VOLUME' },
  now_playing: { label:'NOW PLAYING' },
};

// ═══════════════════════════════════════════════════════════════════════════
// RENDERERS
// ═══════════════════════════════════════════════════════════════════════════

function renderWeather(d) {
  const icon  = _wxIcon(d.icon, d.condition);
  const city  = (d.city || 'Unknown').toUpperCase();
  const stats = [
    { label:'FEELS LIKE', value: d.feels_like != null ? `${d.feels_like}°` : '—', unit:'' },
    { label:'HUMIDITY',   value: d.humidity  != null ? `${d.humidity}` : '—',    unit:'%' },
    { label:'WIND',       value: d.wind_speed != null ? `${d.wind_speed}` : '—', unit:' m/s' },
    { label:'HI / LO',
      value: (d.temp_max != null && d.temp_min != null) ? `${d.temp_max}° / ${d.temp_min}°` : '—',
      unit: '' },
  ];
  return `
  <div class="ui-card">
    <div class="card-header">
      <span class="card-header-icon">🌤️</span>
      <span class="card-header-title">WEATHER — ${city}</span>
    </div>
    <div class="card-body">
      <div class="weather-main">
        <div>
          <div class="weather-temp">${d.temp != null ? d.temp : '--'}<sup>°C</sup></div>
          <div class="weather-condition">${d.description || d.condition || ''}</div>
        </div>
        <div class="weather-icon">${icon}</div>
      </div>
      <div class="weather-stats">
        ${stats.map(s => `
          <div class="weather-stat">
            <div class="stat-label">${s.label}</div>
            <div class="stat-value">${s.value}<span class="stat-unit">${s.unit}</span></div>
          </div>`).join('')}
      </div>
    </div>
  </div>`;
}

// ── Catmull-Rom → cubic bezier smooth path ────────────────────────────────
function _smoothPath(pts) {
  if (!pts.length) return '';
  if (pts.length === 1) return `M ${pts[0].x.toFixed(1)} ${pts[0].y.toFixed(1)}`;
  let d = `M ${pts[0].x.toFixed(1)} ${pts[0].y.toFixed(1)}`;
  const T = 0.26; // tension
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[Math.min(pts.length - 1, i + 2)];
    const cp1x = p1.x + (p2.x - p0.x) * T;
    const cp1y = p1.y + (p2.y - p0.y) * T;
    const cp2x = p2.x - (p3.x - p1.x) * T;
    const cp2y = p2.y - (p3.y - p1.y) * T;
    d += ` C ${cp1x.toFixed(1)} ${cp1y.toFixed(1)},${cp2x.toFixed(1)} ${cp2y.toFixed(1)},${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`;
  }
  return d;
}

function renderForecast(d) {
  const requested = d.requested_days ? Math.min(Math.max(1, d.requested_days), 5) : 5;
  const days = (Array.isArray(d.days) ? d.days : []).slice(0, requested);
  const city = (d.city || 'Unknown').toUpperCase();
  const country = d.country || '';
  const dayLabel = days.length === 1 ? '1-DAY' : `${days.length}-DAY`;

  // ── fallback ──────────────────────────────────────────────────────────────
  if (!days.length) return `
  <div class="ui-card"><div class="card-header">
    <span class="card-header-icon">📅</span>
    <span class="card-header-title">FORECAST — ${city}</span>
  </div><div class="card-body"><p style="color:var(--text-2);font-size:13px">${d.text||'No forecast data available.'}</p></div></div>`;

  // ── day columns ───────────────────────────────────────────────────────────
  const cols = days.map(day => {
    const icon  = _wxIcon(day.icon, day.condition);
    const rain  = day.rain_chance || 0;
    const rainColor = rain > 60 ? 'var(--blue)' : rain > 30 ? 'var(--cyan)' : 'var(--text-3)';
    return `
    <div class="fc-day${day.is_today ? ' fc-today' : ''}">
      <div class="fc-day-name">${day.is_today ? 'TODAY' : day.day_short}</div>
      <div class="fc-day-icon">${icon}</div>
      <div class="fc-desc">${(day.description||'').replace(/ /g,'&nbsp;')}</div>
      <div class="fc-temps">
        <span class="fc-hi">${Math.round(day.temp_max)}°</span>
        <span class="fc-temp-sep">/</span>
        <span class="fc-lo">${Math.round(day.temp_min)}°</span>
      </div>
      <div class="fc-rain-wrap">
        <div class="fc-rain-bar">
          <div class="fc-rain-fill" style="width:${rain}%;background:${rainColor}"></div>
        </div>
        <span class="fc-rain-pct" style="color:${rainColor}">${rain}%</span>
      </div>
      <div class="fc-wind">💨 ${day.wind_speed}m/s</div>
    </div>`;
  }).join('');

  // ── SVG trend chart ───────────────────────────────────────────────────────
  const W = 272, CHART_TOP = 16, CHART_H = 58, TOTAL_H = CHART_TOP + CHART_H + 2;
  const PAD = 26;
  const n   = days.length;
  const xs  = days.map((_, i) => PAD + (n > 1 ? (i / (n - 1)) * (W - PAD * 2) : (W - PAD * 2) / 2));

  const allT  = days.flatMap(day => [day.temp_max, day.temp_min]);
  const tMin  = Math.min(...allT) - 2;
  const tMax  = Math.max(...allT) + 2;
  const tRng  = tMax - tMin || 1;
  const yOf   = t => CHART_TOP + (1 - (t - tMin) / tRng) * CHART_H;

  const hiPts = days.map((day, i) => ({ x: xs[i], y: yOf(day.temp_max) }));
  const loPts = days.map((day, i) => ({ x: xs[i], y: yOf(day.temp_min) }));

  const hiPath  = _smoothPath(hiPts);
  const loPath  = _smoothPath(loPts);
  // area fill: hi curve forward + lo straight lines backward
  const areaPath = hiPath
    + ` L ${loPts[n-1].x.toFixed(1)} ${loPts[n-1].y.toFixed(1)}`
    + loPts.slice(0,-1).reverse().map(p => ` L ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join('')
    + ' Z';

  // grid lines
  const gridStep  = Math.max(1, Math.ceil(tRng / 3));
  const gridStart = Math.ceil(tMin / gridStep) * gridStep;
  let gridLines   = '';
  for (let t = gridStart; t <= tMax; t += gridStep) {
    const y = yOf(t).toFixed(1);
    gridLines += `<line x1="${PAD-4}" y1="${y}" x2="${W-PAD+4}" y2="${y}" stroke="rgba(255,255,255,0.05)" stroke-width="0.6"/>
    <text x="${PAD-6}" y="${(+y+3.5).toFixed(1)}" fill="rgba(255,255,255,0.18)" font-size="6.5" text-anchor="end" font-family="Orbitron,monospace">${Math.round(t)}°</text>`;
  }

  // dots + labels
  const hiDots = hiPts.map((p, i) => `
    <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="3" fill="#00d4ff" opacity="0.9"/>
    <text x="${p.x.toFixed(1)}" y="${(p.y - 6).toFixed(1)}" fill="#00d4ff" font-size="7.5" text-anchor="middle" font-family="Orbitron,monospace" font-weight="700">${Math.round(days[i].temp_max)}°</text>`).join('');

  const loDots = loPts.map((p, i) => `
    <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="3" fill="#9b5fff" opacity="0.9"/>
    <text x="${p.x.toFixed(1)}" y="${(p.y + 13).toFixed(1)}" fill="#9b5fff" font-size="7.5" text-anchor="middle" font-family="Orbitron,monospace" font-weight="700">${Math.round(days[i].temp_min)}°</text>`).join('');

  const svg = `
  <svg viewBox="0 0 ${W} ${TOTAL_H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;display:block;overflow:visible">
    <defs>
      <linearGradient id="fcAreaGrad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#00d4ff" stop-opacity="0.18"/>
        <stop offset="100%" stop-color="#7b2fff" stop-opacity="0.06"/>
      </linearGradient>
      <linearGradient id="fcHiGrad" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" stop-color="#00d4ff"/><stop offset="100%" stop-color="#00ffcc"/>
      </linearGradient>
      <linearGradient id="fcLoGrad" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" stop-color="#7b2fff"/><stop offset="100%" stop-color="#ff2dce"/>
      </linearGradient>
      <filter id="fcGlow"><feGaussianBlur stdDeviation="1.8" result="b"/>
        <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    </defs>
    ${gridLines}
    <path d="${areaPath}" fill="url(#fcAreaGrad)"/>
    <path d="${hiPath}" stroke="url(#fcHiGrad)" stroke-width="1.8" fill="none" filter="url(#fcGlow)"/>
    <path d="${loPath}" stroke="url(#fcLoGrad)" stroke-width="1.8" fill="none" filter="url(#fcGlow)"/>
    ${hiDots}${loDots}
  </svg>`;

  return `
  <div class="ui-card forecast-card">
    <div class="card-header">
      <span class="card-header-icon">🌤️</span>
      <span class="card-header-title">${dayLabel} FORECAST &mdash; ${city}${country ? ' &middot; ' + country : ''}</span>
    </div>
    <div class="card-body" style="padding:12px 10px">
      <div class="forecast-days">${cols}</div>
      ${days.length > 1 ? `
      <div class="fc-chart-section">
        <div class="fc-chart-legend">
          <span class="fc-leg fc-leg-hi">&#9644; HIGH</span>
          <span class="fc-leg fc-leg-lo">&#9644; LOW</span>
          <span class="fc-leg-label">TEMPERATURE TREND</span>
        </div>
        <div class="fc-chart-body">${svg}</div>
      </div>` : ''}
    </div>
  </div>`;
}

function renderHealthLog(d) {
  const cfg   = _HEALTH_CFG[d.type] || { icon:'❤️', color:'var(--accent-green)', label:'HEALTH LOG' };
  let detail  = '';

  if (d.type === 'sleep') {
    detail = `
      <div class="health-log-value" style="color:${cfg.color}">${d.hours}h</div>
      <div class="health-log-label">Quality: ${d.quality || 'fair'}</div>
      ${d.avg_7d != null ? `<div class="health-log-label" style="margin-top:4px;font-size:11px;color:var(--text-muted)">7-day avg: ${d.avg_7d}h</div>` : ''}`;
  } else if (d.type === 'water') {
    const pct = Math.min(100, Math.round((d.glasses / (d.goal || 8)) * 100));
    detail = `
      <div class="health-log-value" style="color:${cfg.color}">${d.glasses} <span style="font-size:16px">/ ${d.goal || 8}</span></div>
      <div class="health-log-label">glasses today</div>
      <div class="water-bar"><div class="water-fill" style="width:${pct}%"></div></div>
      <div class="water-labels"><span>0</span><span>${d.goal || 8} goal</span></div>`;
  } else if (d.type === 'mood') {
    const emoji = _MOOD_EMOJI[d.mood?.toLowerCase()] || '🧠';
    detail = `
      <div class="health-log-value" style="font-size:40px">${emoji}</div>
      <div class="health-log-value" style="color:${cfg.color};font-size:20px;margin-top:4px">${d.mood || ''}</div>
      ${d.score != null ? `<div class="health-log-label">Score: ${d.score}/10</div>` : ''}`;
  } else if (d.type === 'exercise') {
    detail = `
      <div class="health-log-value" style="color:${cfg.color}">${d.minutes}m</div>
      <div class="health-log-label">${d.activity || ''}</div>`;
  } else if (d.type === 'symptom') {
    const sevColor = d.severity >= 7 ? 'var(--accent-red)' : d.severity >= 4 ? 'var(--accent-amber)' : 'var(--accent-green)';
    detail = `
      <div class="health-log-value" style="color:${sevColor}">${d.severity}/10</div>
      <div class="health-log-label">${d.symptom || ''}</div>`;
  } else if (d.type === 'medication') {
    detail = `
      <div class="health-log-value" style="color:${cfg.color}">✓</div>
      <div class="health-log-label">${d.name || ''}</div>`;
  }

  return `
  <div class="ui-card">
    <div class="card-header">
      <span class="card-header-icon">${cfg.icon}</span>
      <span class="card-header-title">${cfg.label}</span>
    </div>
    <div class="card-body">
      <div class="health-log-icon">${cfg.icon}</div>
      <div class="health-log-type">${d.type ? d.type.toUpperCase() : ''}</div>
      ${detail}
    </div>
  </div>`;
}

function renderHealthSummary(d) {
  const rows = [
    { label:'SLEEP',    value: d.sleep_hours != null ? `${d.sleep_hours}h (${d.sleep_quality||'—'})` : '—' },
    { label:'WATER',    value: `${d.water_glasses||0} / ${d.water_goal||8} glasses` },
    { label:'MOOD',     value: d.mood || '—' },
    { label:'EXERCISE', value: d.exercise_mins ? `${d.exercise_mins} min` : '—' },
  ];
  const meds = (d.meds_taken || []).join(', ') || 'None';
  return `
  <div class="ui-card">
    <div class="card-header">
      <span class="card-header-icon">📊</span>
      <span class="card-header-title">HEALTH SUMMARY</span>
    </div>
    <div class="card-body">
      <div class="summary-grid">
        ${rows.map(r => `
          <div class="summary-stat">
            <div class="summary-stat-value">${r.value}</div>
            <div class="summary-stat-label">${r.label}</div>
          </div>`).join('')}
      </div>
      <div style="margin-top:12px;padding:10px 12px;background:rgba(0,0,0,0.2);border-radius:8px;border:1px solid var(--border)">
        <div class="stat-label" style="margin-bottom:4px">MEDICATIONS TODAY</div>
        <div style="font-size:13px;color:var(--text-secondary)">${meds}</div>
      </div>
    </div>
  </div>`;
}

function renderWellnessScore(d) {
  const score  = d.score || 0;
  const r      = 46;
  const circ   = 2 * Math.PI * r;
  const offset = circ - (score / 100) * circ;
  const color  = score >= 75 ? 'var(--accent-green)' : score >= 50 ? 'var(--accent-amber)' : 'var(--accent-red)';
  const label  = score >= 80 ? 'Excellent' : score >= 60 ? 'Good' : score >= 40 ? 'Fair' : 'Needs attention';
  return `
  <div class="ui-card">
    <div class="card-header">
      <span class="card-header-icon">⚡</span>
      <span class="card-header-title">WELLNESS SCORE</span>
    </div>
    <div class="card-body" style="text-align:center">
      <div class="wellness-ring-container">
        <svg width="120" height="120" viewBox="0 0 120 120">
          <circle class="wellness-ring-bg"  cx="60" cy="60" r="${r}" stroke-width="8"/>
          <circle class="wellness-ring-arc" cx="60" cy="60" r="${r}" stroke-width="8"
            stroke="${color}"
            stroke-dasharray="${circ}"
            stroke-dashoffset="${offset}"
            style="transition:stroke-dashoffset 1.2s cubic-bezier(0.4,0,0.2,1)"/>
        </svg>
        <div class="wellness-score-num">
          <span class="wellness-num" style="color:${color}">${score}</span>
          <span class="wellness-max">/100</span>
        </div>
      </div>
      <div style="font-family:var(--font-display);font-size:11px;letter-spacing:2px;color:${color};margin-top:6px">${label.toUpperCase()}</div>
    </div>
  </div>`;
}

function renderAlarms(d) {
  const alarms   = d.alarms || [];
  const newAlarm = d.new;
  if (!alarms.length) {
    return `
    <div class="ui-card">
      <div class="card-header"><span class="card-header-icon">&#9200;</span><span class="card-header-title">ALARMS</span></div>
      <div class="card-body"><div style="color:var(--text-muted);font-size:12px;text-align:center;padding:20px 16px">
        No alarms set.<br><span style="font-size:11px;opacity:.6">Say "Set an alarm for 7 AM"</span>
      </div></div>
    </div>`;
  }

  const items = alarms.map(a => {
    const isNew   = newAlarm && (a.time === newAlarm.time || a.time_12h === newAlarm.time);
    const when    = a.when || '';
    const isToday = when === 'Today';
    const note    = a.note || a.description || a.label || '';
    const mins    = a.minutes_away;
    let timeAway  = '';
    if (mins != null) {
      if (mins < 60) timeAway = `in ${mins} min`;
      else { const h = Math.floor(mins/60), m = mins%60; timeAway = m ? `in ${h}h ${m}m` : `in ${h}h`; }
    }
    return `
    <div class="alarm-row${isNew ? ' alarm-row-new' : ''}">
      <div class="alb ${isToday ? 'alb-today' : 'alb-future'}">${when || 'SET'}</div>
      <div class="alarm-row-time">${a.time_12h || a.time || '&mdash;'}</div>
      <div class="alarm-row-right">
        ${note ? `<div class="alarm-row-note">${note}</div>` : ''}
        ${timeAway ? `<div class="alarm-row-away">${timeAway}</div>` : ''}
        ${a.created_at ? `<div class="alarm-row-set">Set ${_fmtCreated(a.created_at)}</div>` : ''}
      </div>
    </div>`;
  }).join('');

  return `
  <div class="ui-card">
    <div class="card-header">
      <span class="card-header-icon">&#9200;</span>
      <span class="card-header-title">ALARMS &mdash; ${alarms.length} SET</span>
    </div>
    <div class="card-body" style="padding:10px 12px">
      <div class="alarm-list-v2">${items}</div>
    </div>
  </div>`;
}

function renderReminderDue(d) {
  const esc = s => String(s || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  return `
    <div class="ui-card reminder-due-card">
      <div class="card-header"><span class="card-header-icon">&#128276;</span><span class="card-header-title">REMINDER</span><span class="reminder-due-time">${esc(d.time)}</span></div>
      <div class="card-body">
        <div class="reminder-due-text">${esc(d.message)}</div>
        <div class="reminder-due-hint">Say "done" or "stop the reminder" to dismiss</div>
      </div>
    </div>`;
}

function renderReminders(d) {
  const reminders = d.reminders || [];
  const newR      = d.task ? d : null;
  if (!reminders.length && !newR) {
    return `
    <div class="ui-card">
      <div class="card-header"><span class="card-header-icon">&#128221;</span><span class="card-header-title">REMINDERS</span></div>
      <div class="card-body"><div style="color:var(--text-muted);font-size:12px;text-align:center;padding:20px 16px">
        No reminders set.<br><span style="font-size:11px;opacity:.6">Say "Remind me to..."</span>
      </div></div>
    </div>`;
  }
  return `
  <div class="ui-card">
    <div class="card-header">
      <span class="card-header-icon">&#128221;</span>
      <span class="card-header-title">REMINDERS</span>
    </div>
    <div class="card-body">
      <div class="reminder-list">
        ${reminders.map(r => {
          const done    = r.done || false;
          const overdue = r.is_past && !done;
          const dotCls  = done ? 'dot-done' : overdue ? 'dot-overdue' : '';
          const rowCls  = done ? 'reminder-done-row' : overdue ? 'reminder-overdue-row' : '';
          const lbl     = r.when_label || r.datetime || '';
          return `
          <div class="reminder-item ${rowCls}">
            <div class="reminder-dot ${dotCls}"></div>
            <div style="flex:1;min-width:0">
              <div class="reminder-task">${r.message || r.task || r.description || '&mdash;'}</div>
              ${lbl ? `<div class="reminder-time">${lbl}</div>` : ''}
            </div>
            ${done ? '<span class="rem-badge done-badge">DONE</span>' : overdue ? '<span class="rem-badge overdue-badge">OVERDUE</span>' : ''}
          </div>`; }).join('')}
        ${newR ? `
          <div class="reminder-item">
            <div class="reminder-dot" style="background:var(--green)"></div>
            <div>
              <div class="reminder-task">&#10003; ${newR.task}</div>
              ${newR.time ? `<div class="reminder-time">${newR.time}</div>` : ''}
            </div>
          </div>` : ''}
      </div>
    </div>
  </div>`;
}

function renderSpotify(d) {
  const cfg        = _SP_ACTION[d.action] || { label:'SPOTIFY' };
  const dispTrack  = d.track  || d.query || d.artist || '';
  const dispArtist = d.artist || '';
  const isPlay     = ['play','now_playing','resume','next','previous'].includes(d.action);
  const canLyrics  = !!dispTrack && isPlay;
  const safeT      = dispTrack.replace(/"/g,'&quot;');
  const safeA      = dispArtist.replace(/"/g,'&quot;');
  return `
  <div class="ui-card sp-now-card" data-sp-track="${safeT}" data-sp-artist="${safeA}">
    <div class="sp-now-header">
      <span class="sp-now-label">${cfg.label}</span>
      <div class="sp-soundbars${isPlay?'':' sp-soundbars--paused'}" aria-hidden="true">
        <span></span><span></span><span></span><span></span><span></span>
      </div>
    </div>
    <div class="sp-vinyl-wrap">
      <div class="sp-vinyl${isPlay?' sp-vinyl--spin':''}">
        <div class="sp-vinyl-groove"></div>
        <div class="sp-vinyl-center"></div>
      </div>
      <div class="sp-track-info">
        ${dispTrack  ? `<div class="sp-track-name">${dispTrack}</div>` : ''}
        ${dispArtist ? `<div class="sp-track-artist">${dispArtist}</div>` : ''}
        ${d.action==='volume' ? `<div class="sp-vol-bar"><div class="sp-vol-fill" style="width:${d.percent||50}%"></div></div>` : ''}
        ${d.action==='now_playing'&&!dispTrack ? `<div class="sp-track-artist" style="opacity:.35">Nothing playing</div>` : ''}
      </div>
    </div>
    <div class="sp-controls">
      <button class="sp-ctrl-btn" data-sp="previous_track" title="Previous">⏮</button>
      <button class="sp-ctrl-btn" data-sp="pause_spotify"  title="Pause">⏸</button>
      <button class="sp-ctrl-btn sp-ctrl-btn--play" data-sp="resume_spotify" title="Play">▶</button>
      <button class="sp-ctrl-btn" data-sp="skip_track"     title="Next">⏭</button>
    </div>
    ${canLyrics ? `
    <div class="sp-lyrics-row">
      <button class="sp-lyrics-btn" data-action="lyrics">♪ Show Lyrics</button>
    </div>` : ''}
  </div>`;
}

// In-place update of existing Spotify card — used by control buttons
window._updateSpotifyCard = function(card, d) {
  const isPlay = ['play','now_playing','resume','next','previous'].includes(d.action);
  const track  = d.track  || d.query || '';
  const artist = d.artist || '';

  // Update data attrs so lyrics lookup stays accurate
  if (track)  card.dataset.spTrack  = track;
  if (artist) card.dataset.spArtist = artist;

  // Label
  const cfg     = _SP_ACTION[d.action] || {};
  const labelEl = card.querySelector('.sp-now-label');
  if (labelEl && cfg.label) labelEl.textContent = cfg.label;

  // Soundbars — animated when playing, frozen when paused
  const bars = card.querySelector('.sp-soundbars');
  if (bars) bars.classList.toggle('sp-soundbars--paused', !isPlay);

  // Vinyl spin
  const vinyl = card.querySelector('.sp-vinyl');
  if (vinyl) vinyl.classList.toggle('sp-vinyl--spin', isPlay);

  // Track name + artist (only overwrite if server returned them)
  if (track) {
    const nameEl = card.querySelector('.sp-track-name');
    if (nameEl) nameEl.textContent = track;
    else {
      const info = card.querySelector('.sp-track-info');
      if (info) {
        const el = document.createElement('div');
        el.className = 'sp-track-name'; el.textContent = track;
        info.prepend(el);
      }
    }
  }
  if (artist) {
    const artistEl = card.querySelector('.sp-track-artist');
    if (artistEl) artistEl.textContent = artist;
    else if (track) {
      const info = card.querySelector('.sp-track-info');
      if (info) {
        const el = document.createElement('div');
        el.className = 'sp-track-artist'; el.textContent = artist;
        info.appendChild(el);
      }
    }
  }

  // Volume bar — show briefly then fade out
  if (d.action === 'volume' && d.percent != null) {
    let volBar = card.querySelector('.sp-vol-bar');
    if (!volBar) {
      const info = card.querySelector('.sp-track-info');
      volBar = document.createElement('div');
      volBar.className = 'sp-vol-bar';
      if (info) info.appendChild(volBar);
    }
    volBar.innerHTML = `<div class="sp-vol-fill" style="width:${d.percent}%"></div>`;
    clearTimeout(volBar._hideTimer);
    volBar._hideTimer = setTimeout(() => {
      volBar.style.transition = 'opacity .8s'; volBar.style.opacity = '0';
      setTimeout(() => { if (volBar.parentNode) volBar.remove(); }, 800);
    }, 2500);
  }

  // Ensure lyrics button exists when track info is available
  const canLyrics = !!track && isPlay;
  let lyrRow = card.querySelector('.sp-lyrics-row');
  if (canLyrics && !lyrRow) {
    lyrRow = document.createElement('div');
    lyrRow.className = 'sp-lyrics-row';
    lyrRow.innerHTML = '<button class="sp-lyrics-btn" data-action="lyrics">♪ Show Lyrics</button>';
    card.appendChild(lyrRow);
  }
};

// ── Lyrics card ───────────────────────────────────────────────────────────────
function renderLyricsCard(data) {
  if (!data.found) {
    return `
    <div class="ui-card lyrics-card">
      <div class="lyr-header">
        <div class="lyr-header-track">LYRICS</div>
        <div class="lyr-header-artist">Not available for this track</div>
      </div>
      <div style="text-align:center;padding:32px 16px">
        <div style="font-size:32px;margin-bottom:10px">🎵</div>
        <div class="lyrics-not-found">Couldn't find lyrics for this track</div>
      </div>
    </div>`;
  }

  let stanzas; // array of arrays of {text, idx}
  let totalLines = 0;

  if (data.lrc_lines && data.lrc_lines.length) {
    // ── LRC path: group by time gaps > 3 s ──────────────────────────────────
    const lrc = data.lrc_lines;
    const groups = [];
    let cur = [];
    for (let i = 0; i < lrc.length; i++) {
      cur.push({ text: lrc[i].text, idx: totalLines++ });
      const gap = i < lrc.length - 1 ? lrc[i + 1].ms - lrc[i].ms : 0;
      if (gap > 3000) { groups.push(cur); cur = []; }
    }
    if (cur.length) groups.push(cur);
    stanzas = groups;
  } else {
    // ── Plain text path: group by blank lines ───────────────────────────────
    const lines = data.lyrics
      .replace(/\r\n/g, '\n').replace(/\r/g, '\n')
      .split('\n').map(l => l.trim());
    const groups = [];
    let cur = [];
    for (const l of lines) {
      if (l === '') { if (cur.length) { groups.push(cur); cur = []; } }
      else cur.push({ text: l, idx: totalLines++ });
    }
    if (cur.length) groups.push(cur);
    stanzas = groups;
  }

  const stanzaHTML = stanzas.map(stanza =>
    `<div class="lyrics-stanza">${stanza.map(({text, idx}) => {
      const delay = Math.min(idx * 35, 2000);
      return `<div class="lyrics-line" data-lyr-idx="${idx}" style="animation-delay:${delay}ms" data-action="lyrics-jump">${text}</div>`;
    }).join('')}</div>`
  ).join('');

  const hasLrc = !!(data.lrc_lines && data.lrc_lines.length);
  return `
  <div class="ui-card lyrics-card${hasLrc ? ' lyrics-card--lrc' : ''}">
    <div class="lyr-header">
      <div class="lyr-header-top">
        <span class="lyr-icon">🎤</span>
        <div>
          <div class="lyr-header-track">${data.track}</div>
          <div class="lyr-header-artist">${data.artist}</div>
        </div>
        ${hasLrc ? '<span class="lyr-sync-badge">SYNCED</span>' : ''}
      </div>
    </div>
    <div class="lyrics-scroll-body">
      ${stanzaHTML}
    </div>
  </div>`;
}

// Called when user clicks "Show Lyrics" on a Spotify card
window._loadLyrics = async function(btn) {
  btn.disabled = true;
  btn.textContent = '♪ Loading…';
  const fetchStart = Date.now();
  try {
    const spotifyCard = btn.closest('.ui-card');
    const title  = spotifyCard?.dataset?.spTrack  || '';
    const artist = spotifyCard?.dataset?.spArtist || '';
    const params = new URLSearchParams();
    if (title)  params.set('title',  title);
    if (artist) params.set('artist', artist);
    const r    = await fetch('/lyrics?' + params.toString());
    const data = await r.json();
    // Compensate for fetch + parse latency so glow starts in sync
    const fetchElapsed  = Date.now() - fetchStart;
    const adjustedProgress = (data.progress_ms || 0) + fetchElapsed;

    const html     = renderLyricsCard(data);
    const tmp      = document.createElement('div');
    tmp.innerHTML  = html.trim();
    const lyricsEl = tmp.firstElementChild;
    // Attach LRC data as a JS property (not serialized into DOM)
    if (data.lrc_lines) lyricsEl._lrcLines = data.lrc_lines;

    if (spotifyCard && spotifyCard.parentNode) {
      const next = spotifyCard.nextElementSibling;
      if (next && next.classList.contains('lyrics-card')) {
        if (next._lyrRaf)    cancelAnimationFrame(next._lyrRaf);
        if (next._lyrTimers) next._lyrTimers.forEach(clearTimeout);
        clearInterval(next._lyrTimer);
        next.remove();
      }
      spotifyCard.parentNode.insertBefore(lyricsEl, spotifyCard.nextSibling);
      lyricsEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
      if (data.found) _startLyricsGlow(lyricsEl, adjustedProgress);
    }
    btn.textContent = '♪ Lyrics';
    btn.disabled    = false;
  } catch(e) {
    console.error('loadLyrics', e);
    btn.textContent = '♪ Failed';
    btn.disabled    = false;
  }
};

// ── Lyrics glow engine ────────────────────────────────────────────────────────
function _setLyricsActive(card, idx) {
  const all = card.querySelectorAll('.lyrics-line');
  all.forEach((el, i) => {
    el.classList.remove('lyr-active', 'lyr-past', 'lyr-upcoming');
    if (idx < 0) return;  // instrumental intro — all lines dim
    if      (i < idx)      el.classList.add('lyr-past');
    else if (i === idx)    el.classList.add('lyr-active');
    else if (i <= idx + 3) el.classList.add('lyr-upcoming');
  });
  if (idx < 0) return;
  const active = card.querySelector('.lyrics-line.lyr-active');
  if (active) {
    const body = card.querySelector('.lyrics-scroll-body');
    const target = active.offsetTop - body.clientHeight / 2 + active.offsetHeight / 2;
    body.scrollTo({ top: Math.max(0, target), behavior: 'smooth' });
  }
}

// Fallback: dumb interval for plain-text lyrics (no timestamps)
function _autoGlow(card) {
  clearInterval(card._lyrTimer);
  const all = card.querySelectorAll('.lyrics-line');
  if (!all.length) return;
  const ms = Math.max(2400, Math.min(5000, Math.round(3.2 * 60 * 1000 / all.length)));
  card._lyrTimer = setInterval(() => {
    if (!document.contains(card)) { clearInterval(card._lyrTimer); return; }
    card._lyrIdx = (card._lyrIdx || 0) + 1;
    if (card._lyrIdx >= all.length) { clearInterval(card._lyrTimer); return; }
    _setLyricsActive(card, card._lyrIdx);
  }, ms);
}

function _startLyricsGlow(card, adjustedProgressMs) {
  const lrcLines = card._lrcLines;
  card._lyrPaused = false;

  if (lrcLines && lrcLines.length) {
    // ── LRC mode: requestAnimationFrame continuous loop ────────────────────
    // Stores reference point: at wall-clock time _lyrStartTime, the song was at _lyrProgressMs.
    // Every frame we compute currentMs = _lyrProgressMs + (performance.now() - _lyrStartTime)
    // and find which LRC line matches. Self-corrects jitter; naturally handles:
    //   • instrumental intros  → no line highlighted until currentMs >= lrcLines[0].ms
    //   • mid-song instrumentals → highlighted line stays until next LRC timestamp arrives
    card._lyrProgressMs  = adjustedProgressMs || 0;
    card._lyrStartTime   = performance.now();
    card._lyrCurrentIdx  = -2;  // sentinel: forces a render on first tick

    // Cancel any previous RAF loop or stale timers
    if (card._lyrRaf)    cancelAnimationFrame(card._lyrRaf);
    if (card._lyrTimers) { card._lyrTimers.forEach(clearTimeout); card._lyrTimers = []; }

    function lrcTick() {
      if (!document.contains(card)) return;  // card removed — stop loop
      if (!card._lyrPaused) {
        const currentMs = card._lyrProgressMs + (performance.now() - card._lyrStartTime);
        // Find the last line whose timestamp ≤ currentMs
        let curIdx = -1;
        for (let i = 0; i < lrcLines.length; i++) {
          if (lrcLines[i].ms <= currentMs) curIdx = i; else break;
        }
        if (curIdx !== card._lyrCurrentIdx) {
          card._lyrCurrentIdx = curIdx;
          card._lyrIdx = Math.max(0, curIdx);
          _setLyricsActive(card, curIdx);
        }
      }
      card._lyrRaf = requestAnimationFrame(lrcTick);
    }

    card._lyrRaf = requestAnimationFrame(lrcTick);

    // Hover: freeze the visual; RAF keeps tracking internally
    card.addEventListener('mouseenter', () => { card._lyrPaused = true; });
    card.addEventListener('mouseleave', () => {
      card._lyrPaused = false;
      if (document.contains(card)) _setLyricsActive(card, card._lyrCurrentIdx);
    });

  } else {
    // ── Plain text fallback: interval-based ───────────────────────────────
    const all = card.querySelectorAll('.lyrics-line');
    if (!all.length) return;
    const entryMs = Math.min(all.length * 35 + 500, 2500);
    setTimeout(() => {
      if (!document.contains(card)) return;
      card._lyrIdx = 0;
      _setLyricsActive(card, 0);
      _autoGlow(card);
    }, entryMs);
    card.addEventListener('mouseenter', () => clearInterval(card._lyrTimer));
    card.addEventListener('mouseleave', () => {
      if (document.contains(card)) _autoGlow(card);
    });
  }
}

// Click any line to scroll to it (LRC mode: RAF continues syncing; plain mode: jumps to that line)
window._lyricsJump = function(lineEl) {
  const card = lineEl.closest('.lyrics-card');
  if (!card) return;
  const idx = parseInt(lineEl.dataset.lyrIdx, 10);

  if (card._lrcLines) {
    // LRC mode — just scroll to that line; the RAF loop keeps driving real sync
    const body = card.querySelector('.lyrics-scroll-body');
    if (body) body.scrollTo({
      top: Math.max(0, lineEl.offsetTop - body.clientHeight / 2 + lineEl.offsetHeight / 2),
      behavior: 'smooth'
    });
  } else {
    // Plain text fallback — jump and re-anchor the interval timer
    clearInterval(card._lyrTimer);
    _autoGlow(card);
  }
};

function renderNews(d) {
  const topic = d.topic ? d.topic.toUpperCase() : 'HEALTH NEWS';
  return `
  <div class="ui-card">
    <div class="card-header">
      <span class="card-header-icon">📰</span>
      <span class="card-header-title">${topic}</span>
    </div>
    <div class="card-body">
      <div class="news-text">${(d.text || '').trim()}</div>
    </div>
  </div>`;
}

function renderMotion(d) {
  const active = d.active;
  const statusText = active ? 'MONITORING ACTIVE' : 'MONITORING INACTIVE';
  return `
  <div class="ui-card">
    <div class="card-header">
      <span class="card-header-icon">📡</span>
      <span class="card-header-title">MOTION SENSOR</span>
    </div>
    <div class="card-body">
      <div class="motion-status-indicator">
        <div class="motion-led ${active ? 'active' : 'inactive'}"></div>
        <span class="motion-status-text">${statusText}</span>
      </div>
      ${d.text ? `<div style="font-size:12px;color:var(--text-muted);text-align:center;margin-top:8px">${d.text}</div>` : ''}
      ${d.cooldown != null ? `<div style="font-size:11px;color:var(--text-muted);text-align:center;margin-top:4px">Cooldown: ${d.cooldown}s</div>` : ''}
    </div>
  </div>`;
}

function renderEmergencyCard(d) {
  return d.active
    ? `<div class="ui-card" style="border-color:rgba(255,58,58,0.5)">
         <div class="card-header" style="background:rgba(255,58,58,0.1)">
           <span class="card-header-icon">🚨</span>
           <span class="card-header-title" style="color:var(--accent-red)">SOS ALERT ACTIVE</span>
         </div>
         <div class="card-body" style="text-align:center;padding:20px">
           <div style="font-size:48px;margin-bottom:10px">🚨</div>
           <div style="font-family:var(--font-display);color:var(--accent-red);letter-spacing:2px;font-size:12px">EMERGENCY TRIGGERED</div>
           <div style="font-size:12px;color:var(--text-secondary);margin-top:8px">Contacts are being notified.</div>
         </div>
       </div>`
    : `<div class="ui-card" style="border-color:rgba(0,255,157,0.3)">
         <div class="card-header">
           <span class="card-header-icon">✅</span>
           <span class="card-header-title" style="color:var(--accent-green)">EMERGENCY CANCELLED</span>
         </div>
         <div class="card-body" style="text-align:center;padding:20px">
           <div style="font-size:40px;margin-bottom:8px">✅</div>
           <div style="font-family:var(--font-display);color:var(--accent-green);letter-spacing:2px;font-size:12px">ALL CLEAR</div>
         </div>
       </div>`;
}

function renderTelegram(d) {
  const esc    = s => String(s || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const icon   = d.sent ? '✅' : '⚠️';
  const label  = d.type === 'health_report' ? 'Health report sent via Telegram' : (d.message ? `"${esc(d.message)}"` : 'Message sent');
  const to     = d.to ? `<div class="telegram-to">${d.sent ? 'Sent to' : 'Not sent to'} ${esc(d.to)}</div>` : '';
  return `
  <div class="ui-card">
    <div class="card-header">
      <span class="card-header-icon">✈️</span>
      <span class="card-header-title">TELEGRAM</span>
    </div>
    <div class="card-body">
      <div class="telegram-sent">
        <div class="telegram-check">${icon}</div>
        <div class="telegram-msg-text">${label}</div>
      </div>
      ${to}
    </div>
  </div>`;
}

function renderTime(d) {
  return `
  <div class="ui-card">
    <div class="card-header">
      <span class="card-header-icon">🕐</span>
      <span class="card-header-title">CURRENT TIME</span>
    </div>
    <div class="card-body">
      <div class="time-display">${d.time || '--:-- AM'}</div>
    </div>
  </div>`;
}

function renderDate(d) {
  return `
  <div class="ui-card">
    <div class="card-header">
      <span class="card-header-icon">📅</span>
      <span class="card-header-title">TODAY</span>
    </div>
    <div class="card-body">
      <div class="date-display">
        <div class="date-weekday">${(d.weekday || '').toUpperCase()}</div>
        <div class="date-full">${d.date || ''}</div>
      </div>
    </div>
  </div>`;
}

function renderText(d) {
  return `
  <div class="ui-card">
    <div class="card-header">
      <span class="card-header-icon">◈</span>
      <span class="card-header-title">MAYA</span>
    </div>
    <div class="card-body">
      <div class="text-card-content">${d.text || ''}</div>
    </div>
  </div>`;
}

// ═══════════════════════════════════════════════════════════════════════════
// MEDICATION CARD
// ═══════════════════════════════════════════════════════════════════════════

function renderMedication(d) {
  // "Not found" or blocked state
  if (!d.found) {
    return `
      <div class="med-card">
        <div class="med-not-found">
          <div class="med-nf-icon">&#128138;</div>
          <div class="med-nf-title">${d.name || 'Medication'}</div>
          <div class="med-nf-body">
            Official database entry not found for this medication. Your MAYA assistant is providing guidance verbally &#8212; please listen carefully.
          </div>
          <div class="med-disclaimer">
            &#9888;&#65039; Always consult your doctor or pharmacist before taking any medication.
          </div>
        </div>
      </div>`;
  }

  // Route badge colour & icon
  const _routeIcon = { oral:'&#128138;', topical:'&#129381;', injection:'&#128140;', inhalation:'&#128168;', ophthalmic:'&#128065;&#65039;', otic:'&#128065;&#65039;' };
  const _routeClr  = { oral:'route-oral', topical:'route-topical', injection:'route-injection', inhalation:'route-inhalation' };
  const routeKey   = (d.route || 'oral').toLowerCase().split(' ')[0];
  const routeIcon  = _routeIcon[routeKey] || '&#128138;';
  const routeCls   = _routeClr[routeKey]  || 'route-oral';

  // Generic name sub-label
  const genericRow = (d.generic_name && d.generic_name !== d.name)
    ? `<div class="med-generic">${d.generic_name}</div>` : '';

  // What it treats
  const indicationsBlock = d.indications ? `
    <div class="med-section">
      <div class="med-section-title">&#128203; WHAT IT TREATS</div>
      <div class="med-section-body">${d.indications}</div>
    </div>` : '';

  // How-to-take steps
  let stepsHtml = '';
  if (d.steps && d.steps.length) {
    const stepItems = d.steps.map((s, i) => `
      <div class="med-step">
        <div class="med-step-num">${i + 1}</div>
        <div class="med-step-text">${s}</div>
      </div>`).join('');
    stepsHtml = `
      <div class="med-section">
        <div class="med-section-title">&#9654;&#65039; HOW TO TAKE</div>
        <div class="med-steps">${stepItems}</div>
      </div>`;
  } else if (d.dosage_raw) {
    stepsHtml = `
      <div class="med-section">
        <div class="med-section-title">&#9654;&#65039; DOSAGE &amp; INSTRUCTIONS</div>
        <div class="med-section-body">${d.dosage_raw}</div>
      </div>`;
  }

  // Warnings block
  const warningsBlock = d.warnings ? `
    <div class="med-warning-box">
      <div class="med-warning-header">&#9888;&#65039; WARNINGS</div>
      <div class="med-warning-body">${d.warnings}</div>
    </div>` : '';

  // Side effects
  const sideBlock = d.side_effects ? `
    <div class="med-section">
      <div class="med-section-title">&#128309; POSSIBLE SIDE EFFECTS</div>
      <div class="med-section-body">${d.side_effects}</div>
    </div>` : '';

  return `
    <div class="med-card">
      <div class="med-identity">
        <div class="med-pill-wrap">
          <div class="med-pill-shape"></div>
        </div>
        <div class="med-names">
          <div class="med-brand">${d.name}</div>
          ${genericRow}
          <div class="med-route-badge ${routeCls}">${routeIcon}&nbsp;${(d.route || 'oral').toUpperCase()}</div>
        </div>
      </div>

      ${indicationsBlock}
      ${stepsHtml}
      ${warningsBlock}
      ${sideBlock}

      <div class="med-disclaimer">
        &#9432; Information sourced from the U.S. FDA drug label database. Always follow your healthcare provider's instructions and read the full package insert.
      </div>
    </div>`;
}

// ═══════════════════════════════════════════════════════════════════════════
// DISPATCHER
// ═══════════════════════════════════════════════════════════════════════════

const _BADGE_MAP = {
  weather:'weather', forecast:'weather',
  health_log:'health', health_summary:'health', wellness_score:'health',
  alarms:'alarm', reminder_set:'reminder', reminders:'reminder', reminder_due:'reminder',
  spotify:'music',
  emergency:'emergency',
  medication:'health',
  time:'default', date:'default',
  motion:'default', telegram:'default', news:'default',
  profile_name:'default',
};

// ── helper: format ISO created_at to friendly short date ─────────────────────
function _fmtCreated(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month:'short', day:'numeric', year:'numeric',
                                             hour:'2-digit', minute:'2-digit' });
  } catch { return iso; }
}

// ── Profile name card ─────────────────────────────────────────────────────────
function renderProfileName(d) {
  const current = d.current_name || '—';
  const history = d.name_history || [];
  const initial = current !== '—' ? current.charAt(0).toUpperCase() : '?';

  const histHTML = history.length
    ? history.slice().reverse().map((h, i) =>
        `<div class="pname-hist-row" style="animation-delay:${i * 60}ms">
           <span class="pname-hist-dot"></span>
           <span class="pname-hist-name">${h.name}</span>
           <span class="pname-hist-date">${h.changed_at || ''}</span>
         </div>`
      ).join('')
    : '';

  return `
  <div class="ui-card pname-card">
    <div class="pname-hero">
      <div class="pname-avatar-ring">
        <div class="pname-avatar">${initial}</div>
      </div>
      <div class="pname-label-sm">YOUR NAME</div>
      <div class="pname-value">${current}</div>
      <div class="pname-tagline">Saved &amp; remembered</div>
    </div>
    ${history.length ? `
    <div class="pname-hist-section">
      <div class="pname-hist-title">
        <span class="pname-hist-icon">⟳</span> Previously known as
      </div>
      ${histHTML}
    </div>` : ''}
  </div>`;
}

function renderCard(uiType, uiData) {
  switch (uiType) {
    case 'weather':        return renderWeather(uiData);
    case 'forecast':       return renderForecast(uiData);
    case 'health_log':     return renderHealthLog(uiData);
    case 'health_summary': return renderHealthSummary(uiData);
    case 'wellness_score': return renderWellnessScore(uiData);
    case 'alarms':         return renderAlarms(uiData);
    case 'alarm_stopped':  return renderText({ text: 'Alarm stopped.' });
    case 'reminders':
    case 'reminder_set':   return renderReminders(uiData);
    case 'reminder_stopped': return renderText({ text: 'Reminder dismissed.' });
    case 'reminder_due':     return renderReminderDue(uiData);
    case 'spotify':        return renderSpotify(uiData);
    case 'news':           return renderNews(uiData);
    case 'motion':         return renderMotion(uiData);
    case 'emergency':      return renderEmergencyCard(uiData);
    case 'telegram':       return renderTelegram(uiData);
    case 'time':           return renderTime(uiData);
    case 'date':           return renderDate(uiData);
    case 'medication':     return renderMedication(uiData);
    case 'profile_name':   return renderProfileName(uiData);
    case 'text':           return renderText(uiData);
    default:               return '';
  }
}

function getCardBadge(uiType) {
  const key = _BADGE_MAP[uiType] || 'default';
  const labels = {
    weather:'WEATHER', health:'HEALTH', alarm:'ALARMS',
    reminder:'REMINDERS', music:'MUSIC', emergency:'SOS',
    default: (uiType || '').toUpperCase().replace(/_/g, ' '),
  };
  return { cls: `badge-${key}`, text: labels[key] || uiType };
}

function getHistoryItem(uiType, uiData, resultText) {
  const icons = {
    weather:'🌤️', forecast:'📅', health_log:'❤️', health_summary:'📊',
    wellness_score:'⚡', alarms:'⏰', reminder_set:'📝', reminders:'📝',
    spotify:'🎵', news:'📰', motion:'📡', emergency:'🚨',
    telegram:'✈️', time:'🕐', date:'📅', text:'◈', medication:'💊',
    profile_name:'👤', reminder_due:'🔔',
  };
  const badgeKey = _BADGE_MAP[uiType] || 'default';
  const icon     = icons[uiType] || '◈';
  const now      = new Date();
  const timeStr  = now.toLocaleTimeString([], { hour:'2-digit', minute:'2-digit' });
  const preview  = (resultText || '').slice(0, 60) + ((resultText||'').length > 60 ? '…' : '');
  return `
    <div class="history-item" data-replay="${uiType}">
      <div><span class="history-item-badge badge-${badgeKey}">${icon} ${badgeKey.toUpperCase()}</span></div>
      <div class="history-item-text">${preview}</div>
      <div class="history-item-time">${timeStr}</div>
    </div>`;
}

window.CardRenderer = { renderCard, getCardBadge, getHistoryItem };

// One delegated listener instead of inline onclick attributes, so the page
// runs under a Content-Security-Policy that forbids inline script.
document.addEventListener('click', e => {
  const el = e.target.closest('[data-sp],[data-action],[data-replay]');
  if (!el) return;
  if (el.dataset.sp) window._spCmd(el.dataset.sp, {});
  else if (el.dataset.replay) window._replayCard(el.dataset.replay, el);
  else if (el.dataset.action === 'lyrics') window._loadLyrics(el);
  else if (el.dataset.action === 'lyrics-jump') window._lyricsJump(el);
});
