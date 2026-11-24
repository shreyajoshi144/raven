// Lazy loader for the vendored Mermaid bundle (served from our own origin; strict CSP forbids CDNs).
let loading = null;
function load() {
  if (window.mermaid) return Promise.resolve(window.mermaid);
  if (!loading) {
    loading = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = '/assets/vendor/mermaid.min.js';
      s.onload = () => {
        window.mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'base', fontFamily: 'Inter, system-ui, sans-serif', flowchart: { htmlLabels: false, useMaxWidth: true, curve: 'basis' }, maxTextSize: 60000,
          themeVariables: { primaryColor: '#ffffff', primaryBorderColor: '#0a0a0a', primaryTextColor: '#0a0a0a', lineColor: '#0a0a0a', secondaryColor: '#e6f5ec', tertiaryColor: '#f6f6f7', edgeLabelBackground: '#ffffff', clusterBkg: '#f6f6f7', clusterBorder: '#d1d1d6', nodeBorder: '#0a0a0a' } });
        resolve(window.mermaid);
      };
      s.onerror = () => reject(new Error('Diagram library failed to load'));
      document.head.appendChild(s);
    });
  }
  return loading;
}
let counter = 0;
export async function renderMermaid(source, container) {
  const mermaid = await load();
  const { svg } = await mermaid.render('mmd' + (++counter), source);
  container.innerHTML = svg; // SVG produced by Mermaid in strict mode from server-sanitized labels
  return container.querySelector('svg');
}
export async function renderAllIn(root) {
  for (const node of root.querySelectorAll('[data-mermaid]')) {
    try { await renderMermaid(node.dataset.mermaid, node); node.removeAttribute('data-mermaid'); }
    catch (e) {
      node.textContent = '';
      node.appendChild(Object.assign(document.createElement('pre'), { textContent: node.dataset.mermaid }));
      node.insertAdjacentElement('afterbegin', Object.assign(document.createElement('p'), { className: 'muted small', textContent: 'Diagram could not be rendered; showing its source.' }));
    }
  }
}
