// Pure (DOM-free) helpers for the Health, Impact and Ask views. Kept separate so they can be unit-tested with `node --test`.
export const SEVERITIES = ['critical', 'high', 'medium', 'low', 'info'];
export const CONFIDENCES = ['high', 'medium', 'low'];
export const CATEGORIES = ['testing', 'error_handling', 'security', 'configuration', 'logging', 'maintainability'];
export const KINDS = ['observed', 'potential_risk', 'absence', 'coverage_gap', 'metric'];
export const RESOLUTIONS = ['verified_static', 'inferred', 'unresolved'];

export const label = (s) => String(s || '').replaceAll('_', ' ');
// Palette is restricted to ink / grey / yellow / green: no red or orange for severity.
export const severityKind = (s) => ({ critical: 'bad', high: 'bad', medium: 'warn', low: 'info', info: 'neutral' })[s] || 'neutral';
export const confidenceKind = (c) => ({ high: 'ok', medium: 'warn', low: 'neutral' })[c] || 'neutral';

// Query string for GET /readiness: only the server's own filter names, empty values dropped.
export function readinessQuery(f = {}) {
  const p = new URLSearchParams();
  if (CATEGORIES.includes(f.category)) p.set('category', f.category);
  if (SEVERITIES.includes(f.severity)) p.set('severity', f.severity);
  if (CONFIDENCES.includes(f.min_confidence)) p.set('min_confidence', f.min_confidence);
  if (KINDS.includes(f.kind)) p.set('kind', f.kind);
  return p.toString();
}

// {path, line} for the in-app source viewer (files?path=&line=), from any {path, start_line, end_line} or {file, line} record.
export function sourceTarget(ev) {
  const path = ev.path || ev.file; const s = ev.start_line || ev.line || 0; const e = ev.end_line || s;
  return { path, line: s ? (e && e !== s ? `${s}-${e}` : String(s)) : '' };
}
export function sourceLabel(ev) { const t = sourceTarget(ev); return t.line ? `${t.path}:${t.line}` : t.path; }

// Impact: keep items whose resolution is at least as strong as `min` (verified_static > inferred > unresolved). '' keeps everything.
export function atLeast(items, min) {
  const cut = RESOLUTIONS.indexOf(min);
  return cut < 0 ? items : items.filter((x) => { const i = RESOLUTIONS.indexOf(x.resolution); return i >= 0 && i <= cut; });
}

// Chat: split an assistant message into what the cited source supports and what the model inferred beyond it.
export function answerParts(m) {
  const ai = m.answer_source === 'ai';
  return { ai, confidence: CONFIDENCES.includes(m.confidence) ? m.confidence : null, supported: m.content || '', citations: m.citations || [],
    inferred: ai ? (m.inferred || []).filter((x) => x && String(x).trim()) : [], limitations: m.limitations || [], insufficient: m.evidence_sufficiency === 'insufficient' };
}
export const CONFIDENCE_HELP = {
  high: 'High: a validated citation overlaps a direct match for your question and nothing is inferred.',
  medium: 'Medium: cited, but it rests on text matches or related code, or it includes inferred claims.',
  low: 'Low: insufficient evidence, no citations, or retrieval only.',
};
