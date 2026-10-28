/* The page consumes public DTOs only. Model/tool permissions stay on the server.
 * All untrusted material is rendered with text nodes; no HTML is interpreted. */
'use strict';
(() => {
  let authSession = null;
  window.addEventListener('storage', event => { if (event.key === 'skilltree.auth.changed') location.reload(); });
  window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
  const $ = (id) => document.getElementById(id);
  const state = { projects: [], legacyProjects: [], tab: 'current', id: null, view: null,
    busy: false, loading: false, capabilities: [], packs: [], selectedPack: null, menu: null,
    loadSequence: 0, pendingWrite: null };
  let garden;
  let accountStoragePrefix = '';
  const storage = {
    read(key, fallback = null) { try { return JSON.parse(localStorage.getItem('skilltree.v3.' + accountStoragePrefix + key)) ?? fallback; } catch { return fallback; } },
    write(key, value) { try { localStorage.setItem('skilltree.v3.' + accountStoragePrefix + key, JSON.stringify(value)); } catch { /* Storage can be disabled. */ } },
    remove(key) { try { localStorage.removeItem('skilltree.v3.' + accountStoragePrefix + key); } catch { /* No stored draft. */ } },
  };
  const uuid = () => crypto.randomUUID();
  const creationProjectId = (request) => request?.request_id ? 'v3_' + request.request_id.replaceAll('-', '') : null;
  function finishCreation(projectId) {
    // Keep only unresolved creation attempts, including across reloads. Do not
    // clear a different tab's newer request when an older response arrives.
    if (projectId && creationProjectId(storage.read('creation-request')) === projectId) storage.remove('creation-request');
  }
  const labels = { profile_review: '确认学习档案', materials_required: '准备学习资料', plan_review: '确认学习计划',
    learning: '正在学习', quiz: '等待作答', assessment_review: '需要复核', budget_exhausted: '额度暂时用完',
    exploring: '探索学习', paused: '已暂停', completed: '学习已完成', error: '需要恢复', running: '正在处理', legacy_readonly: 'V2 只读历史' };
  const actionLabels = { confirm_profile: '确认档案与范围', update_profile: '修改档案', import_material: '导入资料', adjust_scope: '调整学习范围',
    choose_exploration: '明确进入探索模式', replan: '重新规划', confirm_plan: '确认这条路线', adjust_plan: '调整计划', begin: '开始学习', begin_learning: '开始学习',
    ask: '发送问题', start_quiz: '我准备好了，开始小测', return_to_current: '返回当前节点', submit_answer: '提交这次小测',
    view_feedback: '查看评价反馈', annotate_dispute: '补充说明', replace_assessment: '申请换题', rest: '休息，保留当前进度', retry_3: '再给 3 次闯关机会',
    continue_with_new_budget: '追加一次额度，继续', retry: '重试这次操作', return_to_teaching: '返回教学' };
  const capabilityNames = { choice_exact: '选择题', numeric_scalar: '数值与单位', text_rubric: '文字与步骤', text_explanation: '文字讲解', text_question_answer: '文字问答' };
  const list = (value) => Array.isArray(value) ? value : [];
  const actions = () => list(state.view?.allowed_actions);
  const allowed = (action) => actions().includes(action);
  const isLegacy = () => false;
  const currentName = (p) => p?.display_name || p?.profile?.topic || p?.topic || p?.goal || '未命名学习';
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
      else if (key === 'checked' || key === 'disabled' || key === 'required' || key === 'multiple') node[key] = Boolean(value);
      else if (key === 'value') node.value = value;
      else node.setAttribute(key, String(value));
    }
    for (const child of children.flat(Infinity)) if (child !== null && child !== undefined && child !== false) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    return node;
  }
  function button(text, callback, style = '') { return el('button', { type: 'button', class: 'btn ' + style, text, onclick: callback, 'data-write': 'true', disabled: state.busy }); }
  function dismissButton() { return el('button', { type: 'button', class: 'btn', text: '取消', onclick: closeModal }); }
  function chip(text, kind = '') { return el('span', { class: 'chip ' + kind, text }); }
  function showMessage(message, kind = '') { $('message').textContent = message; $('message').className = 'message ' + kind; $('message').hidden = !message; }
  let busyTimer = null;
  function busy(value, text = null) {
    // Long AI steps show how long they have been waiting instead of a bare spinner.
    if (value && !state.busy) { const started = Date.now(); $('busy-elapsed').textContent = ''; clearInterval(busyTimer); busyTimer = setInterval(() => { const s = Math.round((Date.now() - started) / 1000); $('busy-elapsed').textContent = s >= 3 ? `已等待 ${s} 秒` : ''; }, 1000); }
    if (!value) { clearInterval(busyTimer); busyTimer = null; $('busy-elapsed').textContent = ''; }
    state.busy = value; $('busy-notice').hidden = !value;
    if (text) $('busy-text').textContent = text;
    const grading = value && $('busy-text').textContent.includes('评分');
    $('grading-state').hidden = !grading; $('content').hidden = grading;
    document.body.setAttribute('aria-busy', String(value));
    document.querySelectorAll('[data-write],form button[type=submit],.project-link,.project-more,#view-tabs button').forEach(n => { n.disabled = value; });
    $('new-project').disabled = value; $('refresh-project').disabled = value;
    watchRunningStatus();
    // Inputs remain editable, but their submission captures immutable identities.
  }
  async function get(url, { signal } = {}) {
    const controller = signal ? null : new AbortController();
    const timeout = controller ? setTimeout(() => controller.abort(), 15000) : null;
    try {
      const response = await fetch(url, { headers: { Accept: 'application/json' }, cache: 'no-store', signal: signal || controller.signal });
      if (response.status === 401) { location.replace('/login?next=' + encodeURIComponent(location.pathname + location.search + location.hash)); throw Object.assign(new Error('请重新登录。'), { status: 401 }); }
      let data; try { data = await response.json(); } catch { throw new Error('服务暂时没有返回可读结果。请刷新状态。'); }
      if (!response.ok) throw Object.assign(new Error(data?.error?.message || '读取失败，请稍后刷新。'), { status: response.status });
      return data;
    } finally { if (timeout) clearTimeout(timeout); }
  }
  let statusWatch = null;
  function stopStatusWatch() {
    if (!statusWatch) return;
    clearTimeout(statusWatch.timer); statusWatch.controller?.abort(); statusWatch = null;
  }
  function watchRunningStatus() {
    if (state.busy || !state.id || state.view?.page_state !== 'running') { stopStatusWatch(); return; }
    if (statusWatch?.id === state.id) return;
    stopStatusWatch();
    const watch = { id: state.id, started: Date.now(), attempts: 0, errors: 0, timer: null, controller: null };
    statusWatch = watch;
    async function poll() {
      if (statusWatch !== watch) return;
      if (state.busy || state.id !== watch.id || state.view?.page_state !== 'running') { stopStatusWatch(); return; }
      if (watch.attempts >= 60 || Date.now() - watch.started >= 600000) {
        stopStatusWatch(); showMessage('自动查询已暂停。可以点击“刷新状态”读取结果，进度已保留。', 'warn'); return;
      }
      watch.attempts++; watch.controller = new AbortController();
      const controller = watch.controller, sequence = ++state.loadSequence;
      const timeout = setTimeout(() => controller.abort(), 12000);
      try {
        const view = await get('/projects/' + encodeURIComponent(watch.id), { signal: controller.signal });
        if (statusWatch !== watch || state.id !== watch.id || sequence !== state.loadSequence) return;
        watch.errors = 0; state.view = view; render();
        if (view.page_state !== 'running') {
          const failed = Boolean(view.error_type) || ['error', 'budget_exhausted'].includes(view.page_state);
          showMessage(failed ? '后台处理已结束，这一步未能完成。请查看当前提示，进度已保留。' : '后台处理已完成，已更新最新结果。', failed ? 'warn' : '');
          refreshList().catch(() => {});
        }
      } catch (error) {
        if (statusWatch !== watch) return;
        if ([401, 403, 404].includes(error.status)) {
          stopStatusWatch(); showMessage('当前无法读取此项目，请重新登录或刷新学习记录。', 'warn'); return;
        }
        if (++watch.errors === 3) showMessage('连接不稳定，正在继续查询已保存的状态；不会重复提交操作。', 'warn');
      } finally {
        clearTimeout(timeout); watch.controller = null;
        if (statusWatch === watch) watch.timer = setTimeout(poll, Math.min(2000 + watch.attempts * 500, 10000));
      }
    }
    watch.timer = setTimeout(poll, 1500);
  }
  function asProjects(data) { return list(Array.isArray(data) ? data : data?.projects); }
  async function refreshList() {
    const legacy = isLegacy(); const data = asProjects(await get(legacy ? '/legacy/projects' : '/projects'));
    if (legacy) state.legacyProjects = data; else state.projects = data;
    renderList(); return data;
  }
  async function loadProject(id, { announce = false } = {}) {
    const sequence = ++state.loadSequence; const legacy = isLegacy();
    const view = await get((legacy ? '/legacy/projects/' : '/projects/') + encodeURIComponent(id));
    if (sequence !== state.loadSequence || legacy !== isLegacy()) return;
    state.id = id; state.view = view;
    finishCreation(view.project_id);
    storage.write('selection', { id, tab: state.tab });
    render(); if (announce) showMessage('已读取最新状态，未调用模型。');
    return view;
  }
  async function selectProject(id) {
    if (state.busy) return; closeMenu(); closeSidebar(); showMessage('');
    try { await loadProject(id); window.scrollTo({ top: 0, behavior: 'instant' }); } catch (error) { showMessage(error.message, 'error'); }
  }
  async function switchTab(tab) {
    if (state.busy) return; state.tab = tab; state.id = null; state.view = null; ++state.loadSequence;
    closeMenu(); render(); showMessage('');
    try { await refreshList(); } catch (error) { showMessage(error.message, 'error'); }
  }
  function closeSidebar() { $('sidebar').classList.remove('open'); $('sidebar-shade').hidden = true; $('mobile-menu').setAttribute('aria-expanded', 'false'); }
  function closeMenu() { state.menu?.remove(); state.menu = null; document.querySelectorAll('.project-more').forEach(n => n.setAttribute('aria-expanded', 'false')); }
  function projectMenu(p, trigger) {
    const already = state.menu?.dataset.project === p.project_id; closeMenu(); if (already) return;
    const menu = el('div', { class: 'project-menu', role: 'menu', 'data-project': p.project_id });
    menu.append(el('button', { role: 'menuitem', text: '重命名', onclick: () => { closeMenu(); renameProject(p); } }),
      el('button', { role: 'menuitem', class: 'danger', text: '删除学习记录', onclick: () => { closeMenu(); deleteProject(p); } }));
    menu.addEventListener('keydown', e => { const items = [...menu.querySelectorAll('button')]; const i = items.indexOf(document.activeElement);
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus(); }
      if (e.key === 'Escape') { closeMenu(); trigger.focus(); }
    });
    document.body.append(menu); const rect = trigger.getBoundingClientRect();
    menu.style.left = Math.max(8, Math.min(rect.left, innerWidth - menu.offsetWidth - 8)) + 'px';
    menu.style.top = Math.max(8, Math.min(rect.bottom + 4, innerHeight - menu.offsetHeight - 8)) + 'px';
    state.menu = menu; trigger.setAttribute('aria-expanded', 'true'); menu.querySelector('button').focus({ preventScroll: true });
  }
  function renderList() {

    $('list-label').textContent = isLegacy() ? 'V2 只读历史记录' : '我的学习';
    const items = isLegacy() ? state.legacyProjects : state.projects; const target = $('project-list'); target.replaceChildren();
    if (!items.length) target.append(el('p', { class: 'empty', text: isLegacy() ? '暂无可读取的 V2 历史。' : '还没有学习记录，从一个目标开始。' }));
    for (const p of items) {
      const id = p.project_id || p.id; const name = currentName(p); const row = el('div', { class: 'project-row' + (id === state.id ? ' active' : '') });
      const open = el('button', { class: 'project-link', type: 'button', 'aria-current': id === state.id ? 'page' : null, onclick: () => selectProject(id), disabled: state.busy },
        el('span', { class: 'project-name', text: name, title: name }), el('span', { class: 'project-meta', text: (isLegacy() ? 'V2 · 只读' : 'V3') + ' · ' + (labels[p.page_state] || p.status_label || '学习记录') }));
      row.append(open);
      if (!isLegacy()) row.append(el('button', { class: 'project-more', text: '⋯', type: 'button', 'aria-label': name + ' 的更多操作', 'aria-haspopup': 'menu', 'aria-expanded': 'false', disabled: state.busy,
        onclick: e => { e.stopPropagation(); projectMenu({ ...p, project_id: id }, e.currentTarget); } }));
      target.append(row);
    }
  }
  function openModal(title, body) { closeMenu(); $('modal').classList.remove('source-drawer'); $('modal-title').textContent = title; $('modal-content').replaceChildren(body); if (!$('modal').open) $('modal').showModal(); }
  function closeModal() { $('modal').close(); }
  function field(label, input, hint = '', full = false) {
    const id = input.id || 'field-' + uuid(); input.id = id;
    return el('div', { class: 'field' + (full ? ' full' : '') }, el('label', { for: id, text: label }), input, hint ? el('small', { text: hint }) : null);
  }
  function input(name, value = '', attrs = {}) { return el('input', { name, value, ...attrs }); }
  function textArea(name, value = '', attrs = {}) { return el('textarea', { name, value, ...attrs }); }
  function lines(text) { return String(text || '').split(/\n/).map(s => s.trim()).filter(Boolean); }
  function safeLink(url) { try { const parsed = new URL(url); return ['https:', 'http:'].includes(parsed.protocol) ? parsed.href : null; } catch { return null; } }
  function mathText(text) {
    return text.replace(/\\(?:begin|end)\{(?:equation\*?|align\*?|aligned|displaymath)\}/g, '')
      .replace(/\\(?:left|right)\s*/g, '').replace(/\\text\{([^{}]*)\}/g, '$1')
      .replace(/\\frac\{([^{}]*)\}\{([^{}]*)\}/g, '($1)/($2)').replace(/\\sqrt\{([^{}]*)\}/g, '√($1)')
      .replace(/\\(times|cdot|div|leq?|geq?|neq?|approx|infty|pm|to|rightarrow|Rightarrow|pi|alpha|beta|theta|Delta|sum)\b/g,
        (_, key) => ({ times: '×', cdot: '·', div: '÷', le: '≤', leq: '≤', ge: '≥', geq: '≥', ne: '≠', neq: '≠', approx: '≈', infty: '∞', pm: '±', to: '→', rightarrow: '→', Rightarrow: '⇒', pi: 'π', alpha: 'α', beta: 'β', theta: 'θ', Delta: 'Δ', sum: '∑' })[key]);
  }
  function mathNode(source, block = false) {
    const node = el(block ? 'div' : 'span', { class: block ? 'math-block' : 'math-inline', 'aria-label': '公式：' + source });
    const converted = mathText(source); const pattern = /([_^])(?:\{([^{}]+)\}|([A-Za-z0-9+-]))/g; let cursor = 0, match;
    while ((match = pattern.exec(converted))) { node.append(document.createTextNode(converted.slice(cursor, match.index)), el(match[1] === '^' ? 'sup' : 'sub', { text: match[2] || match[3] })); cursor = pattern.lastIndex; }
    node.append(document.createTextNode(converted.slice(cursor))); return node;
  }
  function inline(text, target) {
    const pattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\$[^$\n]+\$|\\\([^\n]*?\\\)|\[[^\]\n]+\]\([^\s)]+\))/g;
    let cursor = 0, match;
    while ((match = pattern.exec(text))) {
      target.append(document.createTextNode(text.slice(cursor, match.index))); const token = match[0];
      if (token[0] === '`') target.append(el('code', { text: token.slice(1, -1) }));
      else if (token.startsWith('**')) target.append(el('strong', { text: token.slice(2, -2) }));
      else if (token[0] === '$') target.append(mathNode(token.slice(1, -1)));
      else if (token.startsWith('\\(')) target.append(mathNode(token.slice(2, -2)));
      else { const parts = /^\[([^\]]+)\]\((.+)\)$/.exec(token); const href = safeLink(parts[2]); target.append(href ? el('a', { href, target: '_blank', rel: 'noopener noreferrer', text: parts[1] }) : document.createTextNode(token)); }
      cursor = pattern.lastIndex;
    }
    target.append(document.createTextNode(text.slice(cursor)));
  }
  function markdown(text) {
    const root = el('div', { class: 'reading' }); const rows = String(text || '').replace(/\r\n?/g, '\n').split('\n');
    let index = 0;
    while (index < rows.length) {
      const line = rows[index];
      if (!line.trim()) { index++; continue; }
      const fence = /^\s*```([\w+-]*)\s*$/.exec(line);
      if (fence) { const content = []; index++; while (index < rows.length && !/^\s*```\s*$/.test(rows[index])) content.push(rows[index++]); index++;
        if (fence[1]) root.append(el('div', { class: 'code-caption', text: fence[1] })); root.append(el('pre', {}, el('code', { text: content.join('\n') }))); continue; }
      if (line.trim().startsWith('$$') || line.trim().startsWith('\\[')) {
        const marker = line.trim().startsWith('$$') ? '$$' : '\\]'; const openLength = 2; let formula = line.trim().slice(openLength); index++;
        if (!formula.endsWith(marker)) { const parts = [formula]; while (index < rows.length && !rows[index].includes(marker)) parts.push(rows[index++]); if (index < rows.length) parts.push(rows[index++].split(marker)[0]); formula = parts.join('\n'); }
        else formula = formula.slice(0, -marker.length);
        root.append(mathNode(formula.trim(), true)); continue;
      }
      const heading = /^(#{1,4})\s+(.+)$/.exec(line);
      if (heading) { const h = el('h' + Math.min(4, heading[1].length + 1)); inline(heading[2], h); root.append(h); index++; continue; }
      const listMatch = /^\s*(?:([-*])|\d+[.)])\s+(.+)$/.exec(line);
      if (listMatch) { const ordered = !listMatch[1]; const ul = el(ordered ? 'ol' : 'ul');
        while (index < rows.length) { const m = /^\s*(?:([-*])|\d+[.)])\s+(.+)$/.exec(rows[index]); if (!m || Boolean(!m[1]) !== ordered) break; const li = el('li'); inline(m[2], li); ul.append(li); index++; } root.append(ul); continue; }
      const block = line.startsWith('> ') ? el('blockquote') : el('p'); inline(line.startsWith('> ') ? line.slice(2) : line, block); root.append(block); index++;
    }
    return root;
  }
  function profileForm(profile = {}, { editing = false, action = 'update_profile', pack = null, guided = false } = {}) {
    const saved = editing ? null : storage.read('create-draft'); const p = Object.keys(profile).length ? profile : (saved || {});
    const form = el('form', { id: editing ? 'profile-edit-form' : 'create-form' });
    const goal = textArea('goal', p.goal || '', { required: true, maxlength: 4000, rows: 3, placeholder: '例如：我想从零学习 Python，能自己写一个记账小工具。' });
    const priorValue = typeof p.prior_knowledge === 'string' ? p.prior_knowledge : list(p.prior_knowledge?.self_reported).join('\n');
    const prior = textArea('prior', priorValue, { maxlength: 4000, rows: 2, placeholder: '可以写“零基础”“不确定”，或简单说说已经会什么。' });
    const grid = el('div', { class: 'form-grid' }, field('你想学会什么？', goal, '日语、Python、心理学……写下想长期探索的方向，或一个具体目标。', true), field('已有基础', prior, '可不填；让这棵树从适合你的地方开始。', true));
    window.SkillTreeControls?.seedMeter(goal);
    const total = input('time_budget_minutes', p.time_budget_minutes || 1440, { type: 'number', min: 1, max: 10080, required: true });
    const session = input('session_minutes', p.session_minutes || 30, { type: 'number', min: 1, max: 480, required: true });
    const rhythm = el('summary');
    const describeRhythm = () => { rhythm.textContent = `生长节奏 · 每次 ${session.value} 分钟，初始路线总预算 ${Number(total.value) >= 60 ? (Math.round(Number(total.value) / 60 * 10) / 10) + ' 小时' : total.value + ' 分钟'}（可调整）`; };
    total.addEventListener('input', describeRhythm); session.addEventListener('input', describeRhythm); describeRhythm();
    const advanced = el('details', { class: 'section-details' }, rhythm, el('div', { class: 'form-grid' }, field('初始路线总预算（分钟）', total, '分多次完成，不要求一天学完。调整总预算会影响路线范围。'), field('每次学习（分钟）', session, '控制每次的节奏，不会把整棵树缩成一课。')));
    form.append(grid, advanced, el('p', { class: 'muted-line', text: '创建后可直接让 AI 准备，也可以先上传讲义或内部培训文件。没有资料时整理通用知识；具体公司制度以实际文件为准。' }));
    if (pack) form.append(el('p', { class: 'welcome-note', text: '已填入示例目标，可继续编辑。示例资料可在创建后按需导入。' }));
    form.append(el('div', { class: 'actions' }, el('button', { type: 'submit', class: 'btn primary', text: editing ? '保存学习档案' : '种下这棵树', disabled: state.busy })));
    function collect() {
      return { goal: goal.value.trim(), prior_knowledge: prior.value.trim(), time_budget_minutes: Number(total.value), session_minutes: Number(session.value) };
    }
    if (!editing) form.addEventListener('input', () => storage.write('create-draft', collect()));
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (state.busy || !form.reportValidity()) return;
      const intent = collect();
      if (intent.session_minutes > intent.time_budget_minutes) { showMessage('单次学习时间不能超过总学习时间。', 'warn'); session.focus(); return; }
      if (editing) {
        const updated = { ...p, goal: intent.goal, prior_knowledge: { self_reported: intent.prior_knowledge ? [intent.prior_knowledge] : [], assessed_evidence: list(p.prior_knowledge?.assessed_evidence) }, time_budget_minutes: intent.time_budget_minutes, session_minutes: intent.session_minutes,
          bounded_goal: guided ? null : p.goal === intent.goal ? p.bounded_goal : intent.goal };
        await command(action, { profile: updated });
      } else {
        const encoded = JSON.stringify(intent); let previous = storage.read('creation-request');
        if (previous?.profile && !previous.intent) {
          // A pending request from the old form has a different HTTP contract.
          // Resolve it first; never replay its identity with a new payload.
          try { const old = await get('/projects/' + encodeURIComponent(creationProjectId(previous))); finishCreation(old.project_id); previous = null; }
          catch (error) {
            if (error.status === 404) { storage.remove('creation-request'); previous = null; }
            else { showMessage('上次创建结果暂时无法确认，请恢复连接后先刷新记录，再创建学习。', 'warn'); return; }
          }
        }
        const requestId = previous?.intent === encoded ? previous.request_id : uuid();
        storage.write('creation-request', { request_id: requestId, intent: encoded });
        state.selectedPack = pack; state.tab = 'current';
        await write('/projects', { request_id: requestId, intent }, { busyText: '正在记下这棵树的目标与起点…', success: '这棵树已种下。可以补充资料，再让 AI 规划生长路线。', after: result => {
          if (result?.project_id) { finishCreation(result.project_id); state.id = result.project_id; state.view = result; storage.remove('create-draft'); }
        } });
      }
    });
    return form;
  }
  function welcome() {
    const root = el('div'); root.append(el('div', { class: 'page-heading' }, el('div', {}, el('div', { class: 'eyebrow', text: 'YOUR NEXT LEARNING STEP' }), el('h1', { text: '从一个想学会的目标开始' }), el('p', { text: '确认范围，绑定资料，把大目标拆成有依据的小步骤。学到哪里，回来就能继续。' })), chip('通用文字学习', 'green')));
    if (isLegacy()) {
      root.append(el('div', { class: 'legacy-badge', text: '这里展示 V2 原有业务记录。历史只读，不恢复旧 Checkpoint，也不修改原来的学习数据。' }), el('div', { class: 'card' }, el('h2', { text: '从左侧选择一条历史记录' }), el('p', { class: 'muted', text: '可以查看已有计划、讲解和结果。新的学习请在 V3 中创建。' }))); return root;
    }
    const presets = el('div', { class: 'preset-row' });
    for (const pack of state.packs) presets.append(el('button', { class: 'preset-button', type: 'button', 'data-write': 'true', disabled: state.busy, onclick: async () => {
      try { const data = await get('/material-packs/' + encodeURIComponent(pack.subject)); state.selectedPack = pack.subject; $('create-card').replaceChildren(el('h2', { text: '种下一棵新的树' }), profileForm(data.profile, { pack: pack.subject })); showMessage('已填入示例档案，可继续编辑。资料需创建后另行导入。'); }
      catch (error) { showMessage(error.message, 'error'); }
    } }, el('span', { text: pack.title || pack.subject }), el('small', { text: '使用示例档案与资料' })));
    if (state.packs.length) root.append(presets);
    root.append(el('section', { class: 'card card-accent', id: 'create-card' }, el('h2', { text: '种下一棵新的树' }), profileForm())); return root;
  }
  function heading(view) {
    const profile = view.profile || {}; const root = el('div', { class: 'page-heading' }, el('div', {}, el('div', { class: 'eyebrow', text: (profile.subject_label || 'LEARNING') + ' / ' + (view.version === 'v2' || isLegacy() ? 'V2 HISTORY' : 'V3 LEARNING') }),
      el('h1', { text: currentName(view) }), el('p', { text: profile.bounded_goal || profile.goal || view.goal || '' })),
      el('div', { class: 'heading-tags' }, chip(labels[view.page_state] || '学习记录', view.page_state === 'completed' ? 'green' : view.page_state === 'error' ? 'red' : 'cyan'),
        chip(profile.learning_mode === 'exploration' ? '当前仅讲解' : view.learning_basis === 'ai_generated' ? 'AI 整理内容' : view.learning_basis === 'provided_material' ? '依据资料学习' : '学习与练习', profile.learning_mode === 'exploration' || isLegacy() ? 'amber' : '')));
    return root;
  }
  function flow(view) {
    const stage = view.page_state; const index = stage === 'profile_review' ? 0 : stage === 'materials_required' ? 1 : stage === 'plan_review' ? 2 : ['quiz','completed','assessment_review'].includes(stage) ? 4 : ['learning', 'exploring'].includes(stage) ? 3 : -1;
    return el('div', { class: 'flow-steps', 'aria-label': '学习流程' }, ['起点', '资料', '路线', '学习', '小测'].map((s, i) => el('span', { class: 'flow-step' + (index === i ? ' active' : '') }, el('span', { class: 'step-dot', text: i + 1 }), s)));
  }
  function profileSummary(view) {
    const p = view.profile || {}; const dl = el('dl', { class: 'profile-summary' });
    const rows = view.guided ? [['学习目标', p.goal], ['已有基础', list(p.prior_knowledge?.self_reported).join('；') || '零基础 / 暂未自述'],
      ...(p.bounded_goal ? [['AI 建议范围', p.bounded_goal]] : []),
      ['时间安排', `${p.time_budget_minutes} 分钟 / 每次 ${p.session_minutes} 分钟`]] : [['学习主题', p.topic], ['目标范围', p.bounded_goal || p.goal], ['已有基础', list(p.prior_knowledge?.self_reported).join('；') || '暂未自述'],
      ['本次包含', list(p.scope_in).join('；') || '以确认的目标范围为准'], ['本次不包含', list(p.scope_out).join('；') || '暂未填写'],
      ['学习方式', p.learning_mode === 'exploration' ? '探索讨论，不产生正式通过' : '正式学习与测评'], ['评价方式', list(p.requested_capabilities).map(s => capabilityNames[s] || s).join('、')],
      ['时间安排', p.time_budget_minutes ? `${p.time_budget_minutes} 分钟 / 每次 ${p.session_minutes} 分钟` : '—']];
    for (const [key, value] of rows) dl.append(el('dt', { text: key }), el('dd', { text: value || '—' }));
    return dl;
  }
  function nodesFor(view) { return list(view.nodes).length ? view.nodes : list(view.plan?.nodes); }
  function renderPlan(view, compact = false) {
    const nodes = nodesFor(view); const ol = el('ol', { class: 'plan-list' }); const completed = new Set(list(view.completed_node_ids));
    const names = new Map(nodes.map(n => [n.node_id || n.id, n.title]));
    nodes.forEach((node, index) => {
      const passed = node.passed === true || completed.has(node.node_id || node.id); const current = (node.node_id || node.id) === view.current_node_id;
      const li = el('li', { class: 'plan-node' + (passed ? ' passed' : '') + (current ? ' current' : '') }, el('span', { class: 'node-number', text: passed ? '✓' : String(index + 1).padStart(2, '0') }),
        el('h3', {}, el('span', { text: node.title || node.node_id }), passed ? chip('已通过', 'green') : current ? chip(view.mode === 'review' ? '当前节点 / 先修回顾中' : '当前学习', 'cyan') : null));
      if (!compact) {
        li.append(el('p', { class: 'node-description', text: node.description || '' }));
        const objectives = el('ul', { class: 'objective-list' });
        for (const obj of list(node.objectives)) objectives.append(el('li', {}, el('span', { text: obj.observable_outcome || obj.description || obj.title || obj.objective_id }), el('small', { text: obj.required === false ? '选修目标' : '必要目标' })));
        if (objectives.childElementCount) li.append(objectives);
      }
      const prereqs = list(node.prerequisite_ids || node.prerequisites);
      li.append(el('p', { class: 'node-meta', text: (node.estimated_minutes ? `约 ${node.estimated_minutes} 分钟` : '') + (prereqs.length ? ' · 先修：' + prereqs.map(id => names.get(id) || id).join('、') : ' · 起始节点') }));
      ol.append(li);
    });
    if (!nodes.length) ol.append(el('p', { class: 'muted', text: 'AI 将根据目标、基础和可用资料整理起步计划。' }));
    return ol;
  }
  function citationButtons(citations, view) {
    const group = el('div', { class: 'citations', 'aria-label': '讲解资料引用' });
    for (const c of list(citations)) {
      const source = list(view.sources).find(s => s.source_id === c.source_id && s.source_version === c.source_version);
      group.append(el('button', { type: 'button', text: (source?.title || '查看引用原文') + ' · v' + c.source_version, onclick: () => showSource(c.source_id, c.source_version, c.chunk_id) }));
    }
    return group;
  }
  function sourceCard(view) {
    const card = el('section', { class: 'card' }, el('div', { class: 'card-header' }, el('h2', { text: '学习资料' }), view.frozen ? chip('已随路线确认', 'green') : null));
    const sources = list(view.sources);
    if (!sources.length) card.append(el('p', { class: 'muted', text: view.guided ? '资料可选。不上传时，AI 将整理通用学习内容并标明来源；学习具体内部制度时请提供文件。' : '尚无公开教学资料，请先导入本课依据。' }));
    if (list(view.private_references).length) card.append(el('p', { class: 'muted-line', text: `已导入 ${view.private_references.length} 份评价参考，请在计划预览中选择适用节点，或明确不使用。` }));
    for (const source of sources) card.append(el('div', { class: 'source-row' }, el('div', {}, el('h3', { text: source.title }), el('p', { text: source.source_description }), el('small', { class: 'dim', text: '版本 ' + source.source_version + ' · ' + (source.trust_note || '用户提供，未独立核验') })),
      button('查看来源', () => showSource(source.source_id, source.source_version), 'subtle')));
    if (allowed('import_material')) {
      const row = el('div', { class: 'actions' }, button('＋ 粘贴 / 上传资料', () => sourceForm(view)));
      if (state.packs.length) row.append(button('导入示例资料', () => choosePack(view)));
      card.append(row, el('p', { class: 'source-foot', text: '支持 TXT / Markdown 文字资料。更新资料后需要重新规划路线；仅供评分的参考资料不会出现在讲解里。' }));
    }
    return card;
  }
  function prepareView(view) {
    const root = el('div', {}, heading(view), flow(view));
    if (view.notice) root.append(el('p', { class: 'notice', text: view.notice }));
    if (view.requires_replan) root.append(el('div', { class: 'notice', text: '资料或目标已经变化，这条路线需要重新规划后才能确认。' }));
    if (view.preparation_notice) root.append(el('p', { class: 'notice blue', text: view.preparation_notice }));
    const cap = view.capability_check;
    if (cap && cap.status !== 'supported') root.append(el('div', { class: 'notice blue' },
      el('strong', { text: ({ needs_material: '还需要一份学习资料', exploration_only: '这门课目前只能自由探索', unsupported: '有一部分内容暂时还不能练习和评分' })[cap.status] || '学习条件检查' }),
      ...list(cap.reasons).map(s => el('p', { text: s }))));
    const profileCard = el('section', { class: 'card' }, el('h2', { text: view.guided ? '你的学习起点' : '学习档案' }), profileSummary(view));
    const controls = el('div', { class: 'actions' });
    for (const action of ['update_profile', 'adjust_scope']) if (allowed(action)) controls.append(button(actionLabels[action], () => openModal(actionLabels[action], profileForm(view.profile, { editing: true, action, guided: view.guided }))));
    if (allowed('confirm_profile')) controls.append(button(view.guided ? 'AI 整理学习计划' : '生成学习计划', () => command('confirm_profile'), 'primary'));
    if (controls.childElementCount) profileCard.append(controls);
    root.append(profileCard, sourceCard(view));
    if (view.plan || ['plan_review', 'learning', 'exploring'].includes(view.page_state) || allowed('begin')) {
      const plan = el('section', { class: 'card' }, el('div', { class: 'card-header' }, el('h2', { text: view.frozen ? '已确认的生长路线' : '预览生长路线' }), view.frozen ? chip('路线已确认', 'green') : chip('待确认', 'amber')), renderPlan(view));
      if (!view.frozen) plan.append(el('p', { class: 'muted-line', text: '确认后，这条路线和对应资料会固定下来；之后上传的新资料不会改变本课的评分标准。' }));
      const referenceChoices = [];
      if (!view.frozen && list(view.private_references).length) {
        plan.append(el('h3', { text: '评价参考的用途' }), el('p', { class: 'muted-line', text: '选择每份参考用于哪些节点的出题与评分；参考正文不会交给教学，也不会出现在公开来源中。' }));
        const localLabels = storage.read('reference-labels-' + view.project_id) || {};
        for (const reference of view.private_references) {
          const mode = el('select', { 'aria-label': reference.label + '的用途', 'data-write': 'true' }, el('option', { value: '', text: '请选择用途' }), el('option', { value: 'bind', text: '用于选中的节点' }), el('option', { value: 'exclude', text: '本计划不使用' }));
          const targets = el('div', { class: 'reference-targets', hidden: true });
          const checks = nodesFor(view).map(node => {
            const check = input('reference-node', '', { type: 'checkbox', value: node.node_id, 'data-write': 'true' });
            targets.append(el('label', {}, check, el('span', { text: node.title })));
            return check;
          });
          mode.addEventListener('change', () => { targets.hidden = mode.value !== 'bind'; });
          plan.append(el('div', { class: 'reference-choice' }, el('strong', { text: localLabels[reference.reference_id] || reference.label }), mode, targets));
          referenceChoices.push(() => {
            const nodeIds = mode.value === 'bind' ? checks.filter(c => c.checked).map(c => c.value) : [];
            if (!mode.value || (mode.value === 'bind' && !nodeIds.length)) throw new Error('请为每份评价参考选择适用节点，或选择“本计划不使用”。');
            return { reference_id: reference.reference_id, action: mode.value, node_ids: nodeIds };
          });
        }
      }
      const row = el('div', { class: 'actions' });
      if (allowed('adjust_plan')) row.append(button('调整计划', () => textCommand('adjust_plan', '希望如何调整学习计划？', 'feedback', '例如：把这一部分拆成两个更小的节点。')));
      if (allowed('confirm_plan')) row.append(button(actionLabels.confirm_plan, () => {
        try { return command('confirm_plan', { private_references: referenceChoices.map(read => read()) }); }
        catch (error) { showMessage(error.message, 'warn'); }
      }, 'primary'));
      plan.append(row); root.append(plan);
    }
    const row = el('div', { class: 'actions' });
    for (const action of ['replan', 'begin', 'begin_learning']) if (allowed(action)) row.append(button(actionLabels[action], () => action === 'choose_exploration' ? confirmAction('进入探索模式', '探索模式只提供文字讨论，不产生正式通过或依赖解锁。', () => command(action)) : command(action), action.startsWith('begin') || (action === 'replan' && (view.requires_replan || !allowed('confirm_plan'))) ? 'primary' : ''));
    if (allowed('rest')) row.append(button('休息，保留当前进度', () => command('rest'), 'subtle'));
    if (row.childElementCount) root.append(row);
    return root;
  }
  function sourceForm(view) {
    const form = el('form'); const title = input('title', '', { required: true, maxlength: 256, placeholder: '例如：第一单元 · 循环基础' });
    const description = textArea('source_description', '', { required: true, maxlength: 4000, placeholder: '作者 / 链接 / 章节 / 使用范围等', rows: 2 });
    const content = textArea('content', '', { maxlength: 131072, rows: 8, placeholder: '粘贴资料原文，或在下方选择 UTF-8 文件' });
    const file = input('file', '', { type: 'file', accept: '.txt,.md,.markdown,text/plain,text/markdown' });
    const visibility = el('select', { name: 'visibility' }, el('option', { value: 'teaching', text: '教学资料 · 可用于讲解与公开引用' }), el('option', { value: 'assessment_private', text: '私有测评资料 · 仅供出题与评分' }));
    const replace = el('select', { name: 'source_id' }, el('option', { value: '', text: '作为新资料导入' }), ...list(view.sources).map(s => el('option', { value: s.source_id, text: '更新版本：' + s.title })));
    const submit = el('button', { type: 'submit', class: 'btn primary', text: '导入资料', disabled: state.busy });
    form.append(el('div', { class: 'form-grid' }, field('资料标题', title, '', true), field('来源说明', description, '请保留可复查的作者、章节或链接。', true), field('原文', content, '文件和粘贴二选一。资料中的脚本只会作为文字显示。', true), field('选择文件', file, 'UTF-8 TXT / Markdown，单文件最多 128 KB。', true), field('可见性', visibility), field('导入方式', replace)), el('div', { class: 'notice blue', text: '资料不能修改权限、评分策略、工具或调用上限。私有参考的正文与答案不进入教学或公开来源；确认计划时需选择适用节点。' }), el('div', { class: 'actions' }, submit));
    file.addEventListener('change', () => { if (file.files[0] && !title.value) title.value = file.files[0].name.replace(/\.(?:txt|md|markdown)$/i, ''); });
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (state.busy || !form.reportValidity()) return;
      if (Boolean(file.files[0]) === Boolean(content.value.trim())) { showMessage('请选择一个文件，或粘贴原文，两者保留一种。', 'warn'); return; }
      const body = { request_id: uuid(), title: title.value.trim(), source_description: description.value.trim(), visibility: visibility.value };
      if (replace.value) body.source_id = replace.value;
      try {
        if (file.files[0]) {
          const selected = file.files[0]; if (!/\.(txt|md|markdown)$/i.test(selected.name)) throw new Error('仅支持 TXT / Markdown 文件。');
          const bytes = new Uint8Array(await selected.arrayBuffer()); if (bytes.length > 131072) throw new Error('文件超过 128 KB，请拆分或缩减范围。');
          new TextDecoder('utf-8', { fatal: true }).decode(bytes); let binary = ''; for (const byte of bytes) binary += String.fromCharCode(byte);
          body.filename = selected.name; body.data_base64 = btoa(binary);
        } else body.content = content.value;
      } catch (error) { showMessage(error.message || '文件必须采用 UTF-8 编码。', 'error'); return; }
      await write('/projects/' + encodeURIComponent(view.project_id) + '/sources', body, { busyText: '正在保存资料版本…', success: '资料已导入。请核对新草案，必要时明确重新规划。', after: result => {
        if (result?.private_reference_id) {
          const labels = storage.read('reference-labels-' + view.project_id) || {};
          labels[result.private_reference_id] = title.value.trim();
          storage.write('reference-labels-' + view.project_id, labels);
        }
        // A successful import no longer needs its private draft in hidden DOM.
        content.value = ''; file.value = '';
      } });
    });
    openModal('导入学习资料', form);
  }
  function choosePack(view) {
    const content = el('div', {}, el('p', { class: 'muted', text: '将导入配套公开教学原文，不会自动确认档案或计划。示例范围可在正式开课前调整。' }));
    for (const p of state.packs) content.append(button(p.title || p.subject, async () => {
      try {
        const pack = await get('/material-packs/' + encodeURIComponent(p.subject));
        confirmAction('导入 ' + (pack.title || p.title || p.subject), `将导入 ${list(pack.documents).length} 份公开资料。与当前范围无关的资料不会自动成为正式计划依据。`, async () => {
          if (state.busy) return; busy(true, '正在依次导入示例资料…'); let imported = 0;
          try {
            // Each document is a separate explicit request. A failed response
            // stops the batch and reads state; it never blindly replays a POST.
            for (const doc of list(pack.documents)) {
              if (doc.visibility && doc.visibility !== 'teaching') continue;
              const response = await fetch('/projects/' + encodeURIComponent(view.project_id) + '/sources', { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify({ request_id: uuid(), title: doc.title, source_description: doc.source_description, visibility: 'teaching', content: doc.content }) });
              if (!response.ok) throw new Error('一份资料未能确认导入，已停止后续导入。'); await response.json(); imported++;
            }
            $('modal').close(); showMessage(`已导入 ${imported} 份公开教学资料。请确认档案或重新规划。`);
          } catch (error) { showMessage(`${error.message} 已先查询最新状态，请核对资料列表再操作。`, 'warn'); }
          finally { try { await loadProject(view.project_id); await refreshList(); } catch { /* Keep the last readable view. */ } busy(false); }
        });
      } catch (error) { showMessage(error.message, 'error'); }
    })); openModal('选择示例资料包', content);
  }
  async function showSource(sourceId, version, chunkId = null) {
    try {
      const data = await get('/projects/' + encodeURIComponent(state.id) + '/sources/' + encodeURIComponent(sourceId) + '/versions/' + encodeURIComponent(version));
      const root = el('div', {}, el('p', { class: 'muted', text: data.source_description || '' }), chip('版本 ' + (data.source_version || version)), el('p', { class: 'muted-line', text: data.trust_note || '用户提供，未独立核验。引用定位不等同于内容已被人工核实。' }));
      const chunks = list(data.chunks);
      if (chunks.length) for (const chunk of chunks) {
        const lines = el('div', { class: 'source-content' });
        String(chunk.content || '').split('\n').forEach((line, index) => lines.append(el('span', { class: 'source-line' }, el('span', { class: 'source-line-number', 'aria-hidden': 'true', text: Number(chunk.line_start || 1) + index }), line)));
        root.append(el('section', { class: 'source-chunk' + (chunk.chunk_id === chunkId ? ' highlighted' : ''), id: 'source-' + chunk.chunk_id }, el('small', { text: `第 ${chunk.line_start}–${chunk.line_end} 行` + (chunk.heading ? ' · ' + chunk.heading : '') }), lines));
      }
      else root.append(el('pre', { class: 'source-content', text: data.content || '' }));
      openModal(data.title || '来源原文', root);
      $('modal').classList.add('source-drawer');
      if (chunkId) document.getElementById('source-' + chunkId)?.scrollIntoView({ block: 'nearest' });
    } catch (error) { showMessage(error.status === 404 ? '该来源或版本不可公开读取，请刷新查看当前可用引用。' : error.message, 'error'); }
  }
  function objectiveFeedback(view) {
    const feedback = view.feedback; if (!feedback) return null;
    const card = el('section', { class: 'card' }, el('div', { class: 'card-header' }, el('h2', { text: '本轮评价反馈' }), chip(({ graded: '已评分', needs_review: '需要复核', invalid_item: '题目无效' })[feedback.grading_status] || '评价结果', feedback.grading_status === 'graded' ? 'cyan' : 'amber')));
    if (feedback.node_title) card.append(el('p', { class: 'muted-line', text: '对应节点：' + feedback.node_title }));
    const guard = feedback.guard;
    if (guard) card.append(el('div', { class: 'notice ' + (guard.passed === true ? 'green' : 'blue') }, el('strong', { text: guard.passed === true ? '本节点已通过' : '尚未形成正式通过' }), ...list(guard.reasons).map(r => el('p', { text: r }))));
    if (feedback.grading_status === 'graded' && feedback.max_score > 0) card.append(el('div', { class: 'metric-row' }, el('div', {}, el('div', { class: 'metric-value', text: `${feedback.total_score} / ${feedback.max_score}` }), el('div', { class: 'metric-label', text: '本卷得分 · 不代表掌握概率' }))));
    else card.append(el('p', { class: 'muted-line', text: '本轮尚无可靠分数，不计为学生低分或有效失败轮次。' }));
    const results = list(feedback.objective_results);
    if (results.length) {
      card.append(el('h3', { text: '分目标证据' }));
      for (const result of results) {
        const percent = typeof result.score_ratio === 'number' ? Math.round(result.score_ratio * 10000) / 100 + '%' : '—';
        const threshold = typeof result.threshold === 'number' ? ' · 冻结门槛 ' + (Math.round(result.threshold * 10000) / 100) + '%' : '';
        card.append(el('div', { class: 'feedback-row' }, el('div', { class: 'feedback-title' }, el('span', { text: result.observable_outcome || result.objective_id }), el('small', { text: percent + threshold })), result.feedback ? el('p', { text: result.feedback }) : null, result.required !== false ? el('small', { class: 'dim', text: '必要目标' }) : null));
      }
    }
    const questions = list(feedback.question_results || feedback.question_scores);
    if (questions.length) { card.append(el('h3', { text: '逐题结果' })); for (const [i, result] of questions.entries()) card.append(el('div', { class: 'feedback-row' }, el('div', { class: 'feedback-title' }, el('span', { text: '第 ' + (i + 1) + ' 题' }), el('small', { text: `${result.score} / ${result.max_score}` })), result.feedback ? el('p', { text: result.feedback }) : null)); }
    card.append(el('p', { class: 'muted-line', text: '是否通过由后端结合必要目标、证据和关键错误审查。无法可靠评价的测评不计有效失败轮次。' }));
    return card;
  }
  function budgetCard(view) {
    const budget = view.operation_budget; const rounds = view.rounds;
    if (!budget && !rounds) return null;
    const card = el('section', { class: 'card' }, el('h2', { text: '本次学习' }));
    if (rounds) card.append(el('div', { class: 'metric-row' }, el('div', {}, el('div', { class: 'metric-value', text: `${rounds.effective_rounds || 0} / ${rounds.round_limit || 3}` }), el('div', { class: 'metric-label', text: '当前节点有效测评轮次' }))), el('p', { class: 'muted-line', text: rounds.extension_used ? '已使用一次额外 3 轮。' : '达到轮数后暂停，可主动追加一次 3 轮。' }));
    if (budget && budget.limit > 0) {
      const fill = el('div', { class: 'budget-fill' }); fill.style.width = Math.min(100, (budget.used / budget.limit) * 100) + '%';
      card.append(el('p', { class: 'metric-label', text: `本操作模型请求：${budget.used} / ${budget.limit}` }), el('div', { class: 'budget-track', 'aria-label': '请求额度已用 ' + budget.used + '，共 ' + budget.limit }, fill));
    }
    return card;
  }
  function tutorCard(view) {
    const tutor = view.tutor; const node = nodesFor(view).find(n => n.node_id === view.current_node_id);
    const title = view.mode === 'remediate' ? '针对性补弱' : view.mode === 'review' ? '先修知识回顾' : view.page_state === 'exploring' ? '探索讨论' : '一起学这一小步';
    const card = el('section', { class: 'card card-accent' }, el('div', { class: 'card-header' }, el('h2', { text: title }), node ? chip(node.title, 'cyan') : null));
    if (view.profile?.learning_mode === 'exploration') card.append(el('p', { class: 'notice', text: '当前课程暂不提供可验证的练习通过记录，可继续提问和讨论。' }));
    const turns = list(view.conversation); const tutorText = typeof tutor === 'string' ? tutor : tutor?.text;
    if (tutorText) card.append(markdown(tutorText), citationButtons(tutor?.citations, view));
    else card.append(el('p', { class: 'muted', text: '当前暂无讲解。请按下方可用操作继续。' }));
    if (turns.length) {
      const history = el('details', { class: 'section-details' }, el('summary', { text: '查看最近问答（' + turns.length + '）' }));
      for (const turn of turns) {
        const question = turn.question || turn.user || turn.user_message; const answer = turn.text || turn.answer || turn.assistant || turn.assistant_message;
        const item = el('div', { class: 'conversation-turn' });
        if (question) item.append(el('div', { class: 'conversation-head', text: '我的问题' }), el('p', { class: 'conversation-question', text: typeof question === 'string' ? question : question.content || '' }));
        if (answer) item.append(el('div', { class: 'conversation-head', text: '讲解' }), markdown(typeof answer === 'string' ? answer : answer.text || answer.content || ''));
        history.append(item);
      }
      card.append(history);
    }
    if (allowed('ask')) {
      const key = 'question-' + view.project_id; const q = textArea('question', storage.read(key, ''), { required: true, maxlength: 4000, placeholder: '哪里还不清楚？也可以提出你自己的例子。', 'aria-label': '向 Tutor 提问' });
      const form = el('form', { class: 'composer' }, q, el('div', { class: 'actions' }, el('button', { type: 'submit', class: 'btn', text: '发送问题', disabled: state.busy })));
      q.addEventListener('input', () => storage.write(key, q.value));
      form.addEventListener('submit', async event => { event.preventDefault(); if (!state.busy && form.reportValidity()) await command('ask', { question: q.value.trim() }, { after: () => storage.remove(key) }); });
      card.append(form);
    }
    const row = el('div', { class: 'actions' });
    for (const action of ['return_to_current', 'start_quiz', 'return_to_teaching']) if (allowed(action)) row.append(button(actionLabels[action], () => command(action), action === 'start_quiz' ? 'primary' : ''));
    if (row.childElementCount) card.append(row);
    return card;
  }
  function quizCard(view) {
    const quiz = view.quiz; if (!quiz) return el('section', { class: 'card' }, el('h2', { text: '正在准备试卷' }), el('p', { class: 'muted', text: '请查看当前状态和可用恢复操作。' }));
    const form = el('form', { id: 'quiz-form' }); const key = 'answers-' + view.project_id + '-' + quiz.assessment_id; const saved = storage.read(key, {});
    const card = el('section', { class: 'card card-accent' }, el('div', { class: 'card-header' }, el('h2', { text: '这一节的小测' }), chip(list(quiz.questions).length + ' 道题', 'cyan')),
      el('p', { class: 'muted-line', text: '请独立作答。数值题写数值和单位，解题思路写在文字题里。' }));
    const answers = {};
    list(quiz.questions).forEach((q, index) => {
      const type = q.question_type || q.type; const fieldset = el('fieldset', { class: 'question' }, el('legend', { text: `第 ${index + 1} 题` }),
        el('div', { class: 'question-type' }, el('span', { text: ({ single_choice: '单选题', multiple_choice: '多选题 · 全对得分', numeric_scalar: '数值题', text: '文字 / 步骤题' })[type] || '文字题' }), el('span', { text: q.max_score + ' 分' })), markdown(q.prompt));
      const controls = [];
      if (type === 'single_choice' || type === 'multiple_choice') {
        for (const option of list(q.options)) {
          const checked = type === 'multiple_choice' ? list(saved[q.question_id]).includes(option.option_id) : saved[q.question_id] === option.option_id;
          const choice = input(q.question_id, option.option_id, { type: type === 'multiple_choice' ? 'checkbox' : 'radio', checked, required: type === 'single_choice', disabled: !allowed('submit_answer'), 'aria-label': option.text });
          controls.push(choice); fieldset.append(el('label', { class: 'answer-choice' }, choice, markdown(option.text)));
        }
      } else {
        const answer = type === 'numeric_scalar' ? input(q.question_id, saved[q.question_id] || '', { type: 'text', inputmode: 'text', class: 'answer-numeric', placeholder: '例如：2、1.5 cm 或 3e-2', maxlength: 4000, required: true, disabled: !allowed('submit_answer'), 'aria-label': '第 ' + (index + 1) + ' 题数值答案' })
          : textArea(q.question_id, saved[q.question_id] || '', { required: true, maxlength: 8000, rows: 5, placeholder: '写下你的答案与理由…', disabled: !allowed('submit_answer'), 'aria-label': '第 ' + (index + 1) + ' 题文字答案' });
        controls.push(answer); fieldset.append(el('label', { class: 'answer-label', for: answer.id = 'answer-' + index, text: type === 'numeric_scalar' ? '你的数值答案' : '你的答案与步骤' }), answer);
        if (type === 'numeric_scalar') window.SkillTreeControls?.numericEcho(answer);
      }
      answers[q.question_id] = () => type === 'multiple_choice' ? controls.filter(c => c.checked).map(c => c.value) : type === 'single_choice' ? controls.find(c => c.checked)?.value || '' : controls[0].value;
      for (const control of controls) control.addEventListener('input', () => storage.write(key, Object.fromEntries(Object.entries(answers).map(([id, read]) => [id, read()]))));
      form.append(fieldset);
    });
    if (allowed('submit_answer')) form.append(el('div', { class: 'actions' }, el('button', { type: 'submit', class: 'btn primary', text: actionLabels.submit_answer, disabled: state.busy })));
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (state.busy || !form.reportValidity()) return; const payload = Object.fromEntries(Object.entries(answers).map(([id, read]) => [id, read()]));
      const missing = Object.values(payload).map((v, i) => (Array.isArray(v) ? !v.length : !v.trim()) ? i + 1 : 0).filter(Boolean);
      if (missing.length) { showMessage(`还有第 ${missing.join('、')} 题没有作答，完成后再提交。`, 'warn'); document.getElementById('question-' + (missing[0] - 1))?.scrollIntoView({ block: 'center' }); return; }
      await command('submit_answer', { assessment_id: quiz.assessment_id, answers: payload }, { after: () => storage.remove(key) });
    }); card.append(form); window.SkillTreeControls?.choiceKeys(form); return card;
  }
  function recoveryCard(view) {
    const stage = view.page_state; const headings = { running: '正在完成本次操作', error: '这一步需要恢复', paused: '暂停一下，进度已保留',
      budget_exhausted: '这一步的 AI 额度用完了', assessment_review: '这次没能可靠评分', completed: '这次学习已经完成' };
    const defaults = { running: '正在查询后台处理状态，结束后会自动显示结果。也可点击“刷新状态”；查询只读，不会再次请求模型。', error: '重试会接着原来的进度和试卷继续，不会重复计数。', paused: '休息期间什么都不会自动发生。准备好了，再点继续。',
      budget_exhausted: '为了避免无限消耗，每一步的 AI 调用都有上限。你可以追加一次额度继续；已经追加过时，进度会保留，稍后再来。', assessment_review: '题目或评分出了问题，这不算你答错，也不会消耗闯关机会。', completed: '每一节的通过记录都已保存，可以随时回来复习。' };
    // A timed-out or failed model request is a service problem, not the learner's answer.
    const modelTrouble = stage === 'error' && (['ModelRequestFailedError', 'LogicalTaskExhausted'].includes(view.error_type) || view.error_code === 'model_task_exhausted');
    const modelTroubleText = (view.error_type === 'ModelOutputValidationError'
      ? 'AI 生成的内容未通过格式或课程规则检查，当前结果没有生效。这不是你作答的问题。'
      : 'AI 请求没有成功完成。这不是你作答的问题。') + (allowed('replace_assessment') ? '可以申请换一份新的小测重新作答，' : '') + (allowed('return_to_teaching') ? '也可以先返回教学，' : '') + '进度都已保存。';
    const card = el('section', { class: 'card status-card' }, el('div', { class: 'status-symbol' + (stage === 'completed' ? ' green' : ''), text: stage === 'completed' ? '✓' : stage === 'running' ? '◌' : '↳' }), el('h2', { text: modelTrouble ? 'AI 这一步没能完成' : headings[stage] || labels[stage] || '当前状态' }), el('p', { class: 'muted', text: modelTrouble ? modelTroubleText : view.notice || defaults[stage] || '' }));
    if (view.pause_reason === 'replacement_limit') card.append(el('p', { class: 'notice', text: '已达到系统原因连续换题上限，当前保持暂停。请保留记录，待题目与评价问题修复后再继续。' }));
    if (view.pause_reason === 'extension_ready') card.append(el('p', { class: 'notice green', text: '已追加 3 次闯关机会。点“返回教学”继续学习。' }));
    if (view.error_type) card.append(view.recovery_required
      ? el('p', { class: 'muted-line', text: '检测到上次执行中断，可以从已保存的结果恢复。' })
      : el('details', { class: 'muted-line' }, el('summary', { text: '查看错误标识' }), el('code', { text: view.error_type })));
    const row = el('div', { class: 'actions' });
    for (const action of ['retry', 'continue_with_new_budget', 'retry_3', 'return_to_teaching', 'replace_assessment', 'view_feedback', 'annotate_dispute', 'rest']) {
      if (!allowed(action)) continue;
      const label=action==='return_to_teaching' && view.error_code==='model_task_exhausted' && view.failed_task_kind==='tutor' ? '重新生成讲解' : actionLabels[action];
      row.append(button(label, () => {
        if (action === 'continue_with_new_budget') confirmAction('追加请求额度', '每一步最多追加一次额度。追加后会从中断处继续。', () => command(action));
        else if (action === 'retry_3') confirmAction('追加 3 轮测评', '每一节只能追加一次。之前的记录会保留，追加后点“返回教学”继续。', () => command(action));
        else if (action === 'replace_assessment') confirmAction('申请新卷', '换一份新的小测。旧试卷和你的说明会保留，评分标准不变。', () => command(action, { assessment_id: view.assessment_id }));
        else if (action === 'annotate_dispute') textCommand(action, '补充本轮评价说明', 'annotation', '说明你认为需要复核的地方。补充只留档，不改写正式评分，也不当作新的作答。', view.assessment_id);
        else if (action === 'view_feedback') { document.getElementById('evaluation-feedback')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
        else command(action);
      }, ['retry', 'return_to_teaching', 'continue_with_new_budget'].includes(action) ? 'primary' : ''));
    }
    if (row.childElementCount) card.append(row);
    return card;
  }
  function learningView(view) {
    const root = el('div', {}, heading(view), flow(view));
    if (view.page_state === 'exploring') root.append(el('p', { class: 'notice', text: '探索模式只用于文字讨论，不产生正式通过，也不会解锁依赖。' }));
    const main = el('div'); const stage = view.page_state;
    if (['running', 'error', 'paused', 'budget_exhausted', 'assessment_review', 'completed'].includes(stage)) main.append(recoveryCard(view));
    const feedback = objectiveFeedback(view); if (feedback) { feedback.id = 'evaluation-feedback'; main.append(feedback); }
    if (stage === 'quiz') main.append(quizCard(view));
    if (['learning', 'exploring'].includes(stage)) main.append(tutorCard(view));
    if (stage === 'completed' && view.tutor) main.append(el('details', { class: 'card' }, el('summary', { text: '查看最近讲解' }), markdown(view.tutor.text || view.tutor)));
    if (['learning', 'exploring', 'quiz'].includes(stage) && allowed('rest')) {
      const row = el('div', { class: 'actions' }); if (stage === 'quiz' && allowed('return_to_teaching')) row.append(button('先返回教学', () => command('return_to_teaching')));
      row.append(button('休息，保留当前进度', () => command('rest'), 'subtle')); main.append(row);
    }
    const aside = el('aside', { class: 'learning-aside', 'aria-label': '学习路径与额度' });
    if (nodesFor(view).length) aside.append(el('section', { class: 'card' }, el('h2', { text: '学习路径' }), renderPlan(view, true)));
    const budget = budgetCard(view); if (budget) aside.append(budget);
    root.append(el('div', { class: 'learning-layout' }, main, aside));
    const sources = el('details', { class: 'section-details' }, el('summary', { text: '查看冻结资料与完整学习计划' }), sourceCard(view), el('section', { class: 'card' }, el('h2', { text: '学习目标与依赖' }), renderPlan(view)));
    root.append(sources); return root;
  }
  function legacyView(view) {
    const root = el('div', {}, heading(view), el('div', { class: 'legacy-badge', text: 'V2 历史 · 只读展示。不会启动旧 Graph，不接受恢复、重试或资料写入。' }));
    if (view.notice) root.append(el('p', { class: 'muted', text: view.notice }));
    const nodes = nodesFor(view); if (nodes.length) root.append(el('section', { class: 'card' }, el('h2', { text: '原有学习路径' }), renderPlan(view)));
    const lesson = view.lesson?.content || view.lesson?.text || (typeof view.lesson === 'string' ? view.lesson : null) || view.tutor?.text;
    if (lesson) root.append(el('section', { class: 'card' }, el('h2', { text: '已有讲解' }), markdown(lesson)));
    const turns = list(view.conversation);
    if (turns.length) {
      const card = el('section', { class: 'card' }, el('h2', { text: '历史问答' }));
      for (const turn of turns) {
        if (turn.question) card.append(el('p', { class: 'conversation-question', text: turn.question }));
        if (turn.answer) card.append(markdown(turn.answer));
        if (turn.content) card.append(el('p', { class: 'conversation-head', text: turn.role === 'user' ? '我的问题' : '讲解' }), markdown(turn.content));
      }
      root.append(card);
    }
    const feedback = objectiveFeedback(view); if (feedback) root.append(feedback);
    const results = list(view.results || view.assessments);
    if (results.length) {
      const card = el('section', { class: 'card' }, el('h2', { text: '已保存的测评记录' }));
      for (const result of results) {
        const item=el('div', { class: 'feedback-row' }, el('div', { class: 'feedback-title' }, el('span', { text: result.node_title || result.node_id || '历史测评' }), el('small', { text: result.status === 'graded' ? '已评分' : result.status || '已记录' })));
        if (result.feedback && typeof result.feedback === 'object') item.append(el('p', { text: `本卷得分 ${result.feedback.total_score} / ${result.feedback.max_score} · 仅展示原有评分事实` }));
        else item.append(el('p', { text: typeof result.feedback === 'string' ? result.feedback : result.summary || '保留原有评价结果，不重新运行模型。' }));
        for (const question of list(result.quiz?.questions)) item.append(markdown(question.prompt));
        card.append(item);
      }
      root.append(card);
    }
    if (!nodes.length && !lesson && !results.length) root.append(el('section', { class: 'card' }, el('h2', { text: '历史记录已保留' }), el('p', { class: 'muted', text: view.goal || '本条记录暂无可公开展示的已保存内容。' })));
    return root;
  }
  function render() {
    renderList(); $('page-title').textContent = state.view ? currentName(state.view) : '我的花园';
    garden.shell();
    $('refresh-project').hidden = !state.id;
    let content;
    if (!state.view) content = garden.home(welcome());
    else if (isLegacy() || state.view.version === 'v2' || state.view.page_state === 'legacy_readonly') content = legacyView(state.view);
    else if (!state.view.learning_runtime_ready || allowed('begin') || allowed('begin_learning')) {
      content = garden.prepare(state.view, prepareView(state.view));
      if (['error', 'running', 'budget_exhausted'].includes(state.view.page_state)) content.prepend(recoveryCard(state.view));
    } else content = garden.lesson(state.view);
    $('content').replaceChildren(content); busy(state.busy);
  }
  function capture() { return { project_id: state.view.project_id, pending_input_id: state.view.pending_input_id, draft_revision: state.view.draft_revision, assessment_id: state.view.assessment_id }; }
  async function command(action, payload = {}, options = {}) {
    if (state.busy || isLegacy() || !state.view) return;
    if (!allowed(action)) { showMessage('此操作已不适用于当前状态，请刷新后继续。', 'warn'); return; }
    const identity = capture(); const base = '/projects/' + encodeURIComponent(identity.project_id);
    if (['begin', 'begin_learning'].includes(action)) return write(base + '/begin', { request_id: uuid() }, { ...options, busyText: '正在准备第一步讲解…' });
    if (['retry', 'continue_with_new_budget'].includes(action)) return write(base + '/retry', { request_id: uuid(), retry_token: state.view.retry_token, action }, { ...options, busyText: action === 'retry' ? '正在从已保存的进度恢复…' : '正在追加额度并继续…' });
    if (action === 'rest') {
      // Rest still validates the stable identity on the server. It does not
      // advance the graph or trigger Tutor, assessment or diagnosis.
      return write(base + '/resume', { request_id: uuid(), pending_input_id: identity.pending_input_id, draft_revision: identity.draft_revision, action }, { ...options, success: '进度已保留，可以关闭页面，回来时继续。', busyText: '正在保留当前进度…' });
    }
    const body = { request_id: uuid(), pending_input_id: identity.pending_input_id, draft_revision: identity.draft_revision, action, ...payload };
    if (['submit_answer', 'annotate_dispute', 'replace_assessment'].includes(action)) body.assessment_id = identity.assessment_id;
    return write(base + '/resume', body, { ...options, busyText: action === 'submit_answer' ? '正在评分、核查证据并诊断…' : action === 'replan' || action === 'confirm_profile' || action === 'adjust_plan' ? '正在核对范围与资料，准备学习计划…' : '正在完成这一步…' });
  }
  async function followJob(initial) {
    storage.write('active-job', initial.id);
    const started = Date.now(); let job = initial;
    while (['queued', 'running'].includes(job.state)) {
      $('busy-text').textContent = job.state === 'queued' ? `正在排队 · 等待位置第 ${job.position} 位` : '正在处理你的学习任务，进度会自动保存…';
      if (Date.now() - started > 1200000) throw new Error('任务仍在后台处理，稍后刷新页面可以继续查询。');
      await new Promise(resolve => setTimeout(resolve, 1500));
      const response = await get('/jobs/' + encodeURIComponent(job.id)); job = response.job;
    }
    storage.remove('active-job');
    if (job.state === 'interrupted') throw Object.assign(new Error('服务更新时任务中断，进度已保留，请核对当前步骤后使用恢复操作。'), { interrupted: true });
    return job;
  }
  async function restoreJob() {
    try {
      const saved = storage.read('active-job');
      let job;
      if (saved) {
        try { job = (await get('/jobs/' + encodeURIComponent(saved))).job; }
        catch (error) { if (error.status === 404) storage.remove('active-job'); else throw error; }
      }
      if (!job) job = (await get('/jobs/active')).job;
      if (!job) return;
      busy(true, '正在查询上次任务…');
      const completed = await followJob(job);
      if (completed.project_id) await loadProject(completed.project_id);
      await refreshList(); render();
      showMessage(completed.status_code < 400 ? '上次任务已处理，已读取保存的结果。' : '上次任务未完成，请查看当前步骤和恢复提示。', completed.status_code < 400 ? '' : 'warn');
    } catch (error) { showMessage(error.message || '任务状态暂时无法查询，请稍后刷新。', 'warn'); }
    finally { busy(false); }
  }
  async function write(url, body, { method = 'POST', busyText, success = '', after = null } = {}) {
    if (state.busy) return; closeMenu(); busy(true, busyText); showMessage('');
    const sprout = window.SkillTreeControls?.grow(window.SkillTreeControls.pressed());
    // A silent client connection does not cancel or disprove the server's work.
    // Stop waiting for this response, then use the existing read-only recovery.
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 60000);
    const projectId = state.id; const pendingIdentity = state.view?.pending_input_id; const previousView = state.view; let result, confirmed = false;
    state.pendingWrite = { url, body, method };
    try {
      let response = await fetch(url, { method, headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...(authSession?.csrf_token ? { 'X-CSRF-Token': authSession.csrf_token } : {}) }, body: JSON.stringify(body), signal: controller.signal });
      try { result = await response.json(); } catch { throw new Error('本次响应未能确认'); }
      clearTimeout(timeout);
      if (response.status === 401) { location.replace('/login?next=' + encodeURIComponent(location.pathname + location.search + location.hash)); return; }
      if (response.status === 202 && result?.job) {
        const completed = await followJob(result.job);
        result = completed.result; response = { status: completed.status_code, ok: completed.status_code < 400 };
      }
      if (!response.ok) {
        if (response.status === 409) {
          if (projectId) await loadProject(projectId); else await refreshList();
          showMessage(result?.error?.message || '另一个页面已经更新了项目，当前输入已过期。已读取最新状态，请核对后继续。', 'warn');
        } else showMessage(result?.error?.message || '操作未能完成，请检查输入或刷新状态。', 'error');
        return;
      }
      confirmed = true; if (after) after(result);
      if (result?.project_id && !result.deleted) { state.id = result.project_id; state.view = result; storage.write('selection', { id: state.id, tab: state.tab }); }
      else if (state.id) await loadProject(state.id);
      garden.afterWrite(body, state.view, previousView);
      $('modal').close(); await refreshList(); render();
      if (success) showMessage(success);
    } catch (error) {
      // A network error does not prove that the write failed. Read first and
      // never automatically resend the command or silently create a new ID.
      try {
        const recoveryId = state.id || projectId || (url === '/projects' ? creationProjectId(body) : null);
        if (recoveryId) {
          try { await loadProject(recoveryId); }
          catch (readError) {
            if (method === 'DELETE' && readError.status === 404) { state.id = null; state.view = null; storage.remove('selection'); render(); }
            else throw readError;
          }
        }
        await refreshList(); $('modal').close();
        showMessage(confirmed ? '操作结果已返回，但列表未能刷新。已先读取项目状态，请核对后继续。' : '没有收到完整响应，已先查询最新状态。请核对记录与当前步骤；本页没有自动重复提交。', 'warn');
      } catch { showMessage('连接暂时中断。当前草稿已保留，恢复连接后请先刷新状态，核对是否已完成；本页没有自动重复提交。', 'error'); }
    } finally {
      clearTimeout(timeout);
      if (confirmed) sprout?.done(); else sprout?.fail();
      state.pendingWrite = null; busy(false); renderList();
      // Never carry submitted answers into a later assessment identity.
      if (pendingIdentity && state.view?.pending_input_id !== pendingIdentity && state.view?.page_state !== 'quiz') document.querySelectorAll('#quiz-form input,#quiz-form textarea').forEach(n => { n.disabled = true; });
    }
    return result;
  }
  function confirmAction(title, description, callback, destructive = false) {
    const content = el('div', {}, el('p', { class: destructive ? 'danger-note' : 'muted', text: description }));
    content.append(el('div', { class: 'actions dialog-actions' }, dismissButton(), button(destructive ? '确认删除' : '确认继续', () => {
      closeModal(); return callback();
    }, destructive ? 'danger' : 'primary'))); openModal(title, content);
  }
  function textCommand(action, title, key, hint, assessmentId = null) {
    const text = textArea(key, '', { required: true, maxlength: key === 'feedback' ? 2000 : 4000, rows: 6, placeholder: hint });
    const form = el('form', {}, field(title, text, hint), el('div', { class: 'actions dialog-actions' }, dismissButton(), el('button', { type: 'submit', class: 'btn primary', text: '提交', disabled: state.busy })));
    form.addEventListener('submit', async event => { event.preventDefault(); if (!state.busy && form.reportValidity()) await command(action, { [key]: text.value.trim(), ...(assessmentId ? { assessment_id: assessmentId } : {}) }); }); openModal(title, form);
  }
  function renameProject(project) {
    const name = input('display_name', currentName(project), { required: true, maxlength: 80, placeholder: '给这段学习取个名字' });
    const form = el('form', {}, field('学习记录名称', name, '只修改显示名称，原始目标与冻结标准保持不变。'), el('div', { class: 'actions dialog-actions' }, dismissButton(), el('button', { type: 'submit', class: 'btn primary', text: '保存名称', disabled: state.busy })));
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (!state.busy && form.reportValidity()) await write('/projects/' + encodeURIComponent(project.project_id), { display_name: name.value.trim() }, { method: 'PATCH', success: '学习记录已重命名。', after: result => { if (project.project_id !== state.id && result?.project_id) { /* The selected view is refreshed below. */ } } });
    }); openModal('重命名学习记录', form); name.select();
  }
  function deleteProject(project) {
    confirmAction('删除这条学习记录？', '“' + currentName(project) + '”的 V3 学习记录与断点将被删除。此操作无法在页面撤销，请确认这正是你要删除的记录。', async () => {
      await write('/projects/' + encodeURIComponent(project.project_id), { confirm_project_id: project.project_id }, { method: 'DELETE', success: '学习记录已删除。', after: () => {
        if (state.id === project.project_id) { state.id = null; state.view = null; storage.remove('selection'); }
      } });
    }, true);
  }
  function showCapabilities() {
    const body = el('div', {}, el('p', { class: 'muted', text: '这里显示服务端实际能力。未实现的能力不能因为资料或模型要求而获得正式测评权限。' }));
    for (const cap of state.capabilities) body.append(el('div', { class: 'capability-row' }, el('h3', {}, cap.task_description || cap.capability_id, ' ', chip(cap.availability === 'available' ? cap.kind === 'evaluation' ? cap.formal_assessment_available ? '可正式评价' : '不可正式评价' : '可用' : '未支持', cap.availability === 'available' ? 'green' : 'amber')),
      ...list(cap.limitations).map(s => el('p', { text: s })))); openModal('当前支持的能力', body);
  }
  async function newProject() {
    if (state.busy) return;
    const pendingId = creationProjectId(storage.read('creation-request'));
    if (pendingId) {
      // Older page versions also retained successful requests. Read before
      // retiring one; an uncertain/absent result must keep its retry identity.
      busy(true, '正在核对上次创建结果…');
      try { const previous = await get('/projects/' + encodeURIComponent(pendingId)); finishCreation(previous.project_id); }
      catch { /* Preserve the pending request if the result is still unknown. */ }
      finally { busy(false); }
    }
    closeSidebar(); closeMenu(); state.tab = 'current'; state.id = null; state.view = null; ++state.loadSequence;
    storage.remove('selection'); showMessage(''); render(); window.scrollTo({ top: 0, behavior: 'instant' });
  }
  $('new-project').addEventListener('click', newProject);

  $('refresh-list').addEventListener('click', async () => { if (!state.busy) try { await refreshList(); showMessage('记录列表已刷新。'); } catch (error) { showMessage(error.message, 'error'); } });
  $('refresh-project').addEventListener('click', async () => { if (!state.busy && state.id) try { await loadProject(state.id, { announce: true }); } catch (error) { showMessage(error.message, 'error'); } });
  $('mobile-menu').addEventListener('click', () => { const open = !$('sidebar').classList.contains('open'); $('sidebar').classList.toggle('open', open); $('sidebar-shade').hidden = !open; $('mobile-menu').setAttribute('aria-expanded', String(open)); });
  $('sidebar-shade').addEventListener('click', closeSidebar); $('modal-close').addEventListener('click', closeModal);
  $('capabilities-button').addEventListener('click', showCapabilities);
  document.addEventListener('click', event => { if (state.menu && !state.menu.contains(event.target) && !event.target.closest('.project-more')) closeMenu(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') { closeMenu(); closeSidebar(); } });
  window.addEventListener('resize', closeMenu);
  // Font loading and focus can cause a scroll immediately after opening a menu.
  // Close on user scroll intent rather than on those unrelated layout changes.
  document.addEventListener('wheel', closeMenu, { passive: true });
  document.addEventListener('touchmove', closeMenu, { passive: true });
  window.addEventListener('beforeunload', event => { if (state.busy) { event.preventDefault(); event.returnValue = ''; } });
  async function initialize() {
    try {
      const session = await get('/session');
      authSession = session;
      if (session?.account) {
        accountStoragePrefix = encodeURIComponent(session.account) + '.';
        const account = el('span', { class: 'chip', text: '当前账号：' + session.account, id: 'current-account' });
        $('new-project').before(account);
        if (session.logout) {
          const logout = el('button', { class: 'btn subtle', type: 'button', text: '退出登录', onclick: async () => {
            const response = await fetch('/auth/logout', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': authSession.csrf_token }, body: '{}' });
            if (response.ok || response.status === 401) {
              try { const prefix = 'skilltree.v3.' + accountStoragePrefix; for (const key of Object.keys(localStorage)) if (key.startsWith(prefix)) localStorage.removeItem(key); localStorage.setItem('skilltree.auth.changed', String(Date.now())); } catch { /* Storage may be disabled. */ }
              location.replace('/login');
            } else showMessage('退出未完成，请刷新页面再试。', 'warn');
          } });
          account.after(logout);
        }
      }
    } catch { /* Standalone local V3 has no authenticated gateway. */ }
    const initialRoute = location.hash;
    render();
    const loaded = await Promise.allSettled([get('/capabilities'), get('/material-packs'), get('/projects')]);
    if (loaded[0].status === 'fulfilled') state.capabilities = list(loaded[0].value);
    if (loaded[1].status === 'fulfilled') state.packs = list(Array.isArray(loaded[1].value) ? loaded[1].value : loaded[1].value?.packs);
    if (loaded[2].status === 'fulfilled') state.projects = asProjects(loaded[2].value);
    else showMessage('暂时无法连接学习服务。已保存的输入会留在本机，恢复连接后请刷新。', 'error');
    const selection = storage.read('selection');
    if (initialRoute.startsWith('#/p/') && selection?.id && selection.tab !== 'legacy') {
      state.tab = 'current';
      try { if (isLegacy()) await refreshList(); await loadProject(selection.id); } catch { state.id = null; state.view = null; storage.remove('selection'); }
    }
    render();
    if (initialRoute) { history.replaceState(null, '', initialRoute); await garden.readRoute(); }
    if (authSession?.csrf_token) await restoreJob();
  }
  garden = window.SkillTreeGarden({el, button, chip, list, nodesFor, currentName, state, allowed, command,
    selectProject, projectMenu, tutorCard, quizCard, recoveryCard, objectiveFeedback, budgetCard,
    sourceCard, renderPlan, storage, labels, actionLabels, render, newProject, markdown, citationButtons, textCommand, uuid});
  garden.init();
  initialize();
})();
