import { el } from './util.js';
import { icon } from './icons.js';

let open = null;
export function openPalette({ commands, search }) {
  if (open) return;
  const prevFocus = document.activeElement;
  const input = el('input', { type: 'text', placeholder: 'Jump to a page, analysis or file…', 'aria-label': 'Command palette', autocomplete: 'off', role: 'combobox', 'aria-expanded': 'true', 'aria-controls': 'pal-list' });
  const list = el('ul', { id: 'pal-list', class: 'list-reset', role: 'listbox' });
  const back = el('div', { class: 'pal-back' }, el('div', { class: 'pal', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Command palette' }, input, list,
    el('div', { class: 'hint-row' }, el('span', {}, el('span', { class: 'kbd', text: '↑↓' }), ' navigate'), el('span', {}, el('span', { class: 'kbd', text: '↵' }), ' open'), el('span', {}, el('span', { class: 'kbd', text: 'esc' }), ' close'))));
  let items = [], idx = 0, seq = 0;
  const render = () => {
    list.replaceChildren(...(items.length ? items.map((it, i) => el('li', {}, el('button', { type: 'button', role: 'option', 'aria-selected': i === idx ? 'true' : 'false', on: { click: () => run(it), mousemove: () => { idx = i; mark(); } } },
      icon(it.icon || 'arrow'), el('span', {}, it.label), it.hint ? el('span', { class: 'muted small', style: '' }, ' ' + it.hint) : null))) : [el('li', { class: 'empty small', text: 'No matches' })]));
  };
  const mark = () => [...list.querySelectorAll('button')].forEach((b, i) => b.setAttribute('aria-selected', i === idx ? 'true' : 'false'));
  const close = () => { back.remove(); open = null; document.removeEventListener('keydown', onKey, true); prevFocus && prevFocus.focus && prevFocus.focus(); };
  const run = (it) => { close(); it.run(); };
  async function refresh() {
    const q = input.value.trim().toLowerCase(); const my = ++seq;
    let base = commands.filter((c) => !q || c.label.toLowerCase().includes(q));
    items = base; idx = 0; render();
    if (q.length >= 2 && search) { const extra = await search(q).catch(() => []); if (my === seq) { items = [...base, ...extra]; render(); } }
  }
  const onKey = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); close(); } else if (e.key === 'ArrowDown') { e.preventDefault(); idx = Math.min(items.length - 1, idx + 1); mark(); list.querySelectorAll('button')[idx]?.scrollIntoView({ block: 'nearest' }); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); idx = Math.max(0, idx - 1); mark(); list.querySelectorAll('button')[idx]?.scrollIntoView({ block: 'nearest' }); }
    else if (e.key === 'Enter') { e.preventDefault(); if (items[idx]) run(items[idx]); }
  };
  back.addEventListener('mousedown', (e) => { if (e.target === back) close(); });
  document.addEventListener('keydown', onKey, true);
  input.addEventListener('input', refresh);
  document.body.append(back); open = true; input.focus(); refresh();
}
