// Run: node --test frontend/tests/*.test.mjs   (Node >= 20, no dependencies)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { readinessQuery, sourceTarget, sourceLabel, atLeast, answerParts, severityKind, confidenceKind, SEVERITIES, CONFIDENCES } from '../js/insights.js';

const JS = resolve(dirname(fileURLToPath(import.meta.url)), '../js');

test('readinessQuery keeps only the API filter names and known values', () => {
  assert.equal(readinessQuery({}), '');
  assert.equal(readinessQuery({ severity: 'high', min_confidence: 'medium', category: 'security', kind: 'potential_risk' }), 'category=security&severity=high&min_confidence=medium&kind=potential_risk');
  assert.equal(readinessQuery({ severity: 'urgent', min_confidence: '', category: 'x&y=1', kind: undefined, extra: 'z' }), '');
});

test('sourceTarget builds files-view links from evidence, route and citation records', () => {
  assert.deepEqual(sourceTarget({ path: 'app/a.py', start_line: 4, end_line: 9 }), { path: 'app/a.py', line: '4-9' });
  assert.deepEqual(sourceTarget({ path: 'app/a.py', start_line: 4, end_line: 4 }), { path: 'app/a.py', line: '4' });
  assert.deepEqual(sourceTarget({ file: 'app/r.py', line: 12 }), { path: 'app/r.py', line: '12' });
  assert.deepEqual(sourceTarget({ path: 'app/a.py' }), { path: 'app/a.py', line: '' });
  assert.equal(sourceLabel({ path: 'x.py', start_line: 2, end_line: 3 }), 'x.py:2-3');
});

test('atLeast filters impact links by resolution strength', () => {
  const items = [{ resolution: 'verified_static' }, { resolution: 'inferred' }, { resolution: 'unresolved' }, { resolution: 'bogus' }];
  assert.equal(atLeast(items, '').length, 4);
  assert.deepEqual(atLeast(items, 'inferred').map((x) => x.resolution), ['verified_static', 'inferred']);
  assert.deepEqual(atLeast(items, 'verified_static').map((x) => x.resolution), ['verified_static']);
});

test('answerParts separates inferred claims from the source-supported answer', () => {
  const ai = answerParts({ answer_source: 'ai', confidence: 'medium', content: 'Defined in a.py.', citations: [{ path: 'a.py', start_line: 1, end_line: 1 }], inferred: ['Probably runs per request.', ' '], limitations: [], evidence_sufficiency: 'sufficient' });
  assert.equal(ai.ai, true); assert.equal(ai.confidence, 'medium'); assert.equal(ai.supported, 'Defined in a.py.');
  assert.deepEqual(ai.inferred, ['Probably runs per request.']); assert.equal(ai.citations.length, 1); assert.equal(ai.insufficient, false);
  // retrieval-only fallback: never shows inferred claims, keeps citations, low confidence
  const ro = answerParts({ answer_source: 'retrieval_only', confidence: 'low', content: 'Inspect these', citations: [{ path: 'b.py', start_line: 2, end_line: 5 }], inferred: ['x'], limitations: ['AI answering unavailable'], evidence_sufficiency: 'insufficient' });
  assert.equal(ro.ai, false); assert.deepEqual(ro.inferred, []); assert.equal(ro.citations.length, 1); assert.equal(ro.confidence, 'low'); assert.equal(ro.insufficient, true);
  // messages stored before confidence existed
  const old = answerParts({ answer_source: 'ai', content: 'x', confidence: null });
  assert.equal(old.confidence, null); assert.deepEqual(old.inferred, []); assert.deepEqual(old.citations, []);
});

test('severity and confidence map onto existing badge styles only', () => {
  const allowed = new Set(['ok', 'warn', 'bad', 'info', 'neutral']);
  for (const s of SEVERITIES) assert.ok(allowed.has(severityKind(s)), s);
  for (const c of CONFIDENCES) assert.ok(allowed.has(confidenceKind(c)), c);
  assert.equal(severityKind('critical'), 'bad'); assert.equal(confidenceKind('high'), 'ok'); assert.equal(severityKind('nope'), 'neutral');
});

test('every relative import in frontend/js resolves to a file exporting the imported names', () => {
  const files = readdirSync(JS).filter((f) => f.endsWith('.js'));
  for (const f of files) {
    const src = readFileSync(join(JS, f), 'utf8');
    for (const m of src.matchAll(/import\s*\{([^}]*)\}\s*from\s*'(\.\/[^']+)'/g)) {
      const target = join(JS, m[2]); assert.ok(existsSync(target), `${f} imports missing ${m[2]}`);
      const tsrc = readFileSync(target, 'utf8');
      for (const name of m[1].split(',').map((x) => x.trim().split(/\s+as\s+/)[0]).filter(Boolean)) {
        assert.match(tsrc, new RegExp(`export\\s+(async\\s+)?(function|const|let|class)\\s+${name}\\b`), `${f}: ${m[2]} does not export ${name}`);
      }
    }
  }
});

test('workspace tabs, routing and command palette include Health and Impact', () => {
  const va = readFileSync(join(JS, 'view_analysis.js'), 'utf8');
  assert.match(va, /\['health', 'Health', '[a-z]+'\]/); assert.match(va, /\['impact', 'Impact', '[a-z]+'\]/);
  assert.match(va, /health: healthView/); assert.match(va, /impact: impactView/);
  const app = readFileSync(join(JS, 'app.js'), 'utf8');
  assert.match(app, /'\/health'/); assert.match(app, /'\/impact'/);
  const icons = readFileSync(join(JS, 'icons.js'), 'utf8');
  for (const m of va.matchAll(/\['\w+', '\w+', '(\w+)'\]/g)) assert.match(icons, new RegExp(`\\b${m[1]}:`), `icon ${m[1]} missing`);
});

test('views only write untrusted text through textContent (no innerHTML)', () => {
  for (const f of ['view_health.js', 'view_impact.js', 'view_chat.js', 'insights.js']) assert.doesNotMatch(readFileSync(join(JS, f), 'utf8'), /innerHTML|insertAdjacentHTML|outerHTML/, f);
});

test("el() props never use raw data-* keys (el() drops them; use `dataset`)", () => {
  for (const f of readdirSync(JS).filter((x) => x.startsWith('view_'))) assert.doesNotMatch(readFileSync(join(JS, f), 'utf8'), /['"]data-[a-z-]+['"]\s*:/, f);
});
