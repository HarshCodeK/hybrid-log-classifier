/* Incident Triage Console -- frontend logic.
   ---------------------------------------------------------------------------
   Vanilla ES2020, no dependencies, no build step. The whole UI has eight moving
   parts; a framework would add a toolchain and a second language to learn in
   exchange for nothing.

   The one rule that shapes this file: there is no innerHTML assignment anywhere
   in it. Log lines are attacker-influenced data -- a log message can contain
   anything a user typed -- so every value reaches the DOM through el(), which
   uses textContent. Nothing is ever parsed as HTML.
*/

'use strict';

// ── Helpers ────────────────────────────────────────────────────

/** Tiny DOM builder. Every server value enters the page through here. */
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

/**
 * Clear a node's children.
 *
 * Every `innerHTML` assignment in this file goes through here, and it is always
 * the empty string -- there is no path anywhere in this file that assigns
 * interpolated data to innerHTML. All server values reach the DOM exclusively
 * through el(), which sets textContent. That matters because log lines are
 * attacker-influenced: a log message can contain anything a user typed, so it
 * must never be parsed as HTML.
 *
 * `replaceChildren()` is used instead of `innerHTML = ''` so the intent is
 * visible to the next reader and to any static analysis.
 */
function clear(node) {
  node.replaceChildren();
}

