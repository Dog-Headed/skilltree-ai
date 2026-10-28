/* SkillTree controls: small progressive enhancements for the stationery controls.
   Every helper takes an existing element, adds behaviour and returns it; nothing here talks to the API.
   Elements it creates carry .ctl-enh so they can be told apart from server-rendered markup. */
'use strict';
window.SkillTreeControls = (() => {
  const make = (tag, cls, text) => { const n = document.createElement(tag); n.className = 'ctl-enh' + (cls ? ' ' + cls : ''); if (text != null) n.textContent = text; return n; };
  // Wrappers only regroup existing fields, so they stay visible even where the enhancements are switched off.
  const wrapper = (tag, cls) => { const n = document.createElement(tag); n.className = cls; return n; };
  const svg = (tag, attrs = {}) => { const n = document.createElementNS('http://www.w3.org/2000/svg', tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); return n; };
  const fire = el => el.dispatchEvent(new Event('input', { bubbles: true }));

  /* The button the learner just pressed. Safari does not focus buttons on click, so
     document.activeElement is not reliable; this remembers the last press for two seconds. */
  let lastPress = null;
  const note = event => { const b = event.target.closest?.('.btn'); if (b) lastPress = { button: b, at: Date.now() }; };
  document.addEventListener('pointerdown', note, true);
  document.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') note(event); }, true);
  const pressed = () => lastPress && Date.now() - lastPress.at < 2000 && lastPress.button.isConnected ? lastPress.button : null;

  /* A sprout grows inside the button while work is pending.
     const sprout = grow(button); … sprout.done() | sprout.fail() */
  function grow(button) {
    if (!button) return { done() {}, fail() {}, clear() {} };
    let timer;
    const clear = () => { clearTimeout(timer); delete button.dataset.state; button.removeAttribute('aria-busy'); };
    button.dataset.state = 'growing'; button.setAttribute('aria-busy', 'true');
    return {
      done(hold = 900) { button.dataset.state = 'grown'; button.removeAttribute('aria-busy'); timer = setTimeout(clear, hold); },
      fail(hold = 900) { button.dataset.state = 'wilted'; button.removeAttribute('aria-busy'); timer = setTimeout(clear, hold); },
      clear,
    };
  }

  /* The seed beside "你想学会什么？" wakes up as the goal becomes specific. */
  const seedMessages = ['写下目标，种子会醒来', '再具体一点：想做到什么？', '好，再说说要用它来做什么', '很具体，可以规划一条好路线了'];
  function seedLevel(text) {
    const t = text.trim();
    if (!t) return 0;
    if (t.length >= 22 && /(能|会|学会|写|做|看懂|读懂|听懂|说|通过|解决|完成|搭建|分析|解释|应用)/.test(t)) return 3;
    return t.length >= 12 ? 2 : 1;
  }
  function seedMeter(textarea) {
    if (!textarea || textarea.dataset.seed) return textarea;
    textarea.dataset.seed = 'on';
    const wrap = wrapper('div', 'seed-wrap'); textarea.before(wrap); wrap.append(textarea);
    const meter = make('div', 'seed-meter'); const label = make('span'); label.setAttribute('aria-live', 'polite');
    const art = svg('svg', { viewBox: '-15 -26 30 30', 'aria-hidden': 'true' });
    art.append(svg('ellipse', { class: 'seed', cx: 0, cy: 1, rx: 5.5, ry: 3.2 }), svg('path', { class: 'stem', d: 'M0 -1 C0 -6 -1 -10 0 -14' }),
      svg('path', { class: 'cot l', d: 'M0 -10 C-4 -10 -9 -13 -10 -18 C-5 -18 -1 -15 0 -10Z' }), svg('path', { class: 'cot r', d: 'M0 -12 C4 -12 9 -15 10 -20 C5 -20 1 -17 0 -12Z' }),
      svg('path', { class: 'cot t', d: 'M0 -14 C-2.5 -17 -2 -22 0 -24 C2 -22 2.5 -17 0 -14Z' }));
    meter.append(label, art); wrap.append(meter);
    const update = () => { const level = seedLevel(textarea.value); if (meter.dataset.level !== String(level)) { meter.dataset.level = level; label.textContent = seedMessages[level]; } };
    textarea.addEventListener('input', update); update();
    return textarea;
  }

  /* Ready-made follow-up questions above the composer; picking one fills the box. */
  const defaultAsks = [['举个例子', '能再举一个具体的例子吗？'], ['换个说法', '能换一种更通俗的说法解释吗？'],
    ['联系前面', '这一节和前面学过的内容有什么联系？'], ['考考我', '出一道小题考考我，先别告诉我答案。']];
  function quickAsks(textarea, { asks = defaultAsks, anchor = textarea.closest('form') || textarea } = {}) {
    const row = make('div', 'quick-asks'); row.setAttribute('role', 'group'); row.setAttribute('aria-label', '常用追问');
    for (const [label, question] of asks) {
      const chip = make('button', 'ask-chip', label); chip.type = 'button'; chip.title = question;
      chip.addEventListener('click', () => { textarea.value = question; fire(textarea); textarea.focus(); textarea.setSelectionRange(question.length, question.length); });
      row.append(chip);
    }
    anchor.before(row);
    return row;
  }

  function autoGrow(textarea) {
    const fit = () => { textarea.style.height = 'auto'; textarea.style.height = textarea.scrollHeight + 2 + 'px'; };
    textarea.addEventListener('input', fit); requestAnimationFrame(fit);
    return textarea;
  }

  /* Enter sends, Shift+Enter starts a new line. Enter that confirms an IME candidate is left alone. */
  function enterToSend(form, textarea, { hint = true } = {}) {
    textarea.addEventListener('keydown', event => {
      if (event.key !== 'Enter' || event.shiftKey || event.ctrlKey || event.altKey || event.metaKey || event.isComposing || event.keyCode === 229) return;
      event.preventDefault(); form.requestSubmit();
    });
    if (hint) form.after(make('p', 'composer-hint', 'Enter 发送 · Shift + Enter 换行'));
    return form;
  }

  /* Letters A–Z or digits 1–9 pick an option in the question being answered. */
  function choiceKeys(root) {
    const sets = () => [...root.querySelectorAll('fieldset')].filter(f => f.querySelector('.answer-choice input'));
    if (!sets().length) return root;
    let last = sets()[0];
    const remember = event => { const f = event.target.closest?.('fieldset'); if (f && root.contains(f)) last = f; };
    root.addEventListener('focusin', remember); root.addEventListener('pointerdown', remember);
    const first = sets()[0], legend = first.querySelector('legend');
    const most = Math.min(9, Math.max(...sets().map(f => f.querySelectorAll('.answer-choice input').length)));
    const hint = make('p', 'choice-keys'); hint.append('键盘：');
    for (const [i, key] of ['A', String.fromCharCode(64 + most), '1', String(most)].entries()) { const k = make('kbd', '', key); hint.append(k, ['–', ' 或 ', '–', ' 选择当前题'][i]); }
    (legend ? legend.nextElementSibling || legend : first.firstChild)?.before?.(hint);
    const onKey = event => {
      if (!root.isConnected) { document.removeEventListener('keydown', onKey); return; }
      if (event.ctrlKey || event.metaKey || event.altKey || event.isComposing) return;
      const target = event.target;
      if (target.closest?.('textarea, input:not([type="radio"]):not([type="checkbox"]), select, [contenteditable="true"]')) return;
      const key = event.key.toLowerCase();
      const index = /^[1-9]$/.test(key) ? Number(key) - 1 : /^[a-z]$/.test(key) ? key.charCodeAt(0) - 97 : -1;
      if (index < 0) return;
      const holder = root.contains(document.activeElement) ? document.activeElement.closest('fieldset') || last : last;
      const option = holder?.querySelectorAll('.answer-choice input')[index];
      if (!option || option.disabled) return;
      event.preventDefault(); option.click(); option.focus({ preventScroll: true }); last = holder;
    };
    document.addEventListener('keydown', onKey);
    return root;
  }

  /* Repeats how a numeric answer was read. Format only: it never says whether the value is right. */
  const numberPattern = /^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([^\d\s][\s\S]*)?$/;
  function numericEcho(input) {
    const echo = make('div', 'numeric-echo'); echo.setAttribute('aria-live', 'polite'); input.after(echo);
    const update = () => {
      const value = input.value.trim(); echo.replaceChildren(); delete echo.dataset.state;
      if (!value) { echo.append('写数值和单位，例如 2、1.5 cm 或 3e-2'); return; }
      const match = value.match(numberPattern);
      if (!match) { echo.dataset.state = 'unclear'; echo.append('这不像一个数值，可以写成 2、1.5 cm 或 3e-2'); return; }
      echo.append('已识别为', make('b', '', match[1]), match[2] ? '单位' : '（无单位）');
      if (match[2]) echo.append(make('b', '', match[2].trim()));
    };
    input.addEventListener('input', update); update();
    return input;
  }

  /* Length and draft reassurance under a written answer. */
  function draftMeta(textarea, { saved = true } = {}) {
    const meta = make('div', 'answer-meta'), count = make('span'), state = make('span', saved ? 'saved' : '');
    meta.append(count, state); textarea.after(meta);
    const max = Number(textarea.maxLength) > 0 ? textarea.maxLength : 0;
    const time = () => new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    const update = typed => { count.textContent = `${textarea.value.length}${max ? ' / ' + max : ''} 字`; if (saved) state.textContent = typed ? `草稿已保存在本机 · ${time()}` : textarea.value ? '草稿已保存在本机' : '草稿会自动保存在本机'; };
    textarea.addEventListener('input', () => update(true)); update(false);
    return textarea;
  }

  /* A file input becomes soil to drop material into. The input still covers the zone, so drop and click are native. */
  function soilDrop(input, { title = '把资料放进土壤', hint = '拖入 TXT / Markdown，或点击选择 · 单个文件最多 128 KB' } = {}) {
    const zone = wrapper('label', 'soil-drop'); input.before(zone);
    const roots = svg('svg', { class: 'roots ctl-enh', viewBox: '0 0 120 34', 'aria-hidden': 'true' });
    roots.setAttribute('viewBox', '0 -10 120 44');
    roots.append(svg('path', { class: 'soil-line', d: 'M30 14 C50 12 70 16 90 14' }), svg('path', { class: 'sprout', d: 'M60 14 C60 8 59 3 60 -2' }),
      svg('path', { class: 'bud', d: 'M60 1 C56 0 52 -3 51 -8 C56 -8 59 -5 60 1Z' }), svg('path', { class: 'bud', d: 'M60 -1 C64 -2 68 -5 69 -10 C64 -10 61 -7 60 -1Z' }),
      svg('path', { d: 'M60 14 C58 20 52 24 44 30' }), svg('path', { d: 'M60 14 C61 22 60 27 61 33' }), svg('path', { d: 'M60 14 C63 20 70 23 78 28' }));
    const name = make('span', 'soil-file');
    zone.append(input, roots, make('strong', '', title), make('span', '', hint), name);
    let depth = 0;
    zone.addEventListener('dragenter', () => { depth++; zone.dataset.over = ''; });
    zone.addEventListener('dragleave', () => { if (--depth <= 0) { depth = 0; delete zone.dataset.over; } });
    zone.addEventListener('drop', () => { depth = 0; delete zone.dataset.over; });
    input.addEventListener('change', () => { const file = input.files?.[0]; if (file) { zone.dataset.file = ''; name.textContent = file.name; } else { delete zone.dataset.file; name.textContent = ''; } });
    return zone;
  }

  /* Destructive actions confirm by holding the button for about a second (pointer, Enter or Space). */
  function holdToConfirm(button, onConfirm, { ms = 1100 } = {}) {
    button.dataset.hold = ''; button.setAttribute('aria-description', '按住约 1 秒确认');
    let start = 0, frame = 0, done = false;
    const set = v => button.style.setProperty('--hold', v.toFixed(3));
    const stop = () => { cancelAnimationFrame(frame); start = 0; delete button.dataset.holding; if (!done) set(0); };
    const tick = now => { const p = Math.min(1, (now - start) / ms); set(p); if (p >= 1) { done = true; stop(); onConfirm(); setTimeout(() => { done = false; set(0); }, 600); } else frame = requestAnimationFrame(tick); };
    const begin = event => { if (start || button.disabled) return; if (event.type === 'keydown' && ![' ', 'Enter'].includes(event.key)) return; event.preventDefault(); start = performance.now(); button.dataset.holding = ''; frame = requestAnimationFrame(tick); };
    button.addEventListener('pointerdown', begin); button.addEventListener('keydown', begin);
    for (const type of ['pointerup', 'pointerleave', 'pointercancel', 'keyup', 'blur']) button.addEventListener(type, stop);
    button.addEventListener('click', event => event.preventDefault());
    return button;
  }

  function passwordToggle(input) {
    const wrap = wrapper('div', 'password-field'); input.before(wrap); wrap.append(input);
    const reveal = make('button', 'reveal', '显示'); reveal.type = 'button'; reveal.setAttribute('aria-pressed', 'false'); reveal.setAttribute('aria-label', '显示密码');
    if (input.id) reveal.setAttribute('aria-controls', input.id);
    reveal.addEventListener('click', () => { const show = input.type === 'password'; input.type = show ? 'text' : 'password'; reveal.textContent = show ? '隐藏' : '显示';
      reveal.setAttribute('aria-pressed', String(show)); reveal.setAttribute('aria-label', show ? '隐藏密码' : '显示密码'); input.focus(); });
    wrap.append(reveal);
    return input;
  }

  function capsLockHint(input, hint) {
    const check = event => { if (event.getModifierState) hint.hidden = !event.getModifierState('CapsLock'); };
    input.addEventListener('keydown', check); input.addEventListener('keyup', check); input.addEventListener('blur', () => { hint.hidden = true; });
    return input;
  }

  return { grow, pressed, seedMeter, seedLevel, quickAsks, autoGrow, enterToSend, choiceKeys, numericEcho, draftMeta, soilDrop, holdToConfirm, passwordToggle, capsLockHint };
})();
