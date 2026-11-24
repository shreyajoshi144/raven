"""Design-constraint audit: no blue / violet / red / orange / cream-beige, no large dark surfaces, no blur (glass) effects."""
AUDIT_JS = r"""
() => {
  const bad = [], seen = new Set();
  const parse = (c) => { const m = c.match(/rgba?\(([\d.]+)[, ]+([\d.]+)[, ]+([\d.]+)(?:[,/ ]+([\d.]+))?\)/); return m ? { r: +m[1], g: +m[2], b: +m[3], a: m[4] === undefined ? 1 : +m[4] } : null; };
  const hsl = ({ r, g, b }) => { r /= 255; g /= 255; b /= 255; const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2; let h = 0, s = 0;
    if (mx !== mn) { const d = mx - mn; s = l > .5 ? d / (2 - mx - mn) : d / (mx + mn); h = mx === r ? ((g - b) / d + (g < b ? 6 : 0)) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4; h *= 60; } return { h, s, l }; };
  const check = (el, prop, val) => {
    if (!val || val === 'none') return;
    for (const m of val.matchAll(/rgba?\([^)]*\)/g)) { const c = parse(m[0]); if (!c || c.a < .05) continue; const { h, s, l } = hsl(c);
      if (s < .14 || l > .985 || l < .035) continue;           // neutrals (white / grey / ink)
      const ok = h >= 52 && h <= 172;                           // yellow-lime-green-emerald only
      if (!ok) { const key = prop + m[0] + el.tagName + (el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className); if (!seen.has(key)) { seen.add(key); bad.push(`${el.tagName.toLowerCase()}.${(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className) || ''} ${prop}=${m[0]} (h=${Math.round(h)} s=${s.toFixed(2)} l=${l.toFixed(2)})`); } } }
  };
  for (const el of document.querySelectorAll('body, body *')) {
    const cs = getComputedStyle(el); if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    for (const p of ['color', 'backgroundColor', 'borderTopColor', 'borderBottomColor', 'borderLeftColor', 'borderRightColor', 'outlineColor', 'boxShadow', 'textDecorationColor', 'caretColor']) {
      if ((p.startsWith('border') && parseFloat(cs[p.replace('Color', 'Width')]) === 0) || (p === 'outlineColor' && cs.outlineStyle === 'none')) continue; check(el, p, cs[p]); }
    if (el instanceof SVGElement) { check(el, 'fill', cs.fill); check(el, 'stroke', cs.stroke); check(el, 'stopColor', cs.stopColor); }
    if (cs.backgroundImage && cs.backgroundImage !== 'none') check(el, 'backgroundImage', cs.backgroundImage);
    if ((cs.backdropFilter && cs.backdropFilter !== 'none') || (cs.filter && /blur/.test(cs.filter))) bad.push(`${el.tagName.toLowerCase()}.${el.className} uses blur/backdrop-filter (glass)`);
  }
  // large dark surfaces (dark UI): any element covering >20% of the viewport with a dark opaque background
  const vw = innerWidth, vh = innerHeight;
  for (const el of document.querySelectorAll('body, body *')) { const cs = getComputedStyle(el), c = parse(cs.backgroundColor); if (!c || c.a < .9) continue; const r = el.getBoundingClientRect();
    const area = Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0)) * Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0)); if (area / (vw * vh) > .2 && hsl(c).l < .5) bad.push(`large dark surface: ${el.tagName.toLowerCase()}.${el.className} bg=${cs.backgroundColor}`); }
  const bg = parse(getComputedStyle(document.body).backgroundColor); if (!bg || hsl(bg).l < .95) bad.push('body background is not light');
  return bad;
}
"""


def audit(page, name):
    bad = page.evaluate(AUDIT_JS)
    assert not bad, f"[{name}] palette/design violations:\n  " + "\n  ".join(bad[:15])
    print(f"AUDIT ok: {name}", flush=True)
