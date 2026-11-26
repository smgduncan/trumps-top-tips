const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const SYDNEY = new Intl.DateTimeFormat('en-AU',{timeZone:'Australia/Sydney',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',hour12:false});
const syd = (v) => {
  if (!v) return '—';
  const iso = String(v).replace(' ', 'T');
  const dated = /(?:Z|[+-]\d{2}:\d{2})$/.test(iso) ? iso : iso + 'Z';
  const d = new Date(dated);
  return Number.isNaN(d.getTime()) ? '—' : SYDNEY.format(d);
};
const pct = (v) => v == null ? '—' : `${Number(v) > 0 ? '+' : ''}${Number(v).toFixed(2)}%`;
const price = (v) => v == null ? '—' : Number(v).toFixed(2);
const oneK = (v) => v == null ? '—' : '$' + Math.round(1000 * (1 + Number(v) / 100)).toLocaleString('en-AU');
const dollars = (v) => v == null ? '—' : '$' + Number(v).toLocaleString('en-AU');
const link = (u, label) => u ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>` : '';
const load = async (url) => { try { const r = await fetch(url, {cache:'no-store'}); return r.ok ? await r.json() : null; } catch { return null; } };
let events = {statements:[],reactions:[]}, state = {q:'', id:null};

function renderList() {
  const q = state.q.trim().toLowerCase();
  const rows = events.statements.filter(s => !q || [s.headline,s.excerpt,s.channel,s.topic,(s.tickers||[]).join(' ')].join(' ').toLowerCase().includes(q));
  $('#count').textContent = `${rows.length} statement${rows.length === 1 ? '' : 's'} · ${events.reactions.length} logged reactions · Sydney time`;
  $('#list').innerHTML = rows.map(s => `<a class="record" href="#${esc(s.statement_id)}" data-id="${esc(s.statement_id)}" aria-current="${s.statement_id === state.id}">
    <strong>${esc(s.headline)}</strong><span class="meta">${esc(syd(s.stated_at))} · ${esc(s.topic)} · ${esc((s.tickers||[]).join(', '))}</span></a>`).join('');
  $('#list').querySelectorAll('.record').forEach(a => a.addEventListener('click', () => select(a.dataset.id)));
}
function select(id) {
  state.id = id;
  const s = events.statements.find(x => x.statement_id === id);
  if (!s) return;
  const tone = s.sentiment > 0 ? 'Bullish' : s.sentiment < 0 ? 'Bearish' : 'Mixed';
  const rs = events.reactions.filter(r => r.statement_id === id);
  $('#detail').innerHTML = `<h3>${esc(s.headline)}</h3><p class="meta">${esc(syd(s.stated_at))} · ${esc(s.channel)} · ${tone} (confidence ${esc(s.confidence)})</p>
    <p>${esc(s.excerpt)}</p>${s.evidence_quote ? `<blockquote>“${esc(s.evidence_quote)}”</blockquote>` : ''}
    <p class="meta">${esc(s.notes)} ${link(s.source_url,'Source ↗')}</p>
    <h4>Recorded reactions</h4>${rs.length ? rs.map(r => `<details><summary>${esc(r.asset)} · ${esc(r.horizon)} · <b class="${Number(r.return_pct)>0?'up':Number(r.return_pct)<0?'down':''}">${pct(r.return_pct)}</b></summary>
      <dl><dt>Entry basis</dt><dd>${esc(r.entry_basis)}</dd><dt>Price proxy</dt><dd>${esc(price(r.entry_price))} → ${esc(price(r.exit_price))}${r.executable ? '' : ' · study figure, not a trade'}</dd>
      <dt>Source</dt><dd>${link(r.source_url,'Read ↗')}</dd><dt>Note</dt><dd>${esc(r.notes)}${r.evidence_quote ? ` “${esc(r.evidence_quote)}”` : ''}</dd></dl></details>`).join('') : '<p>No reactions logged.</p>'}`;
  $('#detail').focus({preventScroll:true});
}
function renderWatch(data) {
  const signals = Array.isArray(data?.signals) ? data.signals : [];
  $('#signals').innerHTML = `<p class="meta">${signals.length ? `As of ${esc(syd(data.as_of))}` : 'No signals recorded yet'}</p>` + (signals.length ? `<div class="table-wrap"><table><thead><tr><th>Observed</th><th>Asset</th><th>Direction</th><th>Entry</th><th>Close</th><th>T+2</th><th>$1k close / T+2</th><th>Status</th><th>Post</th></tr></thead><tbody>${signals.slice().reverse().map(s => `<tr>
    <td>${esc(syd(s.observed_at))}</td><td>${esc(s.asset)}</td><td>${esc(s.direction)}</td><td>${esc(price(s.entry_price))}</td>
    <td class="${Number(s.close_return_pct)>0?'up':Number(s.close_return_pct)<0?'down':''}">${pct(s.close_return_pct)}</td>
    <td class="${Number(s.t2_return_pct)>0?'up':Number(s.t2_return_pct)<0?'down':''}">${pct(s.t2_return_pct)}</td>
    <td>${oneK(s.close_return_pct)} / ${oneK(s.t2_return_pct)}</td>
    <td>${esc(s.status)}</td><td>${link(s.post_url,'↗')}</td></tr>`).join('')}</tbody></table></div>
    <p class="meta">Paper observations only. Entry is a quote at or after publication + five minutes, or the next session open; no orders are placed.</p>` : '<p>Watch desk idle: no public statement has met the pre-registered filter yet.</p>');
}
function renderHistory(data) {
  const rows = Array.isArray(data?.rows) ? data.rows : [];
  $('#rows').innerHTML = `<p class="meta">${rows.length ? `As of ${esc(syd(data.as_of))}` : 'No backfill yet'}</p>` + (rows.length ? `<div class="table-wrap"><table><thead><tr><th>Statement</th><th>Asset</th><th>Window</th><th>Asset</th><th>Sector</th><th>Excess</th><th>$1k end → now</th><th>Verdict</th><th>Source</th></tr></thead><tbody>${rows.map(r => `<tr>
    <td>${esc(r.headline)}</td><td>${esc(r.asset)}</td><td>${esc(r.horizon)}</td>
    <td class="${Number(r.asset_return_pct)>0?'up':Number(r.asset_return_pct)<0?'down':''}">${pct(r.asset_return_pct)}</td>
    <td>${pct(r.benchmark_return_pct)}</td><td class="${Number(r.excess_return_pct)>0?'up':Number(r.excess_return_pct)<0?'down':''}">${pct(r.excess_return_pct)}</td>
    <td>${dollars(r.value_1000_at_end)} → ${dollars(r.value_1000_now)}<div class="meta">now: ${esc(r.latest_date || '—')}</div></td>
    <td>${esc(r.verdict)}${r.data_mismatch ? ' ⚠' : ''}</td><td title="${esc(r.note)}">${link(r.source_url,'src ↗')}</td></tr>`).join('')}</tbody></table></div>
    <p class="meta">Daily closes from Yahoo Finance, matched to the same window; not proof that a trade was available at the quoted price.</p>` : '<p>History feed empty.</p>');
}
(async () => {
  const [ev, watch, hist] = await Promise.all([load('events.json'), load('watch.json'), load('history.json')]);
  events = ev && Array.isArray(ev.statements) ? ev : {statements:[],reactions:[]};
  renderList(); renderWatch(watch); renderHistory(hist);
  const hash = location.hash.slice(1);
  if (hash && events.statements.some(s => s.statement_id === hash)) select(hash);
  $('#filters').querySelector('input').addEventListener('input', (e) => { state.q = e.target.value; renderList(); });
  window.addEventListener('hashchange', () => { const id = location.hash.slice(1); if (id) select(id); });
})();
