import { get, post, del, ApiError } from './api.js';
import { el, mount, badge } from './util.js';
import { icon } from './icons.js';
import { answerParts, confidenceKind, CONFIDENCE_HELP } from './insights.js';

const SUGGESTIONS = ['What are the main entry points of this application?', 'Which routes require authentication?', 'Where are the database models defined?', 'Which environment variables does the app read?'];

export async function chatView(a, query, ctx) {
  const id = a.analysis_id; let dead = false, busy = false;
  const log = el('div', { class: 'chat', role: 'log', 'aria-live': 'polite', 'aria-label': 'Conversation' });
  const input = el('textarea', { id: 'q', maxlength: 2000, rows: 2, placeholder: 'Ask about this codebase — e.g. “What does get_current_user do?”' });
  const count = el('span', { class: 'small muted', text: '0 / 2000' }); const send = el('button', { class: 'btn primary', type: 'submit' }, 'Ask', icon('arrow')); const errBox = el('div', { role: 'alert' });
  input.addEventListener('input', () => { count.textContent = `${input.value.length} / 2000`; });
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); form.requestSubmit(); } });
  const open = (c) => ctx.goto('files', { path: c.path, line: c.end_line !== c.start_line ? `${c.start_line}-${c.end_line}` : c.start_line });
  function msg(m) {
    if (m.role === 'user') return el('div', { class: 'msg user' }, el('div', { class: 'bd', text: m.content }));
    if (m.status === 'failed') return el('div', { class: 'msg bot' }, el('div', { class: 'av' }, icon('alert')), el('div', { class: 'bubble' }, el('div', { class: 'banner bad', style: '' }, m.content || 'This question could not be answered.')));
    const p = answerParts(m);
    const cites = p.citations.length ? el('div', { class: 'cites' }, el('div', { class: 'small muted', text: 'Sources' }), p.citations.map((c, i) => el('button', { class: 'cite', type: 'button', on: { click: () => open(c) } }, el('span', { class: 'n', text: String(i + 1) }), el('span', {}, el('span', { class: 'mono', text: `${c.path}:${c.start_line}${c.end_line !== c.start_line ? '-' + c.end_line : ''}` }), c.excerpt ? el('div', { class: 'excerpt', text: c.excerpt }) : null)))) : null;
    return el('div', { class: 'msg bot' }, el('div', { class: 'av' }, icon('sparkle')), el('div', { class: 'bubble' },
      el('div', { class: 'row', style: '' }, p.ai ? badge('AI answer', 'info', 'Generated from retrieved code; citations are validated against the analyzed files') : badge('retrieval only — no AI answer', 'warn'), p.insufficient ? badge('insufficient evidence', 'warn') : badge('evidence found', 'ok'),
        p.confidence ? badge(`${p.confidence} confidence`, confidenceKind(p.confidence), CONFIDENCE_HELP[p.confidence] + ' A rule over the evidence, not a probability.') : null),
      el('div', { class: 'answer-part supported' }, p.ai ? el('div', { class: 'small muted part-label', text: p.citations.length ? 'Supported by the cited source' : 'Answer (no supporting citation)' }) : null, el('div', { class: 'bd', text: p.supported }), cites),
      p.inferred.length ? el('div', { class: 'answer-part inferred', role: 'note' }, el('div', { class: 'small part-label' }, icon('alert'), el('strong', { text: ' Inferred — not shown directly by the cited code' })), el('ul', { class: 'small' }, p.inferred.map((x) => el('li', { text: x })))) : null,
      p.limitations.length ? el('ul', { class: 'small muted' }, p.limitations.map((l) => el('li', { text: l }))) : null));
  }
  async function history() { try { const d = await get(`/api/v1/analyses/${id}/chat?limit=100`); if (dead) return; mount(log, d.items.length ? d.items.map(msg) : el('div', { class: 'card flat empty' }, icon('chat'), el('p', { class: 'small', text: 'Ask anything. Answers cite the exact files and lines they come from; if the evidence is not there, Raven says so.' }))); log.lastElementChild?.scrollIntoView({ block: 'nearest' }); } catch (e) { mount(log, el('div', { class: 'banner bad' }, icon('alert'), e.message)); } }
  const form = el('form', { class: 'composer', novalidate: 'true' }, el('label', { for: 'q', class: 'small', style: '' }, 'Ask a question'), input, el('div', { class: 'row spread' }, count, el('div', { class: 'row' },
    el('button', { class: 'btn sm', type: 'button', on: { click: async () => { if (!confirm('Clear this conversation?')) return; try { await del(`/api/v1/analyses/${id}/chat`); } catch (x) { errBox.replaceChildren(el('div', { class: 'banner bad' }, icon('alert'), x instanceof ApiError ? x.message : 'Something went wrong.')); } history(); } } }, 'Clear'), send)));
  form.addEventListener('submit', async (e) => {
    e.preventDefault(); const text = input.value.trim(); if (!text || busy) return; busy = true; send.disabled = true; errBox.replaceChildren();
    log.append(el('div', { class: 'msg user' }, el('div', { class: 'bd', text })), el('div', { class: 'msg bot', id: 'pending' }, el('div', { class: 'av' }, icon('sparkle')), el('div', { class: 'bubble' }, el('span', { class: 'typing', role: 'status', 'aria-label': 'Searching the code and drafting an answer' }, el('i'), el('i'), el('i')))));
    try { await post(`/api/v1/analyses/${id}/chat`, { message: text }); input.value = ''; count.textContent = '0 / 2000'; await history(); }
    catch (x) { document.getElementById('pending')?.remove(); errBox.replaceChildren(el('div', { class: 'banner bad' }, icon('alert'), x instanceof ApiError ? x.message : 'Something went wrong.', x.retryable ? ' Your question is still in the box — you can send it again.' : '')); await history(); }
    finally { busy = false; send.disabled = false; }
  });
  mount(log, el('div', { class: 'skeleton', style: '' })); history();
  const side = el('aside', { class: 'stack' }, el('div', { class: 'card flat' }, el('h3', { text: 'Try asking' }), el('div', { class: 'suggest', style: '' }, SUGGESTIONS.map((s) => el('button', { type: 'button', text: s, on: { click: () => { input.value = s; input.focus(); count.textContent = `${s.length} / 2000`; } } })))),
    el('div', { class: 'card flat small muted' }, icon('lock'), ' Answers are built only from retrieved code at the analyzed commit and must cite file and line ranges. Static analysis cannot show runtime behavior.'));
  return { node: el('div', { class: 'stack-lg' }, el('div', {}, el('div', { class: 'eyebrow', text: 'Ask' }), el('h2', { text: 'Questions, answered with citations' })), el('div', { class: 'chat-shell' }, el('div', { class: 'stack' }, log, errBox, form), side)), cleanup: () => { dead = true; } };
}
