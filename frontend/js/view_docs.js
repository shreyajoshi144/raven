import { get, post, ApiError } from './api.js';
import { el, mount, spinner, badge, toast, fmtDate, shortSha } from './util.js';
import { icon } from './icons.js';
import { renderMarkdown } from './markdown.js';
import { renderAllIn } from './mermaid.js';

export async function docsView(a, query, ctx) {
  const id = a.analysis_id; let dead = false, timer = null, io = null;
  const box = el('div', { class: 'stack-lg' });
  async function load() {
    clearTimeout(timer); let d;
    try { d = await get(`/api/v1/analyses/${id}/docs`); } catch (e) { if (!dead) mount(box, el('div', { class: 'banner bad', role: 'alert' }, icon('alert'), e.message, ' ', el('button', { class: 'linklike', type: 'button', on: { click: load } }, 'Try again'))); return; }
    if (dead) return; const doc = d.document; const pending = d.regenerating || (!doc && a.status !== 'FAILED') || (doc && doc.status === 'PENDING');
    const banners = [];
    if (!doc) banners.push(el('div', { class: 'banner' }, pending ? spinner('The onboarding guide is being generated…') : 'No guide exists for this analysis.'));
    if (doc) {
      if (doc.status === 'PARTIAL') banners.push(el('div', { class: 'banner warn' }, icon('alert'), el('div', {}, el('strong', { text: 'Partial guide. ' }), (doc.gaps || []).join(' · ') || 'Some content is unavailable.')));
      if (doc.ai_status === 'unavailable') banners.push(el('div', { class: 'banner' }, icon('sparkle'), 'AI-written explanations are not included. Everything below is derived directly from static analysis.'));
      if (d.regenerating) banners.push(el('div', { class: 'banner' }, spinner('A new version is being generated; showing the previous one.')));
      if (d.pending_status === 'FAILED') banners.push(el('div', { class: 'banner bad' }, icon('alert'), 'The last regeneration failed. The previous version is shown.'));
    }
    const ctxMd = { repo: a.repository.full_name, sha: a.commit_sha, openSource: (path, line, end) => ctx.goto('files', { path, line: line ? (end && end !== line ? `${line}-${end}` : line) : '' }) };
    const content = doc && doc.markdown ? renderMarkdown(doc.markdown, ctxMd) : null;
    const toc = el('nav', { class: 'toc', 'aria-label': 'On this page' }, el('h3', { text: 'On this page' }));
    if (content) { content.querySelectorAll('h2').forEach((h, i) => { h.id = 'sec-' + i; toc.appendChild(el('a', { href: '#', dataset: { t: h.id }, on: { click: (e) => { e.preventDefault(); document.getElementById(h.id).scrollIntoView({ behavior: 'smooth', block: 'start' }); } } }, h.textContent.replace(/^\d+\.\s*/, ''))); }); }
    mount(box, el('div', { class: 'row spread' }, el('div', {}, el('div', { class: 'eyebrow', text: 'Onboarding guide' }), el('h2', { text: 'Everything a new developer should read first' }),
      doc ? el('div', { class: 'row small muted', style: '' }, badge(doc.status === 'READY' ? 'complete' : 'partial', doc.status === 'READY' ? 'ok' : 'warn'), badge(`AI: ${doc.ai_status}`, doc.ai_status === 'ok' ? 'ok' : 'neutral'), `v${doc.version} · commit ${shortSha(doc.commit_sha)} · ${fmtDate(doc.updated_at)}`) : null),
      el('div', { class: 'row' }, doc ? el('a', { class: 'btn', href: `/api/v1/analyses/${id}/docs/download`, download: 'download' }, icon('download'), 'Download .md') : null, a.status === 'READY' ? el('button', { class: 'btn', type: 'button', disabled: d.regenerating, on: { click: regenerate } }, icon('refresh'), d.regenerating ? 'Regenerating…' : 'Regenerate') : null)),
      ...banners, content ? el('div', { class: 'docs' }, toc, content) : null);
    if (content) {
      renderAllIn(content);
      if (io) io.disconnect(); io = new IntersectionObserver((es) => { for (const e of es) if (e.isIntersecting) { toc.querySelectorAll('a').forEach((x) => x.classList.toggle('on', x.dataset.t === e.target.id)); } }, { rootMargin: '-80px 0px -70% 0px' });
      content.querySelectorAll('h2').forEach((h) => io.observe(h));
    }
    if (!dead && (d.regenerating || (!doc && pending))) timer = setTimeout(load, 3000);
  }
  async function regenerate() { try { await post(`/api/v1/analyses/${id}/docs/generate`); toast('Regeneration started'); load(); } catch (e) { toast(e instanceof ApiError ? e.message : 'Failed', 'bad'); } }
  mount(box, el('div', { class: 'skeleton', style: '' })); load();
  return { node: box, cleanup: () => { dead = true; clearTimeout(timer); if (io) io.disconnect(); } };
}
