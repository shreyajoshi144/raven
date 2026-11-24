import { useEffect, useRef } from 'react';
import { go } from '../router.js';

// Public homepage (unauthenticated "/"). Content is limited to what the product demonstrably does.
const CHAIN = [['route', 'POST /items/', 'items.py:61'], ['depends', 'CurrentUser', 'deps.py:49'], ['resolves', 'get_current_user', 'deps.py:30-49'], ['reads', 'User', 'models.py:51']];
const FEATURES = [
  ['Interactive map', 'See the architecture first, open any part to see its files, then follow what depends on what. Every connection is labelled verified, inferred or unresolved.'],
  ['Ask with citations', 'Questions answered from retrieved code with file and line citations. If the model is down you still get the source locations.'],
  ['Readiness & health', 'Rule-based findings for auth gaps, secrets, missing tests and config, each pointing at the exact lines.'],
  ['Change impact', 'Pick a file or route and see what depends on it, with the evidence for each link.'],
  ['Onboarding guide', 'A generated architecture guide with Mermaid diagrams, marked partial when anything was skipped.'],
];
const STEPS = [['Paste a public repo', 'A GitHub URL for a Python / FastAPI project.'], ['Raven analyses it', 'Fetch, parse, build the graph, score readiness, write the guide.'], ['Explore with evidence', 'Navigate the map, ask questions, check impact. Gaps are stated, not hidden.']];
const STRIP = ['Routes', 'Models', 'Services', 'Imports', 'Dependencies', 'Tests'];
const jump = (id) => document.getElementById(id)?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });

export default function Landing() {
  const root = useRef(null);
  useEffect(() => {
    const nodes = root.current?.querySelectorAll('[data-reveal]'); if (!nodes?.length || typeof IntersectionObserver === 'undefined') return undefined;
    root.current.classList.add('reveal-ready');
    const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } }), { threshold: 0.12 });
    nodes.forEach((n) => io.observe(n)); return () => io.disconnect();
  }, []);
  return (
    <div className="landing sky" ref={root}>
      <header className="l-nav">
        <a className="brand" href="#/" aria-label="Raven home"><span className="mark" aria-hidden="true" />Raven</a>
        <nav className="l-links" aria-label="Sections"><button type="button" onClick={() => jump('how')}>How it works</button><button type="button" onClick={() => jump('preview')}>Routes</button><button type="button" onClick={() => jump('features')}>Features</button></nav>
        <div className="l-actions"><button className="btn sm quiet" type="button" onClick={() => go('/login')}>Sign in</button><button className="btn sm dark" type="button" onClick={() => go('/register')}>Get started</button></div>
      </header>
      <main id="main">
        <section className="l-hero">
          <div className="hero-img" aria-hidden="true" />
          <div className="l-hero-copy">
            <h1>Read a codebase the way it <em>actually connects</em></h1>
            <p className="lead">Point Raven at a public FastAPI repository. Get a map, a health report and cited answers, every claim tied to a file, a line and how it was established.</p>
            <div className="row"><button className="btn dark lg" type="button" onClick={() => go('/register')}>Get started</button><button className="btn outline lg" type="button" onClick={() => go('/login')}>Sign in</button></div>
          </div>
          <ul className="l-strip" aria-label="What Raven maps">{STRIP.map((s) => <li key={s}>{s}</li>)}</ul>
        </section>

        <section id="preview" className="l-sec">
          <h2 data-reveal>Every route, <em>traced end to end</em></h2>
          <p className="l-sub" data-reveal>Pick an endpoint and see the handler, the dependencies it resolves and the models it reads, each with the file and line that proves it.</p>
          <ol className="l-chain" data-reveal aria-label="Example route trace from a real FastAPI repository">
            {CHAIN.map(([k, n, loc], i) => <li key={n} style={{ '--i': i }}><span className="tile"><b>{k}</b></span><span className="n">{n}</span><span className="loc">{loc}</span></li>)}
          </ol>
          <small className="l-cap">Example chain from a real FastAPI repository. Verified by static analysis.</small>
        </section>

        <section id="features" className="l-sec">
          <h2 data-reveal>Built to be <em>checked</em>, not trusted</h2>
          <div className="l-feats">{FEATURES.map(([t, d], i) => <article key={t} data-reveal style={{ '--i': i }}><span className="num">0{i + 1}</span><h3>{t}</h3><p>{d}</p></article>)}</div>
        </section>

        <section id="how" className="l-sec">
          <h2 data-reveal>From URL to <em>understanding</em></h2>
          <ol className="l-steps">{STEPS.map(([t, d], i) => <li key={t} data-reveal style={{ '--i': i }}><span className="num">{i + 1}</span><h3>{t}</h3><p>{d}</p></li>)}</ol>
        </section>

        <section className="l-cta" data-reveal><h2>Try it on your <em>own repository</em></h2><p>Free to sign up. Public repositories only.</p><div className="row"><button className="btn dark lg" type="button" onClick={() => go('/register')}>Get started</button></div></section>
      </main>
      <footer className="l-foot">Static analysis only. Raven never executes the code it reads.</footer>
    </div>
  );
}
