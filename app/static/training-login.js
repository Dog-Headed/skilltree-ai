'use strict';
(() => {
  const form = document.querySelector('#login-form'), button = document.querySelector('#login-submit'), error = document.querySelector('#login-error');
  // Training always lands on the role homepage; no user-controlled role or destination.
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (button.disabled) return;
    button.disabled = true; button.textContent = '正在登录…'; error.hidden = true;
    try {
      const response = await fetch('/auth/login', {method:'POST', headers:{'Content-Type':'application/json','X-SkillTree-Login':'1'},
        body:JSON.stringify({account:form.querySelector('#account').value.trim(),password:form.querySelector('#password').value,remember:form.querySelector('#remember').checked})});
      const value = await response.json();
      if (!response.ok) throw new Error(value.error?.message || '登录暂时不可用，请稍后再试。');
      try { localStorage.setItem('skilltree.auth.changed', String(Date.now())); } catch { /* Optional cross-tab signal. */ }
      location.replace('/');
    } catch (err) { error.textContent = err.message || '连接失败，请稍后再试。'; error.hidden = false; button.disabled = false; button.textContent = '登录并进入'; }
  });
})();
