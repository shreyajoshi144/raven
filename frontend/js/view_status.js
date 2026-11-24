import { get } from './api.js';
import { el, badge } from './util.js';
import { icon } from './icons.js';

export async function statusView() {
  const s = await get('/api/v1/status'); const row = (k, v) => [el('dt', { text: k }), el('dd', {}, v)];
  const tile = (ic, title, ok, text) => el('div', { class: 'card' }, el('div', { class: 'row spread' }, icon(ic), badge(ok ? 'operational' : 'attention', ok ? 'ok' : 'warn')), el('h3', { style: '', text: title }), el('p', { class: 'small muted', text }));
  return { node: el('div', { class: 'page stack-lg' }, el('div', {}, el('div', { class: 'eyebrow', text: 'System' }), el('h1', { text: 'System status' })),
    el('div', { class: 'repo-grid' }, tile('bolt', 'Database', s.database.reachable, s.database.reachable ? 'PostgreSQL is reachable.' : 'Cannot reach the database.'),
      tile('graph', 'Workflow engine (n8n)', s.orchestrator.reachable, s.orchestrator.reachable ? 'Reachable.' : 'Unreachable — new analyses will wait until it returns.'),
      tile('sparkle', 'Language model', s.llm.configured, s.llm.configured ? `Configured (${s.llm.model}).` : 'Not configured — guides and Q&A fall back to deterministic output.'),
      tile('github', 'GitHub access', true, s.github.authenticated ? 'Authenticated (higher rate limit).' : 'Unauthenticated (60 requests/hour).')),
    el('section', { class: 'card' }, el('h2', { text: `Configured limits · v${s.version} · ${s.environment}` }), el('dl', { class: 'kv' }, ...Object.entries(s.limits).flatMap(([k, v]) => row(k.replaceAll('_', ' '), String(v)))))) };
}
