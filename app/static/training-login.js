'use strict';
(() => {
  const form = document.querySelector('#login-form'), button = document.querySelector('#login-submit');
  const error = document.querySelector('#login-error'), mode = document.querySelector('#auth-mode');
  const confirmField = document.querySelector('#confirm-field'), confirm = document.querySelector('#confirm-password');
  const password = document.querySelector('#password');
  let registering = new URLSearchParams(location.search).has('register');
  function setMode(value) {
    registering = value;
    document.querySelector('#login-title').textContent = value ? '注册个人账号' : '登录 SkillTree';
    document.querySelector('#login-lead').textContent = value
      ? '用邮箱和密码创建个人账号。游客进度会保留在同一账号里。'
      : '已有账号可以登录；也可以注册个人账号，或直接以游客身份自主学习。';
    confirmField.hidden = !value; confirm.required = value;
    password.autocomplete = value ? 'new-password' : 'current-password';
    password.minLength = value ? 10 : 1;
    document.querySelector('#login-note').textContent = value
      ? '邮箱仅作登录名，不发送验证码。密码至少 10 位。注册后不会自动成为员工或管理员。'
      : '邮箱仅作登录名，不发送验证码。注册后是个人账号，不会自动加入单位；游客学习进度可在注册时保留。';
    mode.textContent = value ? '已有账号？返回登录' : '没有账号？注册个人账号';
    button.textContent = value ? '注册并进入' : '登录并进入';
  }
  mode.addEventListener('click', () => setMode(!registering));
  setMode(registering);
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (button.disabled) return;
    if (registering && (password.value.length < 10 || password.value !== confirm.value)) {
      error.textContent = password.value.length < 10 ? '注册密码至少 10 位。' : '两次输入的密码不一致。';
      error.hidden = false; return;
    }
    button.disabled = true; button.textContent = registering ? '正在注册…' : '正在登录…'; error.hidden = true;
    try {
      const body = {
        account: form.querySelector('#account').value.trim(),
        password: password.value,
        remember: form.querySelector('#remember').checked,
      };
      if (registering) body.confirm_password = confirm.value;
      const response = await fetch(registering ? '/auth/register' : '/auth/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-SkillTree-Login': '1'},
        body: JSON.stringify(body),
      });
      const value = await response.json();
      if (!response.ok) throw new Error(value.error?.message || (registering ? '注册暂时不可用，请稍后再试。' : '登录暂时不可用，请稍后再试。'));
      try { localStorage.setItem('skilltree.auth.changed', String(Date.now())); } catch { /* Optional cross-tab signal. */ }
      location.replace('/');
    } catch (err) {
      error.textContent = err.message || '连接失败，请稍后再试。'; error.hidden = false;
      button.disabled = false; button.textContent = registering ? '注册并进入' : '登录并进入';
    }
  });
})();
