// Minimal interpreter for the generated Raven workflow JSON (subset of n8n semantics). NOT n8n: it exists to execute the
// workflow *logic* (Code/IF/Switch/HTTP/Wait/Respond nodes) against a live stack when real n8n is unavailable.
import http from 'node:http';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';

const dir = process.argv[2];
const port = Number(process.env.RUNNER_PORT || 5678);
const waitScale = Number(process.env.WAIT_SCALE || 1);
const workflows = fs.readdirSync(dir).filter((f) => f.endsWith('.json')).map((f) => JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')));
const hooks = new Map();
for (const wf of workflows) for (const n of wf.nodes) if (n.type === 'n8n-nodes-base.webhook') hooks.set(n.parameters.path, { wf, node: n });
let execCounter = 1000;

function ctxFor(exec, item, node) {
  const outputs = exec.outputs;
  const ref = (name) => ({
    first: () => (outputs.get(name) || []).at(-1)?.[0]?.[0] ?? { json: {} },
    last: () => (outputs.get(name) || []).at(-1)?.[0]?.at(-1) ?? { json: {} },
    all: () => (outputs.get(name) || []).at(-1)?.[0] ?? [],
  });
  return { $json: item?.json ?? {}, $env: process.env, $execution: { id: String(exec.id) }, $: ref, $input: { first: () => item, all: () => exec.currentInput, item }, $node: {} };
}
function evalExpr(expr, ctx) { return vm.runInNewContext(expr, { ...ctx, JSON, Math, Number, String, Date, Object, Array, Boolean, parseInt }, { timeout: 2000 }); }
function resolve(value, ctx) {
  if (typeof value === 'string' && value.startsWith('=')) {
    const body = value.slice(1);
    const m = /^\{\{([\s\S]*)\}\}$/.exec(body.trim());
    if (m && !body.slice(2).includes('{{')) return evalExpr(m[1], ctx);
    return body.replace(/\{\{([\s\S]*?)\}\}/g, (_, e) => String(evalExpr(e, ctx)));
  }
  if (Array.isArray(value)) return value.map((v) => resolve(v, ctx));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, resolve(v, ctx)]));
  return value;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function runNode(exec, node, items) {
  const p = node.parameters; exec.currentInput = items;
  switch (node.type) {
    case 'n8n-nodes-base.webhook': return [items];
    case 'n8n-nodes-base.noOp': return [items];
    case 'n8n-nodes-base.code': {
      const ctx = ctxFor(exec, items[0], node);
      const fn = vm.runInNewContext(`(function(){${p.jsCode}\n})`, { ...ctx, JSON, Math, Number, String, Date, Object, Array, Boolean, parseInt, Error }, { timeout: 2000 });
      const out = fn();
      if (!Array.isArray(out)) throw new Error(`Code node ${node.name} must return an array`);
      return [out];
    }
    case 'n8n-nodes-base.if': {
      const cond = p.conditions.conditions[0];
      const left = resolve(cond.leftValue, ctxFor(exec, items[0], node));
      return left === true ? [items, []] : [[], items];
    }
    case 'n8n-nodes-base.switch': {
      const outs = p.rules.values.map(() => []);
      const ctx = ctxFor(exec, items[0], node);
      for (const it of items) {
        const c = { ...ctx, $json: it.json };
        const idx = p.rules.values.findIndex((r) => resolve(r.conditions.conditions[0].leftValue, c) === r.conditions.conditions[0].rightValue);
        if (idx >= 0) outs[idx].push(it);
      }
      return outs;
    }
    case 'n8n-nodes-base.wait': {
      const secs = Number(resolve(p.amount, ctxFor(exec, items[0], node)));
      await sleep(Math.max(0, secs * 1000 * waitScale));
      return [items];
    }
    case 'n8n-nodes-base.respondToWebhook': {
      const ctx = ctxFor(exec, items[0], node);
      const body = resolve(p.responseBody, ctx);
      if (exec.res && !exec.responded) { exec.responded = true; exec.res.writeHead(p.options?.responseCode || 200, { 'content-type': 'application/json' }); exec.res.end(typeof body === 'string' ? body : JSON.stringify(body)); }
      return [items];
    }
    case 'n8n-nodes-base.httpRequest': {
      const ctx = ctxFor(exec, items[0], node);
      const url = resolve(p.url, ctx);
      const headers = Object.fromEntries((p.headerParameters?.parameters || []).map((h) => [h.name, resolve(h.value, ctx)]));
      let body;
      if (p.sendBody) { body = resolve(p.jsonBody, ctx); body = typeof body === 'string' ? body : JSON.stringify(body); headers['content-type'] = 'application/json'; }
      try {
        const res = await fetch(url, { method: p.method, headers, body, signal: AbortSignal.timeout(p.options?.timeout || 30000) });
        const text = await res.text(); let parsed = text; try { parsed = JSON.parse(text); } catch { /* keep text */ }
        return [[{ json: { statusCode: res.status, headers: Object.fromEntries(res.headers), body: parsed } }]];
      } catch (e) { return [[{ json: { error: { message: String(e) } } }]]; }
    }
    default: throw new Error('unsupported node type ' + node.type);
  }
}

async function execute(wf, startNode, items, res) {
  const exec = { id: execCounter++, outputs: new Map(), res, responded: false, currentInput: items };
  const byName = new Map(wf.nodes.map((n) => [n.name, n]));
  const queue = [[startNode, items]]; let steps = 0;
  while (queue.length) {
    if (++steps > 5000) throw new Error('step limit');
    const [node, inp] = queue.shift();
    if (!inp.length) continue;
    let outs;
    try { outs = await runNode(exec, node, inp); } catch (e) { console.error(`[exec ${exec.id}] node "${node.name}" failed: ${e.message}`); if (res && !exec.responded) { exec.responded = true; res.writeHead(500); res.end('{}'); } return; }
    const runs = exec.outputs.get(node.name) || []; runs.push(outs); exec.outputs.set(node.name, runs);
    (wf.connections[node.name]?.main || []).forEach((targets, idx) => { for (const t of targets) if ((outs[idx] || []).length) queue.push([byName.get(t.node), outs[idx]]); });
  }
  if (res && !exec.responded) { res.writeHead(200); res.end('{}'); }
  console.log(`[exec ${exec.id}] ${wf.name} finished (${steps} node runs)`);
}

http.createServer((req, res) => {
  const u = new URL(req.url, 'http://x');
  if (u.pathname === '/healthz') { res.writeHead(200); return res.end('{"status":"ok"}'); }
  const m = /^\/webhook\/([^/]+)$/.exec(u.pathname);
  const hook = m && hooks.get(m[1]);
  if (!hook || req.method !== 'POST') { res.writeHead(404); return res.end('{}'); }
  let data = '';
  req.on('data', (c) => (data += c));
  req.on('end', () => {
    let body = {}; try { body = JSON.parse(data || '{}'); } catch { /* ignore */ }
    const item = { json: { headers: Object.fromEntries(Object.entries(req.headers)), body, query: {} } };
    const respondNode = hook.wf.nodes.some((n) => n.type === 'n8n-nodes-base.respondToWebhook') && hook.node.parameters.responseMode === 'responseNode';
    if (!respondNode) { res.writeHead(200); res.end('{"message":"started"}'); execute(hook.wf, hook.node, [item], null); } else execute(hook.wf, hook.node, [item], res);
  });
}).listen(port, '127.0.0.1', () => console.log(`workflow runner on ${port} with hooks: ${[...hooks.keys()].join(', ')}`));
