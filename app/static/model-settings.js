'use strict';
(() => {
  const trigger = document.getElementById('model-settings-button');
  if (!trigger) return;
  const make = (tag, text, className) => {
    const n = document.createElement(tag);
    if (text) n.textContent = text;
    if (className) n.className = className;
    return n;
  };
  const dialog = make('dialog', null, 'model-settings-dialog');
  dialog.id = 'model-settings-dialog'; dialog.setAttribute('aria-labelledby', 'model-settings-title');
  const title = make('h2', '模型设置'); title.id = 'model-settings-title';
  const close = make('button', '×', 'icon-button'); close.type = 'button'; close.setAttribute('aria-label', '关闭模型设置');
  const head = make('div', null, 'modal-head'); head.append(title, close);
  const intro = make('p', '选择后续学习使用的模型。已经生成的课程和学习进度会保留。', 'model-settings-note');
  const form = make('form'); form.autocomplete = 'off';
  const provider = make('select'); provider.id = 'model-provider';
  const source = make('select'); source.id = 'model-key-source';
  for (const [value, label] of [['platform', '使用平台额度'], ['personal', '使用自己的 API Key']]) {
    const option = make('option', label); option.value = value; source.append(option);
  }
  const key = make('input'); key.id = 'model-api-key'; key.type = 'password'; key.maxLength = 512;
  key.autocomplete = 'new-password'; key.spellcheck = false; key.setAttribute('autocapitalize', 'none');
  const saved = make('small'); saved.id = 'model-key-status'; key.setAttribute('aria-describedby', saved.id);
  const remove = make('input'); remove.type = 'checkbox'; remove.id = 'model-remove-key';
  const removeLabel = make('label', null, 'check-label'); removeLabel.htmlFor = remove.id;
  removeLabel.append(remove, make('span', '删除这个模型已保存的个人密钥，改用平台额度'));
  const field = (text, control) => { const label = make('label', null, 'field'); label.htmlFor = control.id; label.append(make('span', text), control); return label; };
  const keyField = field('API Key', key); keyField.append(saved);
  const status = make('p', '', 'model-settings-status'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  const save = make('button', '保存设置', 'btn primary'); save.type = 'button';
  const actions = make('div', null, 'actions'); actions.append(save);
  const notice = make('p', '个人密钥加密保存在服务器，只用于当前账号，不会再次显示。请填写对应平台的官方 API Key；保存设置不会调用模型。个人密钥仍遵循本站每日操作上限与并发限制，模型费用由对应平台计费。', 'model-settings-note');
  form.append(field('学习模型', provider), field('调用方式', source), keyField, removeLabel, notice, status, actions);
  dialog.append(head, intro, form); document.body.append(dialog);
  let settings = null, working = false;
  const info = () => settings?.providers.find(p => p.id === provider.value);
  function refresh() {
    const choice = info(), busy = Boolean(settings?.busy), own = source.value === 'personal';
    provider.disabled = source.disabled = !settings || working || busy;
    keyField.hidden = !own; key.disabled = !own || !settings || working || busy || remove.checked;
    key.placeholder = choice?.has_personal_key ? '已保存，留空继续使用；填写可替换' : '填写此模型的官方 API Key';
    saved.textContent = choice?.has_personal_key ? '此模型已保存个人密钥，密钥不会回显。' : '此模型尚未保存个人密钥。';
    removeLabel.hidden = !choice?.has_personal_key;
    remove.disabled = !settings || working || busy;
    save.disabled = !settings || working || busy;
    save.textContent = working ? '正在保存…' : '保存设置';
    if (busy) status.textContent = '当前有任务正在执行或排队，完成后重新打开本窗口即可切换。';
    const selected = settings?.providers.find(p => p.id === settings.provider);
    if (selected) {
      trigger.textContent = '模型设置 · ' + selected.label + (settings.key_source === 'personal' ? ' · 个人' : '');
    }
  }
  async function readSettings() {
    const response = await fetch('/model-settings', {credentials: 'same-origin', cache: 'no-store'});
    const value = await response.json();
    if (!response.ok) throw new Error(value.error?.message || '读取设置失败，请刷新页面后重试。');
    return value;
  }
  async function open() {
    document.getElementById('sidebar').classList.remove('open');
    document.getElementById('sidebar-shade').hidden = true;
    document.getElementById('mobile-menu').setAttribute('aria-expanded', 'false');
    key.value = ''; remove.checked = false; status.textContent = '正在读取设置…'; settings = null; refresh();
    if (!dialog.open) dialog.showModal();
    try {
      settings = await readSettings(); provider.replaceChildren();
      for (const p of settings.providers) { const option = make('option', p.label + ' · ' + p.model); option.value = p.id; provider.append(option); }
      provider.value = settings.provider; source.value = settings.key_source; status.textContent = ''; refresh();
    } catch (error) { status.textContent = error.message; }
  }
  async function submit(event) {
    event?.preventDefault(); if (!settings || working || settings.busy) return;
    const payload = {provider: provider.value, key_source: source.value, remove_key: remove.checked};
    if (key.value.trim() && source.value === 'personal') payload.api_key = key.value.trim();
    working = true; status.textContent = ''; refresh();
    try {
      const sessionResponse = await fetch('/session', {cache: 'no-store', credentials: 'same-origin'});
      const session = await sessionResponse.json();
      if (!sessionResponse.ok || !session.csrf_token) throw new Error('登录状态已更新，请刷新页面后重试。');
      const response = await fetch('/model-settings', {method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token}, body: JSON.stringify(payload)});
      const value = await response.json();
      if (!response.ok) {
        if (response.status === 409) settings.busy = true;
        throw new Error(value.error?.message || '保存失败，请稍后再试。');
      }
      settings = value; key.value = ''; remove.checked = false;
      status.textContent = '已保存，下一次学习操作将使用所选模型。';
    } catch (error) { status.textContent = error.message || '网络异常，请重新打开设置确认是否已保存。'; }
    finally { working = false; refresh(); }
  }
  trigger.addEventListener('click', open); close.addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { key.value = ''; remove.checked = false; });
  provider.addEventListener('change', () => { key.value = ''; remove.checked = false; status.textContent = ''; refresh(); });
  source.addEventListener('change', () => { key.value = ''; remove.checked = false; refresh(); });
  remove.addEventListener('change', () => { if (remove.checked) { source.value = 'platform'; key.value = ''; } refresh(); });
  save.addEventListener('click', submit); form.addEventListener('submit', submit);
  key.addEventListener('keydown', e => { if (e.key === 'Enter') submit(e); });
  readSettings().then(value => { settings = value; refresh(); }).catch(() => { trigger.textContent = '模型设置'; });
})();
