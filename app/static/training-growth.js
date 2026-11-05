/* Decorative login tree. Reuses SkillTreeBotanical geometry and the garden
   growth classes (masked a-draw branches, a-sprout / a-unfurl leaves). It does
   not mount the garden page or change a real learning tree. */
'use strict';
(() => {
  const host = document.getElementById('login-tree');
  const artwork = window.SkillTreeBotanical;
  if (!host || !artwork) return;
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const W = 400, H = 460, G = 352;
  const f = v => Math.round(v * 10) / 10;
  let serial = 0;
  let timer = 0;

  function svg(tag, attrs = {}, ...children) {
    const n = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [k, v] of Object.entries(attrs)) if (v != null) n.setAttribute(k, String(v));
    for (const child of children.flat()) if (child) n.append(child);
    return n;
  }
  function artNodes(markup) {
    const doc = new DOMParser().parseFromString('<svg xmlns="http://www.w3.org/2000/svg">' + markup + '</svg>', 'image/svg+xml');
    return [...doc.documentElement.children].map(n => document.importNode(n, true));
  }
  function leafGroup(spec) {
    const status = spec.status, size = spec.size, count = Math.max(1, Math.min(5, spec.count || 2));
    const outer = svg('g', {
      class: 'node st-' + status,
      transform: `translate(${f(spec.at[0])} ${f(spec.at[1])}) rotate(${f(spec.rot || 0)})`,
    });
    const grow = svg('g', {class: status === 'passed' ? 'a-unfurl' : 'a-sprout'});
    grow.style.setProperty('--d', spec.delay + 'ms');
    if (status === 'current') grow.append(svg('circle', {class: 'ring', cx: 0, cy: f(-size * .45), r: f(size * .82)}));
    if (status === 'available') grow.append(svg('circle', {class: 'halo', cx: 0, cy: f(-size * .28), r: f(size * .55)}));
    if (status === 'locked' || status === 'available') grow.append(...artNodes(artwork.bud(size, status === 'available')));
    else {
      const sway = svg('g', {class: 'sway'});
      const inner = svg('g', status === 'current' ? {transform: 'scale(.8)'} : {});
      const nodes = artNodes(artwork.leaf('general', size, status, count, spec.veins ? 'a-vein' : ''));
      for (const node of nodes) {
        if (node.matches?.('.a-vein')) node.style.setProperty('--d', (spec.delay + 420) + 'ms');
        node.querySelectorAll?.('.a-vein').forEach(vein => vein.style.setProperty('--d', (spec.delay + 420) + 'ms'));
      }
      inner.append(...nodes);
      sway.append(inner);
      grow.append(sway);
    }
    outer.append(grow);
    return outer;
  }

  function draw() {
    const id = 'login-growth-' + (++serial);
    const defs = svg('defs');
    const animate = !motion.matches;
    function limb(c, w1, w2, cls, key, delay) {
      const path = svg('path', {class: 'br ' + cls, d: artwork.taper(c, w1, w2)});
      if (!animate) return path;
      const maskId = id + '-' + key;
      const mask = svg('mask', {id: maskId, maskUnits: 'userSpaceOnUse', x: 0, y: 0, width: W, height: H});
      const reveal = svg('path', {class: 'mpath a-draw', pathLength: 1, d: artwork.centerline(c)});
      reveal.style.setProperty('--d', delay + 'ms');
      mask.append(reveal);
      defs.append(mask);
      path.setAttribute('mask', 'url(#' + maskId + ')');
      return path;
    }
    const wave = `C${f(W * .22)} ${f(G - 6)} ${f(W * .38)} ${f(G + 5)} ${f(W * .52)} ${f(G)} S${f(W * .84)} ${f(G - 5)} ${W} ${f(G)}`;
    const parts = [
      defs,
      svg('path', {class: 'soil', d: `M0 ${f(G)} ${wave} L${W} ${H} L0 ${H}Z`}),
      svg('path', {class: 'ground', d: `M0 ${f(G)} ${wave}`}),
      svg('path', {class: 'root', d: `M200 ${f(G)} q-8 12 -22 22 M200 ${f(G)} q2 16 4 30 M200 ${f(G)} q10 8 24 16`}),
    ];
    const leaves = [];
    const specs = [
      {from: [200, G + 2], to: [200, 246], w1: 15, w2: 11, cls: 'mature', delay: 0, key: 'trunk'},
      {from: [200, 300], to: [112, 228], w1: 8.5, w2: 5.5, cls: 'mature', delay: 180, key: 'l1', leaf: {status: 'passed', size: 36, rot: -24, delay: 640, veins: true, count: 3}},
      {from: [200, 286], to: [296, 220], w1: 8.2, w2: 5.2, cls: 'mature', delay: 320, key: 'r1', leaf: {status: 'passed', size: 34, rot: 22, delay: 820, veins: true, count: 2}},
      {from: [200, 258], to: [142, 162], w1: 7, w2: 4.6, cls: 'young', delay: 520, key: 'l2', leaf: {status: 'current', size: 32, rot: -14, delay: 1040, count: 2}},
      {from: [200, 250], to: [262, 150], w1: 6.4, w2: 4.2, cls: 'young', delay: 700, key: 'r2', leaf: {status: 'available', size: 28, rot: 8, delay: 1220}},
      {from: [200, 246], to: [198, 112], w1: 5.4, w2: 3.6, cls: 'young', delay: 880, key: 'crown', leaf: {status: 'locked', size: 24, rot: 0, delay: 1400}},
    ];
    for (const spec of specs) {
      parts.push(limb(artwork.curve(spec.from[0], spec.from[1], spec.to[0], spec.to[1]), spec.w1, spec.w2, spec.cls, spec.key, spec.delay));
      if (spec.leaf) leaves.push(leafGroup({...spec.leaf, at: spec.to}));
    }
    const futures = [[198, 112, 154, 72, 1560], [198, 112, 248, 68, 1680]].map(([x1, y1, x2, y2, delay]) => {
      const path = svg('path', {class: 'br-future a-fade', d: artwork.centerline(artwork.curve(x1, y1, x2, y2))});
      path.style.setProperty('--d', delay + 'ms');
      return path;
    });
    host.setAttribute('viewBox', `0 0 ${W} ${H}`);
    host.replaceChildren(...parts, ...leaves, ...futures);
  }

  function arm() {
    clearInterval(timer);
    timer = 0;
    if (!motion.matches) timer = setInterval(draw, 7800);
  }
  draw();
  arm();
  motion.addEventListener('change', () => { draw(); arm(); });
})();