async function api(path, options) {
  const response = await fetch(path, options);
  let body = null;
  try { body = await response.json(); } catch { /* non-JSON error page */ }
  if (!response.ok) {
    const detail = body && body.detail ? body.detail : `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return body;
}

const money = (n) => '$' + Number(n || 0).toFixed(n >= 0.01 ? 3 : 6);

// ── Health ─────────────────────────────────────────────────────

async function loadHealth() {
  const node = document.getElementById('health');
  try {
    const h = await api('/health');
    node.className = 'health ' + (h.llm_available ? 'ok' : 'degraded');
    node.textContent = h.llm_available
      ? `LLM tier ready · ${h.model}`
      : 'LLM tier off · regex + ML only';
    node.title = h.note;
  } catch (err) {
    node.className = 'health degraded';
    node.textContent = 'API unreachable';
  }
}

// ── Single line ────────────────────────────────────────────────

async function classifyOne() {
  const input = document.getElementById('single-input');
  const out = document.getElementById('single-out');
  const text = input.value.trim();
  if (!text) { out.className = 'result empty'; out.textContent = 'Type a log line first.'; return; }

  const btn = document.getElementById('single-go');
  btn.disabled = true;
  try {
    const r = await api('/classify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        allow_llm: !document.getElementById('single-offline').checked,
      }),
    });

    out.className = 'result';
    clear(out);

    const verdict = el('div', 'verdict');
    verdict.appendChild(el('span', 'badge ' + r.severity, r.severity));
    verdict.appendChild(el('span', 'cat', r.category));

    const bits = [
      'tier: ' + r.tier_used,
      r.confidence !== null && r.confidence !== undefined
        ? 'confidence: ' + (r.confidence * 100).toFixed(0) + '%'
        : 'confidence: not reported',
      r.latency_ms + ' ms',
      'cost: ' + money(r.cost_usd),
    ];
    verdict.appendChild(el('span', 'why', bits.join('  ·  ')));
    out.appendChild(verdict);

    out.appendChild(el('p', 'why', r.explain));

    if (r.note) {
      const note = el('div', 'fallback', r.note);
      out.appendChild(note);
    }
  } catch (err) {
    out.className = 'result';
    clear(out);
    out.appendChild(el('div', 'fallback', err.message));
  } finally {
    btn.disabled = false;
  }
}

// ── Batch ──────────────────────────────────────────────────────

async function triageBatch() {
  const area = document.getElementById('batch-input');
  const out = document.getElementById('batch-out');

  const lines = area.value.split('\n').map(s => s.trim()).filter(Boolean);
  if (!lines.length) { out.className = 'result empty'; out.textContent = 'Paste some log lines first.'; return; }

  const btn = document.getElementById('batch-go');
  btn.disabled = true;
  out.className = 'result';
  clear(out);
  out.appendChild(el('p', 'muted', `Classifying ${lines.length} lines…`));

  try {
    const r = await api('/classify/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        lines,
        allow_llm: !document.getElementById('batch-offline').checked,
      }),
    });

    clear(out);
    if (r.swapped_inputs) {
      out.appendChild(el('div', 'fallback',
        `${r.swapped_inputs} lines arrived as (timestamp, text) and were corrected.`));
    }

    // ── Tier economics: the argument for the architecture ──
    const stats = el('div', 'stats');
    const tiers = r.tier_counts || {};
    const stat = (n, label, cls) => {
      const s = el('div', 'stat' + (cls ? ' ' + cls : ''));
      s.appendChild(el('span', 'n', n));
      s.appendChild(el('span', 'l', label));
      return s;
    };
    stats.appendChild(stat(r.total_lines, 'lines'));
    stats.appendChild(stat(tiers.regex || 0, 'regex (free)'));
    stats.appendChild(stat(tiers.ml || 0, 'ml (free)'));
    stats.appendChild(stat(tiers.llm || 0, 'llm (paid)'));
    stats.appendChild(stat(money(r.total_cost_usd), 'actual cost'));
    stats.appendChild(stat(r.cost_avoided_pct + '%', 'cost avoided',
                            r.cost_avoided_pct >= 50 ? 'good' : 'warn'));
    stats.appendChild(stat(r.incidents.length, 'incidents'));
    stats.appendChild(stat(r.latency_ms.p50 + ' / ' + r.latency_ms.p95, 'p50 / p95 ms'));
    out.appendChild(stats);

    // Tier mix bar. Widths are inline percentages so no CSS calc is needed.
    const bar = el('div', 'tierbar');
    const total = r.total_lines || 1;
    ['regex', 'ml', 'llm', 'unknown'].forEach(tier => {
      const count = tiers[tier] || 0;
      if (!count) return;
      const seg = el('span', tier);
      seg.style.width = (count / total * 100) + '%';
      seg.title = `${tier}: ${count}`;
      bar.appendChild(seg);
    });
    out.appendChild(bar);

    if (r.llm_fallback) {
      out.appendChild(el('div', 'fallback',
        'The LLM tier was unavailable, so unmatched lines were reported as Unknown. ' +
        'The cheaper tiers still classified everything they could.'));
    }

    // ── Incidents ──
    out.appendChild(el('h3', '', `Incidents (${r.incidents.length})`));
    if (!r.incidents.length) {
      out.appendChild(el('p', 'muted', 'None found.'));
    }
    r.incidents.forEach(inc => {
      const box = el('div', 'incident ' + inc.severity);

      const head = el('div', 'head');
      head.appendChild(el('span', 'badge ' + inc.severity, inc.severity));
      head.appendChild(el('span', 'cat', inc.category));

      const meta = [];
      meta.push(inc.line_count + (inc.line_count === 1 ? ' line' : ' lines'));
      if (inc.duration_seconds !== null) meta.push('over ' + inc.duration_seconds + 's');
      if (inc.estimated_cost_usd) meta.push(money(inc.estimated_cost_usd));
      head.appendChild(el('span', 'meta', meta.join('  ·  ')));
      box.appendChild(head);

      if (inc.entities && inc.entities.length) {
        const ents = el('div', 'entities');
        inc.entities.forEach(e => ents.appendChild(el('code', '', e)));
        box.appendChild(ents);
      }

      const samples = el('ul', 'samples');
      (inc.sample_lines || []).forEach(s => samples.appendChild(el('li', '', s)));
      box.appendChild(samples);

      out.appendChild(box);
    });

    loadHistory();
  } catch (err) {
    clear(out);
    out.appendChild(el('div', 'fallback', err.message));
  } finally {
    btn.disabled = false;
  }
}

// ── History ────────────────────────────────────────────────────

async function loadHistory() {
  const body = document.getElementById('history-body');
  try {
    const r = await api('/runs?limit=10');
    clear(body);
    if (!r.runs.length) {
      const tr = el('tr');
      const td = el('td', 'muted', 'No runs yet.');
      td.colSpan = 6;
      tr.appendChild(td);
      body.appendChild(tr);
      return;
    }
    r.runs.forEach(run => {
      const tr = el('tr');
      tr.appendChild(el('td', '', '#' + run.id));
      tr.appendChild(el('td', '', (run.started_at || '').replace('T', ' ').slice(0, 19)));
      tr.appendChild(el('td', '', run.total_lines));
      tr.appendChild(el('td', '', run.incident_count));
      tr.appendChild(el('td', '', money(run.total_cost_usd)));
      const actions = el('td');
      const view = el('button', '', 'View');
      view.style.padding = '4px 10px';
      view.addEventListener('click', () => downloadReport(run.id));
      actions.appendChild(view);
      tr.appendChild(actions);
      body.appendChild(tr);
    });
  } catch (err) {
    // Built with el() rather than an innerHTML string, so every DOM write in
    // this file goes through textContent and no static scan has to reason about
    // which literals happen to be safe.
    clear(body);
    const tr = el('tr');
    const td = el('td', 'muted', 'History unavailable: ' + err.message);
    td.colSpan = 6;
    tr.appendChild(td);
    body.appendChild(tr);
  }
}

/**
 * Fetch one run and save it as JSON.
 *
 * The deliverable is the point: a triage run you cannot take away from the
 * browser is a screenshot, not an artefact. This writes the full report to disk.
 */
async function downloadReport(runId) {
  try {
    const run = await api('/runs/' + runId);
    const blob = new Blob([JSON.stringify(run, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `triage-run-${runId}.json`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    alert('Could not load run: ' + err.message);
  }
}

// ── File drop ──────────────────────────────────────────────────

function wireDropzone() {
  const zone = document.getElementById('dropzone');
  const file = document.getElementById('file-input');
  const area = document.getElementById('batch-input');

  zone.addEventListener('click', () => file.click());

  file.addEventListener('change', () => {
    if (file.files[0]) readFile(file.files[0]);
  });

  // dragover must preventDefault or the browser navigates to the file instead.
  zone.addEventListener('dragover', e => {
    e.preventDefault();
    zone.classList.add('over');
  });
  zone.addEventListener('dragleave', () => zone.classList.remove('over'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('over');
    if (e.dataTransfer.files[0]) readFile(e.dataTransfer.files[0]);
  });

  function readFile(f) {
    const reader = new FileReader();
    reader.onload = () => {
      area.value = reader.result;
      area.dispatchEvent(new Event('input'));
    };
    reader.readAsText(f);
  }
}

// ── Wiring ─────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  loadHealth();
  loadHistory();
  wireDropzone();

  document.getElementById('single-go').addEventListener('click', classifyOne);
  document.getElementById('batch-go').addEventListener('click', triageBatch);

  // Enter submits from the single-line input; the textarea needs a modifier so
  // a newline can still be typed.
  document.getElementById('single-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') classifyOne();
  });
  document.getElementById('batch-input').addEventListener('keydown', e => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) triageBatch();
  });

  // Re-check health when the tab regains focus, so pasting a key and returning
  // updates the indicator without a manual reload.
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) loadHealth();
  });
});
