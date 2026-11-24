// Inline SVG icon set (stroke icons, built through createElementNS — no innerHTML).
const NS = 'http://www.w3.org/2000/svg';
const P = {
  graph: 'M6 5a2 2 0 1 0 0 .01M18 5a2 2 0 1 0 0 .01M12 19a2 2 0 1 0 0 .01M7.6 6.6l3.4 10M16.4 6.6l-3.4 10M8 5h8',
  files: 'M6 3h8l4 4v14H6zM14 3v4h4M9 12h6M9 16h6',
  docs: 'M5 4h14v16H5zM8 8h8M8 12h8M8 16h5',
  chat: 'M4 5h16v11H9l-5 4zM8 9h8M8 12h5',
  overview: 'M4 5h7v7H4zM13 5h7v4h-7zM13 11h7v8h-7zM4 14h7v5H4z',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4',
  plus: 'M12 5v14M5 12h14', minus: 'M5 12h14', fit: 'M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5',
  check: 'M5 12l4 4 10-10', x: 'M6 6l12 12M18 6L6 18', alert: 'M12 4l9 16H3zM12 10v4M12 17v.01',
  arrow: 'M5 12h14M13 6l6 6-6 6', download: 'M12 4v11M7 11l5 5 5-5M5 20h14', refresh: 'M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6',
  trash: 'M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13', github: 'M9 19c-4 1-4-2-6-2m12 4v-3c0-1 0-2-1-3 3 0 6-1.5 6-6 0-1.3-.4-2.3-1.2-3.2.2-.8.2-2-.3-3 0 0-1 0-3 1.4a10 10 0 0 0-5 0C8 3 7 3 7 3c-.5 1-.5 2.200-.3 3A5 5 0 0 0 5.500 9c0 4.500 3 6 6 6-1 .8-1 1.800-1 3v3',
  route: 'M5 6a2 2 0 1 0 0 .01M19 18a2 2 0 1 0 0 .01M7 6h6a4 4 0 0 1 0 8h-2a4 4 0 0 0 0 8',
  entry: 'M6 4l13 8-13 8z', model: 'M4 7c0-1.700 3.600-3 8-3s8 1.300 8 3-3.600 3-8 3-8-1.300-8-3zM4 7v5c0 1.700 3.600 3 8 3s8-1.300 8-3V7M4 12v5c0 1.700 3.600 3 8 3s8-1.300 8-3v-5',
  service: 'M12 3l8 4.500v9L12 21l-8-4.500v-9zM12 12l8-4.500M12 12v9M12 12L4 7.500', config: 'M5 7h9M18 7h1M5 17h1M10 17h9M14 7a2 2 0 1 0 0 .01M8 17a2 2 0 1 0 0 .01',
  worker: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2', module: 'M6 4h12v16H6zM9 9h6M9 13h6',
  external: 'M14 4h6v6M20 4l-9 9M18 14v6H4V6h6', test: 'M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3M8 15h8',
  lock: 'M6 11h12v9H6zM8 11V8a4 4 0 0 1 8 0v3', sparkle: 'M12 3l1.800 5.200L19 10l-5.200 1.800L12 17l-1.800-5.200L5 10l5.200-1.800zM18 16l.8 2.200L21 19l-2.200.8L18 22l-.8-2.200L15 19l2.200-.8z',
  folder: 'M3 6h6l2 2h10v11H3z', branch: 'M7 4v12M7 16a2 2 0 1 0 0 .01M17 8a2 2 0 1 0 0 .01M17 10c0 4-10 2-10 6', cmd: 'M9 9h6v6H9zM9 9V6a3 3 0 1 0-3 3h3zM15 9V6a3 3 0 1 1 3 3h-3zM9 15v3a3 3 0 1 1-3-3h3zM15 15v3a3 3 0 1 0 3-3h-3z',
  focus: 'M12 12m-3 0a3 3 0 1 0 6 0 3 3 0 1 0-6 0M4 9V5h4M20 9V5h-4M4 15v4h4M20 15v4h-4', trace: 'M4 12h4l3-6 4 12 3-6h2', filter: 'M4 5h16l-6 8v6l-4-2v-4z', bolt: 'M13 3L5 14h6l-1 7 8-11h-6z',
};
export function icon(name, extra = '') {
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('class', 'ic ' + extra); svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS(NS, 'path'); path.setAttribute('d', P[name] || P.module); svg.appendChild(path);
  return svg;
}
export function iconPath(name) { return P[name] || P.module; }
export const ROLE_ICON = { entry: 'entry', router: 'route', model: 'model', service: 'service', config: 'config', worker: 'worker', module: 'module', test: 'test', external: 'external', frontend: 'module' };
export const ROLE_LABEL = { entry: 'Entry point', router: 'Routes', model: 'Data models', service: 'Services', config: 'Config', worker: 'Workers', module: 'Modules', test: 'Tests', external: 'External', frontend: 'Frontend' };
