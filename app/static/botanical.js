/* Original SVG artwork and animation from the supplied Claude prototype. */
'use strict';
window.SkillTreeBotanical = (() => {
const f = v => Math.round(v * 10) / 10;
function bez(a, b, c, d, t) { const u = 1 - t; return u * u * u * a + 3 * u * u * t * b + 3 * u * t * t * c + t * t * t * d; }
function dbez(a, b, c, d, t) { const u = 1 - t; return 3 * u * u * (b - a) + 6 * u * t * (c - b) + 3 * t * t * (d - c); }
function curve(x1, y1, x2, y2) { const k = (y1 - y2) * .5; return [x1, y1, x1, y1 - k, x2, y2 + k, x2, y2]; }
function centerline(c) { return `M${f(c[0])} ${f(c[1])} C${f(c[2])} ${f(c[3])} ${f(c[4])} ${f(c[5])} ${f(c[6])} ${f(c[7])}`; }
function taper(c, w1, w2) {
  const left = [], right = [], N = 22;
  for (let i = 0; i <= N; i++) {
    const t = i / N, px = bez(c[0], c[2], c[4], c[6], t), py = bez(c[1], c[3], c[5], c[7], t);
    let dx = dbez(c[0], c[2], c[4], c[6], t), dy = dbez(c[1], c[3], c[5], c[7], t); const len = Math.hypot(dx, dy) || 1; dx /= len; dy /= len;
    const w = (w1 + (w2 - w1) * t) / 2;
    left.push(`${f(px - dy * w)} ${f(py + dx * w)}`); right.push(`${f(px + dy * w)} ${f(py - dx * w)}`);
  }
  return `M${left.join(' L')} L${right.reverse().join(' L')}Z`;
}
function tiny(l) { const w = l * .38; return `M0 0 C${f(w)} ${f(-l * .25)} ${f(w * .8)} ${f(-l * .8)} 0 ${f(-l)} C${f(-w * .8)} ${f(-l * .8)} ${f(-w)} ${f(-l * .25)} 0 0Z`; }
function leaf(theme, s, status, k, veinCls = '') {
  let shape = '', veins = '';
  if (theme === 'math') { const w = s * .34; shape = `<path class="lf" d="M0 0 L${f(w)} ${f(-s * .44)} L0 ${f(-s)} L${f(-w)} ${f(-s * .44)}Z"/>`; }
  else if (theme === 'lang') shape = `<path class="lf" d="M0 0 C${f(s * .52)} ${f(-s * .16)} ${f(s * .46)} ${f(-s * .8)} 0 ${f(-s)} C${f(-s * .46)} ${f(-s * .8)} ${f(-s * .52)} ${f(-s * .16)} 0 0Z"/>`;
  else if (theme === 'general') shape = `<path class="stalk" d="M0 0 L0 ${f(-s * .34)}"/><path class="lf" d="M0 ${f(-s * .3)} C${f(-s * .16)} ${f(-s * .4)} ${f(-s * .54)} ${f(-s * .62)} ${f(-s * .5)} ${f(-s * .9)} Q${f(-s * .26)} ${f(-s * 1.06)} ${f(-s * .04)} ${f(-s * .95)} L0 ${f(-s * .84)} L${f(s * .04)} ${f(-s * .95)} Q${f(s * .26)} ${f(-s * 1.06)} ${f(s * .5)} ${f(-s * .9)} C${f(s * .54)} ${f(-s * .62)} ${f(s * .16)} ${f(-s * .4)} 0 ${f(-s * .3)}Z"/>`;
  else {
    const pairs = k + 2; let pin = '';
    for (let i = 0; i < pairs; i++) {
      const y = -s * (.2 + i * (.62 / pairs)), len = s * (.38 - i * (.2 / pairs));
      pin += `<path class="lf" transform="translate(0 ${f(y)}) rotate(-58)" d="${tiny(len)}"/><path class="lf" transform="translate(0 ${f(y)}) rotate(58)" d="${tiny(len)}"/>`;
    }
    shape = `<path class="rachis" d="M0 0 L0 ${f(-s * .9)}"/>${pin}<path class="lf" transform="translate(0 ${f(-s * .84)})" d="${tiny(s * .2)}"/>`;
  }
  if (status === 'passed' && theme !== 'code') {
    // One lateral vein per learning objective; ginkgo veins fan out instead.
    if (theme === 'general') {
      for (let j = 0; j <= k; j++) { const u = j / k, ex = -s * .36 + u * s * .72; veins += `<path class="vein ${veinCls}" pathLength="1" d="M0 ${f(-s * .34)} L${f(ex)} ${f(-s * .86 + Math.abs(ex) * .05)}"/>`; }
    } else {
      veins = `<path class="vein ${veinCls}" pathLength="1" d="M0 ${f(-s * .06)} L0 ${f(-s * .9)}"/>`;
      const reach = theme === 'math' ? s * .2 : s * .27;
      for (let i = 0; i < k; i++) { const t = k === 1 ? .5 : .28 + .4 * i / (k - 1), sd = i % 2 ? 1 : -1; veins += `<path class="vein ${veinCls}" pathLength="1" d="M0 ${f(-s * t)} Q${f(sd * reach * .5)} ${f(-s * (t + .04))} ${f(sd * reach)} ${f(-s * (t + .15))}"/>`; }
    }
  }
  let flower = '';
  if (status === 'passed' && theme === 'lang') {
    const cy = -s * 1.02, r = s * .11;
    for (let i = 0; i < 5; i++) { const a = i / 5 * Math.PI * 2; flower += `<circle class="pet" cx="${f(Math.cos(a) * r * 1.15)}" cy="${f(cy + Math.sin(a) * r * 1.15)}" r="${f(r)}"/>`; }
    flower += `<circle class="ctr" cx="0" cy="${f(cy)}" r="${f(r * .6)}"/>`;
  }
  return shape + veins + flower;
}
function bud(s, open) {
  const r = s * (open ? .27 : .2);
  const body = `<path class="${open ? 'bud-open' : 'bud-locked'}" d="M0 0 C${f(r)} ${f(-r * .45)} ${f(r * .85)} ${f(-r * 1.75)} 0 ${f(-r * 2.6)} C${f(-r * .85)} ${f(-r * 1.75)} ${f(-r)} ${f(-r * .45)} 0 0Z"/>`;
  return open ? body + `<path class="sepal" d="M0 -1 Q${f(-r * .9)} ${f(-r * .25)} ${f(-r * 1.25)} ${f(-r * 1.15)}"/><path class="sepal" d="M0 -1 Q${f(r * .9)} ${f(-r * .25)} ${f(r * 1.25)} ${f(-r * 1.15)}"/>` : body;
}
function burst(svg, x, y) {
  const ns = 'http://www.w3.org/2000/svg', g = document.createElementNS(ns, 'g');
  svg.appendChild(g);
  for (let i = 0; i < 18; i++) {
    const c = document.createElementNS(ns, 'circle');
    c.setAttribute('cx', x); c.setAttribute('cy', y); c.setAttribute('r', (1.4 + Math.random() * 2.2).toFixed(1)); c.setAttribute('class', 'pollen');
    g.appendChild(c);
    const ang = -Math.PI / 2 + (Math.random() - .5) * 2.4, dist = 40 + Math.random() * 75;
    c.animate([{ transform: 'translate(0px,0px)', opacity: 0 }, { opacity: 1, offset: .15 }, { transform: `translate(${(Math.cos(ang) * dist).toFixed(1)}px,${(Math.sin(ang) * dist).toFixed(1)}px)`, opacity: 0 }], { duration: 1200 + Math.random() * 700, delay: 450 + Math.random() * 250, easing: 'cubic-bezier(.2,.7,.3,1)', fill: 'both' });
  }
  setTimeout(() => g.remove(), 3200);
}
return {leaf,bud,curve,centerline,taper,burst};
})();
