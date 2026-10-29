/* Sign-in page. The only server contract it relies on:
     GET  /session     → 200 {account} when signed in; 401 when not; 404 on the local single-user server
     POST /auth/login  {account, password, remember} → 200 {account}, sets an HttpOnly session cookie
                       401 {error:{code:'invalid_credentials'}} · 429 {error:{code:'rate_limited', retry_after}}
   A preview may supply window.SkillTreeAuthTransport with the same two methods. */
'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const controls = window.SkillTreeControls;
  const themeKey = 'skilltree.v3.theme';

  async function http(method, url, body) {
    const response = await fetch(url, { method, credentials: 'same-origin', headers: { Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json', 'X-SkillTree-Login': '1' } : {}) },
      body: body ? JSON.stringify(body) : undefined });
    let data = null;
    try { data = await response.json(); } catch { /* Empty or non-JSON body. */ }
    return { status: response.status, data };
  }
  const transport = window.SkillTreeAuthTransport || {
    session: () => http('GET', '/session'),
    login: body => http('POST', '/auth/login', body),
    register: body => http('POST', '/auth/register', body),
  };

  // Only same-origin paths may be a destination after sign-in.
  const next = (() => { const value = new URLSearchParams(location.search).get('next') || '/'; if (!/^\/(?![\/\\])/.test(value) || /[\u0000-\u0020\\]/.test(value)) return '/'; try { return new URL(value, location.origin).origin === location.origin ? value : '/'; } catch { return '/'; } })();

  const form = $('login-form'), alertBox = $('login-alert'), submit = $('login-submit');
  const account = $('account'), password = $('password');
  const confirm = $('confirm-password');
  let registering = false;
  function setMode(value) {
    registering = value;
    $('login-title').textContent = value ? '创建账号' : '欢迎回来';
    document.querySelector('.login-lead').textContent = value ? '用邮箱和密码种下第一棵学习树。' : '登录后继续照料你的学习树，进度都在这里等你。';
    $('confirm-field').hidden = !value; confirm.required = value;
    password.autocomplete = value ? 'new-password' : 'current-password';
    password.minLength = value ? 10 : 1;
    $('account-hint').textContent = value ? '邮箱只作登录名，不发送验证码；密码至少 10 位。' : '邮箱仅作登录名，不发送验证码。';
    $('auth-mode').textContent = value ? '已有账号？返回登录' : '没有账号？用邮箱注册';
    submit.textContent = value ? '注册并进入我的花园' : '进入我的花园';
    form.action = value ? '/auth/register' : '/auth/login';
    say('');
  }

  function theme() {
    let stored = null;
    try { stored = JSON.parse(localStorage.getItem(themeKey)); } catch { /* Storage can be unavailable. */ }
    if (stored === 'dark' || stored === 'light') document.documentElement.dataset.theme = stored;
    const toggle = $('theme-toggle');
    const dark = () => document.documentElement.dataset.theme === 'dark' || (!document.documentElement.dataset.theme && matchMedia('(prefers-color-scheme: dark)').matches);
    const label = () => { toggle.textContent = dark() ? '☀' : '☾'; toggle.setAttribute('aria-label', dark() ? '切换浅色外观' : '切换深色外观'); };
    toggle.addEventListener('click', () => { const value = dark() ? 'light' : 'dark'; document.documentElement.dataset.theme = value; try { localStorage.setItem(themeKey, JSON.stringify(value)); } catch { /* Not persisted. */ } label(); });
    label();
  }

  function say(text, kind = 'warn') { alertBox.textContent = text; alertBox.dataset.kind = kind; alertBox.hidden = !text; }
  function mark(field, invalid) { if (invalid) field.setAttribute('aria-invalid', 'true'); else field.removeAttribute('aria-invalid'); }

  let lockTimer = null;
  function lockFor(seconds) {
    clearInterval(lockTimer);
    let left = Math.max(1, Math.ceil(Number(seconds) || 30));
    const tick = () => {
      if (left <= 0) { clearInterval(lockTimer); submit.disabled = false; say(''); return; }
      submit.disabled = true; say(`尝试次数有点多，请 ${left} 秒后再试。`); left--;
    };
    tick(); lockTimer = setInterval(tick, 1000);
  }

  async function signIn(event) {
    event.preventDefault();
    if (submit.disabled) return;
    const name = account.value.trim();
    const missingAccount = !name || !account.checkValidity(), missingPassword = !password.value;
    mark(account, missingAccount); mark(password, missingPassword);
    if (missingAccount || missingPassword) {
      say(!name ? '请先填写邮箱。' : missingAccount ? '请填写有效邮箱。' : '请填写密码。');
      (missingAccount ? account : password).focus(); return;
    }
    if (registering && (password.value.length < 10 || password.value !== confirm.value)) {
      mark(confirm, true); say(password.value.length < 10 ? '注册密码至少 10 位。' : '两次输入的密码不一致。'); confirm.focus(); return;
    }
    say('');
    const sprout = controls ? controls.grow(submit) : { done() {}, fail() {} };
    submit.disabled = true; account.readOnly = true; password.readOnly = true; confirm.readOnly = true;
    let result;
    try { result = await (registering ? transport.register : transport.login)({ account: name, password: password.value, remember: $('remember').checked, ...(registering ? { confirm_password: confirm.value } : {}) }); }
    catch { result = { status: 0 }; }
    account.readOnly = false; password.readOnly = false; confirm.readOnly = false;
    if (result.status === 200 || result.status === 201) {
      try { localStorage.setItem('skilltree.auth.changed', String(Date.now())); } catch { /* Optional cross-tab notification. */ }
      sprout.done(2000); document.body.classList.add('welcomed'); say(registering ? '注册成功，正在进入你的花园…' : '欢迎回来，正在进入你的花园…', 'info');
      setTimeout(() => location.assign(next), 900); return;
    }
    sprout.fail(); submit.disabled = false;
    if (result.status === 401) { mark(password, true); say('邮箱或密码不正确，再试一次。'); password.select(); password.focus(); }
    else if (result.status === 429) lockFor(result.data?.error?.retry_after);
    else if (result.status === 409 || result.status === 403 || result.status === 422) say(result.data?.error?.message || '请检查注册信息，或稍后再试。');
    else if (result.status === 0) say('连不上服务器，请检查网络后再试。');
    else say(`登录服务暂时不可用（${result.status}），请稍后再试。`);
  }

  async function checkSession() {
    let result;
    try { result = await transport.session(); } catch { return; }
    if (result.status === 404 || (result.status === 200 && result.data?.account === null)) { $('local-mode').hidden = false; form.hidden = true; $('auth-mode').hidden = true; return; }
    if (result.status === 200 && result.data?.account) {
      $('signed-account').textContent = result.data.login || result.data.account; $('enter-garden').href = next; $('signed-in').hidden = false; form.hidden = true; $('auth-mode').hidden = true;
    }
  }

  theme();
  $('auth-mode').addEventListener('click', () => { if (!submit.disabled) setMode(!registering); });
  if (controls) { controls.passwordToggle(password); controls.capsLockHint(password, $('caps-hint')); }
  if (controls) controls.passwordToggle(confirm);
  for (const field of [account, password, confirm]) field.addEventListener('input', () => mark(field, false));
  form.addEventListener('submit', signIn);
  $('switch-account').addEventListener('click', () => { $('signed-in').hidden = true; form.hidden = false; $('auth-mode').hidden = false; setMode(false); form.reset(); account.focus(); });
  checkSession();
  if (!form.hidden) account.focus({ preventScroll: true });
})();
