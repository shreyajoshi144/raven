// Run: cd web && npm test   (node:test; no extra dependencies). Static checks that keep the React shell consistent with the API and legacy helpers.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseHash } from '../src/router.js';

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const LEGACY = resolve(SRC, '../../frontend/js');
const files = (d) => readdirSync(d, { recursive: true }).filter((f) => /\.(jsx?|css)$/.test(f)).map((f) => join(d, f));

test('hash router parses paths and queries', () => {
  assert.deepEqual(parseHash('#/a/123/files?path=app%2Fmain.py&line=4-9'), { parts: ['a', '123', 'files'], query: { path: 'app/main.py', line: '4-9' } });
  assert.deepEqual(parseHash(''), { parts: [], query: {} });
  assert.deepEqual(parseHash('#/verify-email?token=abc-_'), { parts: ['verify-email'], query: { token: 'abc-_' } });
});

test('every @legacy import resolves to an exported name', () => {
  for (const f of files(SRC).filter((x) => x.endsWith('.jsx') || x.endsWith('.js'))) {
    const src = readFileSync(f, 'utf8');
    for (const m of src.matchAll(/import\s*\{([^}]*)\}\s*from\s*'@legacy\/([^']+)'/g)) {
      const target = join(LEGACY, m[2]); assert.ok(existsSync(target), `${f}: missing ${m[2]}`);
      const tsrc = readFileSync(target, 'utf8');
      for (const name of m[1].split(',').map((x) => x.trim().split(/\s+as\s+/)[0]).filter(Boolean)) assert.match(tsrc, new RegExp(`export\\s+(async\\s+)?(function|const|let|class)\\s+${name}\\b`), `${f}: ${m[2]} does not export ${name}`);
    }
  }
});

test('every endpoint the screens call exists in the API routes', () => {
  const api = readFileSync(resolve(SRC, '../../backend/app/api/routes_analyses.py'), 'utf8') + readFileSync(resolve(SRC, '../../backend/app/api/routes_auth.py'), 'utf8') + readFileSync(resolve(SRC, '../../backend/app/api/routes_pr.py'), 'utf8');
  const admin = readFileSync(resolve(SRC, '../../backend/app/api/routes_admin.py'), 'utf8');  // router prefix is /api/v1/admin
  const routes = [...api.matchAll(/@router\.(get|post|delete)\("([^"]+)"/g)].map((m) => m[2].replace(/\{[^}]+\}/g, '{}'))
    .concat([...admin.matchAll(/@router\.(get|post|put|delete)\("([^"]+)"/g)].map((m) => '/admin' + m[2].replace(/\{[^}]+\}/g, '{}')));
  for (const f of files(SRC).filter((x) => x.endsWith('.jsx'))) {
    const text = readFileSync(f, 'utf8').replace(/\$\{[^}]*\}/g, '{}');  // template expressions become {} placeholders
    for (const m of text.matchAll(/\/api\/v1(\/[^`'"?\s]*)/g)) {
      const path = m[1].replace(/([a-z])\{\}$/, '$1').replace(/\/$/, '') || '/';  // a trailing {} after a name is a query-string suffix
      assert.ok(routes.some((r) => r.replace(/\/$/, '') === path || r === path), `${f}: no backend route for ${m[0]}`);
    }
  }
});

test('screens never inject raw HTML and use only the declared dependencies', () => {
  for (const f of files(SRC)) assert.doesNotMatch(readFileSync(f, 'utf8'), /dangerouslySetInnerHTML|\.innerHTML\s*=|eval\(/, f);
  const pkg = JSON.parse(readFileSync(resolve(SRC, '../package.json'), 'utf8'));
  assert.deepEqual(Object.keys(pkg.dependencies).sort(), ['react', 'react-dom']);
});

test('account screens cover verification, reset and 2FA flows', () => {
  const auth = readFileSync(join(SRC, 'screens/Auth.jsx'), 'utf8') + readFileSync(join(SRC, 'screens/Security.jsx'), 'utf8');
  for (const p of ['/auth/login/2fa', '/auth/verify-email', '/auth/resend-verification', '/auth/forgot-password', '/auth/reset-password', '/auth/2fa/setup', '/auth/2fa/enable', '/auth/2fa/disable']) assert.ok(auth.includes(p), p);
});

test('public landing: unauthenticated "/" renders Landing, protected routes redirect to login and keep the deep link', () => {
  const app = readFileSync(join(SRC, 'App.jsx'), 'utf8');
  assert.match(app, /p0 === '' \? <Landing \/>/);
  assert.match(app, /!PUBLIC\.has\(p0\) && p0 !== ''/);
  assert.match(app, /takeNext/);
  const land = readFileSync(join(SRC, 'screens/Landing.jsx'), 'utf8');
  assert.match(land, /go\('\/register'\)/); assert.match(land, /go\('\/login'\)/);
  assert.deepEqual(parseHash('#/a/abc/ask?q=1').parts, ['a', 'abc', 'ask']);
});
