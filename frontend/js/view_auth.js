import { post, ApiError } from './api.js';
import { el } from './util.js';
import { icon } from './icons.js';

const NS = 'http://www.w3.org/2000/svg';
const sv = (t, a = {}, ...k) => { const n = document.createElementNS(NS, t); for (const [x, y] of Object.entries(a)) n.setAttribute(x, y); k.forEach((c) => n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c)); return n; };
function heroFlow() {
  const svg = sv('svg', { class: 'hero-flow', viewBox: '0 0 560 300', 'aria-hidden': 'true' });
  const box = (x, y, w, label, fill, txt) => [sv('rect', { x: x + 5, y: y + 5, width: w, height: 46, rx: 10, fill: '#bef264' }), sv('rect', { x, y, width: w, height: 46, rx: 10, fill, stroke: '#0a0a0a', 'stroke-width': 1.5 }), sv('text', { x: x + 16, y: y + 29, fill: txt, 'font-family': 'JetBrains Mono, monospace', 'font-size': 13, 'font-weight': 600 }, label)];
  const edge = (d, dash) => sv('path', { d, fill: 'none', stroke: dash ? '#71717a' : '#0a0a0a', 'stroke-width': 1.6, 'stroke-dasharray': dash ? '6 5' : '' });
  svg.append(edge('M170 60 C230 60 230 150 290 150'), edge('M170 60 C230 60 230 40 290 40'), edge('M420 40 C470 40 470 110 500 120'), edge('M420 150 C460 150 460 230 290 240', true), edge('M150 150 C200 150 200 240 250 240'), edge('M420 150 C455 150 470 140 500 130'));
  const nodes = [[20, 38, 150, 'main.py', '#0a0a0a', '#fff'], [290, 18, 130, 'routes.py', '#fff', '#0a0a0a'], [290, 128, 130, 'users.py', '#047857', '#fff'], [20, 128, 130, 'deps.py', '#fff', '#0a0a0a'], [250, 218, 160, 'models.py', '#84cc16', '#0a0a0a'], [480, 100, 70, 'db', '#fff', '#0a0a0a']];
  for (const [x, y, w, l, f, t] of nodes) svg.append(...box(x, y, w, l, f, t));
  return svg;
}
function form(kind, submitLabel, submit, extra) {
  const err = el('div', { role: 'alert' });
  const email = el('input', { id: 'email', type: 'email', autocomplete: 'email', required: true, maxlength: 320 });
  const pw = el('input', { id: 'pw', type: 'password', autocomplete: kind === 'register' ? 'new-password' : 'current-password', required: true, maxlength: 200 });
  const btn = el('button', { class: 'btn primary', type: 'submit', style: '' }, submitLabel, icon('arrow'));
  const f = el('form', { novalidate: 'true', class: 'stack' },
    el('div', {}, el('div', { class: 'eyebrow', text: kind === 'register' ? 'Get started' : 'Welcome back' }), el('h1', { text: kind === 'register' ? 'Create account' : 'Sign in' })),
    el('div', { class: 'field' }, el('label', { for: 'email' }, 'Email'), email),
    el('div', { class: 'field' }, el('label', { for: 'pw' }, 'Password'), pw, kind === 'register' ? el('p', { class: 'hint' }, 'At least 10 characters.') : null), err, btn, extra);
  f.addEventListener('submit', async (e) => {
    e.preventDefault(); err.replaceChildren(); btn.disabled = true;
    try { await submit(email.value, pw.value); } catch (x) { err.replaceChildren(el('div', { class: 'banner bad' }, icon('alert'), x instanceof ApiError ? x.message : 'Something went wrong.')); btn.disabled = false; pw.focus(); }
  });
  const art = el('aside', { class: 'auth-art' }, el('div', {}, el('div', { class: 'eyebrow', text: 'RAVEN' }),
    el('h2', {}, 'Read any FastAPI codebase like a ', el('em', { text: 'map' }), '.'), el('p', { text: 'Pinned to a commit. Every connection cites its evidence. Nothing is executed.' })), heroFlow());
  return { node: el('div', { class: 'auth' }, art, el('div', { class: 'auth-form' }, f)), after: () => email.focus() };
}
export function loginView(onAuthed) { return form('login', 'Sign in', async (e, p) => onAuthed((await post('/api/v1/auth/login', { email: e, password: p })).user), el('p', { class: 'small muted' }, 'No account yet? ', el('a', { href: '#/register' }, 'Create one'))); }
export function registerView(onAuthed) { return form('register', 'Create account', async (e, p) => onAuthed((await post('/api/v1/auth/register', { email: e, password: p })).user), el('p', { class: 'small muted' }, 'Already registered? ', el('a', { href: '#/login' }, 'Sign in'))); }
