// Tiny Python tokenizer → DOM spans (textContent only; safe for untrusted source).
const KW = new Set('False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case'.split(' '));
const RE = /("""[\s\S]*?"""|'''[\s\S]*?''')|(#[^\n]*)|("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')|(\b\d[\d_]*(?:\.\d+)?\b)|(@[A-Za-z_][\w.]*)|([A-Za-z_]\w*)/g;
function span(cls, text) { const e = document.createElement('span'); if (cls) e.className = cls; e.textContent = text; return e; }
export function highlightLine(line, state) {
  const frag = document.createDocumentFragment();
  if (state.inDoc) { const end = line.indexOf(state.inDoc); if (end === -1) { frag.appendChild(span('tk-str', line)); return frag; } frag.appendChild(span('tk-str', line.slice(0, end + 3))); line = line.slice(end + 3); state.inDoc = null; const rest = highlightLine(line, state); frag.appendChild(rest); return frag; }
  let last = 0, m, prev = '';
  RE.lastIndex = 0;
  while ((m = RE.exec(line))) {
    if (m.index > last) frag.appendChild(document.createTextNode(line.slice(last, m.index)));
    const t = m[0];
    if (m[1]) { frag.appendChild(span('tk-str', t)); }
    else if (m[2]) frag.appendChild(span('tk-com', t));
    else if (m[3]) frag.appendChild(span('tk-str', t));
    else if (m[4]) frag.appendChild(span('tk-num', t));
    else if (m[5]) frag.appendChild(span('tk-dec', t));
    else if (KW.has(t)) frag.appendChild(span('tk-kw', t));
    else if (prev === 'def' || prev === 'class') frag.appendChild(span('tk-fn', t));
    else frag.appendChild(document.createTextNode(t));
    if (!m[2]) prev = m[6] ? t : prev; last = m.index + t.length;
  }
  const tail = line.slice(last);
  const open = /("""|''')/.exec(tail);
  if (open && (tail.split(open[1]).length - 1) % 2 === 1) { state.inDoc = open[1]; const i = tail.indexOf(open[1]); if (i > 0) frag.appendChild(document.createTextNode(tail.slice(0, i))); frag.appendChild(span('tk-str', tail.slice(i))); }
  else if (tail) frag.appendChild(document.createTextNode(tail));
  return frag;
}
