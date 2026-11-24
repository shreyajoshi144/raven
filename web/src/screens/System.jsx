import { get } from '@legacy/api.js';
import { Card, Eyebrow, ErrorBox, Skeleton, Badge, useAsync } from '../components/ui.jsx';

export default function System() {
  const q = useAsync(() => get('/api/v1/status'), []);
  const d = q.data;
  return (
    <div className="page stack-lg">
      <div><Eyebrow>System</Eyebrow><h1>Platform status</h1></div>
      {q.loading ? <Skeleton /> : q.error ? <ErrorBox error={q.error} retry={q.reload} /> : (
        <div className="bento">
          <Card className="stack"><h2>Services</h2>
            <dl className="kv">
              <dt>Database</dt><dd>{d.database.reachable ? <Badge kind="ok">reachable</Badge> : <Badge kind="bad">down</Badge>}</dd>
              <dt>Orchestrator (n8n)</dt><dd>{d.orchestrator.reachable ? <Badge kind="ok">reachable</Badge> : <Badge kind="bad">unreachable</Badge>}</dd>
              <dt>LLM</dt><dd>{d.llm.configured ? <Badge kind="ok">{d.llm.provider} · {d.llm.model}</Badge> : <Badge>not configured (retrieval-only answers)</Badge>}</dd>
              <dt>GitHub</dt><dd>{d.github.authenticated ? <Badge kind="ok">token set</Badge> : <Badge kind="warn">unauthenticated (60 req/h)</Badge>}</dd>
              <dt>Version</dt><dd className="mono">{d.version} · {d.environment}</dd>
            </dl></Card>
          <Card className="stack"><h2>Limits</h2><dl className="kv">{Object.entries(d.limits).map(([k, v]) => [<dt key={k}>{k.replaceAll('_', ' ')}</dt>, <dd key={k + 'v'} className="mono">{v}</dd>])}</dl></Card>
        </div>)}
    </div>
  );
}
