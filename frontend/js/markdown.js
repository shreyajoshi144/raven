// Minimal, safe Markdown → DOM renderer. No HTML passthrough: every text is a text node; links are allow-listed.
import { el } from './util.js';

const GH_BLOB = /^https:\/\/github\.com\/([A-Za-z0-9._-]+\/[A-Za-z0-9._-]+)\/blob\/([0-9a-f]{40})\/([^#\s]+)(?:#L(\d+)(?:-L(\d+))?)?$/;

function safeLink(href, text, ctx) {
  const m = GH_BLOB.exec(href);
  if (m && ctx && ctx.repo === m[1] && ctx.sha === m[2] && ctx.openSource) {
    const a = el('a', { href: '#', class: 'source-link', text });
    a.addEventListener('click', (e) => { e.preventDefault(); ctx.openSource(decodeURIComponent(m[3]), m[4] ? +m[4] : null, m[5] ? +m[5] : (m[4] ? +m[4] : null)); });
    return a;
  }
  if (/^https:\/\/github\.com\/[A-Za-z0-9._\-\/#?=%]*$/.test(href)) return el('a', { href, rel: 'noopener noreferrer', target: '_blank', text });
  return document.createTextNode(text);
}

export function inline(text, ctx) {
  const frag = document.createDocumentFragment();
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\[(?:[^\]\\]|\\.)+\]\([^)\s]+\))|(_[^_\s][^_]*_)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
    const tok = m[0];
    if (m[1]) frag.appendChild(el('code', { text: tok.slice(1, -1) }));
    else if (m[2]) frag.appendChild(el('strong', {}, inline(tok.slice(2, -2), ctx)));
    else if (m[3]) {
      const mm = /^\[((?:[^\]\\]|\\.)+)\]\(([^)\s]+)\)$/.exec(tok);
      const label = mm[1].replace(/\\(.)/g, '$1');
      const inner = label.startsWith('`') && label.endsWith('`') ? label.slice(1, -1) : label;
      const link = safeLink(mm[2], inner, ctx);
      if (label.startsWith('`') && link.tagName === 'A') { const c = el('code', { text: inner }); link.textContent = ''; link.appendChild(c); }
      frag.appendChild(link);
    } else if (m[4]) frag.appendChild(el('em', {}, inline(tok.slice(1, -1), ctx)));
    last = m.index + tok.length;
  }
  if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
  return frag;
}

function splitRow(line) {
  const cells = []; let cur = ''; let esc = false;
  const s = line.trim().replace(/^\|/, '').replace(/\|$/, '');
  for (const ch of s) {
    if (esc) { cur += ch === '|' ? '|' : '\\' + ch; esc = false; } else if (ch === '\\') esc = true; else if (ch === '|') { cells.push(cur.trim()); cur = ''; } else cur += ch;
  }
  cells.push(cur.trim());
  return cells;
}

export function renderMarkdown(md, ctx = {}) {
  const root = el('div', { class: 'prose' });
  const lines = md.replace(/\r\n/g, '\n').split('\n');
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const fence = /^```(\w*)\s*$/.exec(line);
    if (fence) {
      const buf = []; i++;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) buf.push(lines[i++]);
      i++;
      if (fence[1] === 'mermaid') root.appendChild(el('div', { class: 'diagram', role: 'img', 'aria-label': 'Diagram', dataset: { mermaid: buf.join('\n') } }));
      else root.appendChild(el('pre', {}, el('code', { text: buf.join('\n') })));
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) { root.appendChild(el('h' + Math.min(h[1].length + 0, 6), {}, inline(h[2], ctx))); i++; continue; }
    if (/^---+\s*$/.test(line)) { root.appendChild(el('hr')); i++; continue; }
    if (line.trim().startsWith('|') && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const head = splitRow(line); i += 2;
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) rows.push(splitRow(lines[i++]));
      root.appendChild(el('div', { class: 'table-wrap' }, el('table', {}, el('thead', {}, el('tr', {}, head.map((c) => el('th', {}, inline(c, ctx))))),
        el('tbody', {}, rows.map((r) => el('tr', {}, head.map((_, ci) => el('td', {}, inline(r[ci] || '', ctx)))))))));
      continue;
    }
    if (/^>\s?/.test(line)) {
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, ''));
      root.appendChild(el('blockquote', {}, inline(buf.join(' '), ctx)));
      continue;
    }
    const li = /^(\s*)([-*]|\d+\.)\s+(.*)$/.exec(line);
    if (li) {
      const ordered = /\d/.test(li[2]);
      const top = el(ordered ? 'ol' : 'ul');
      const stack = [{ indent: li[1].length, node: top }];
      while (i < lines.length) {
        const m = /^(\s*)([-*]|\d+\.)\s+(.*)$/.exec(lines[i]);
        if (!m) break;
        const indent = m[1].length;
        while (stack.length > 1 && indent < stack[stack.length - 1].indent) stack.pop();
        if (indent > stack[stack.length - 1].indent) {
          const parentLi = stack[stack.length - 1].node.lastElementChild;
          const sub = el('ul'); (parentLi || stack[stack.length - 1].node).appendChild(sub);
          stack.push({ indent, node: sub });
        }
        stack[stack.length - 1].node.appendChild(el('li', {}, inline(m[3], ctx)));
        i++;
      }
      root.appendChild(top);
      continue;
    }
    const buf = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|```|>|\s*([-*]|\d+\.)\s|\|)/.test(lines[i])) buf.push(lines[i++]);
    if (!buf.length) { buf.push(lines[i++]); }
    root.appendChild(el('p', {}, inline(buf.join(' '), ctx)));
  }
  return root;
}
