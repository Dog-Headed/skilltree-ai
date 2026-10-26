/* Isolated, actual shipped-page checks. The Fake validates control flow only.
 * No deployment project, retained evaluation case, or real provider is opened. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const [baseURL, scenario, evidence] = process.argv.slice(2);
  const browser = await chromium.launch({ headless: true,
    ...(process.env.SKILLTREE_TEST_BROWSER_CHANNEL ? { channel: process.env.SKILLTREE_TEST_BROWSER_CHANNEL } : {}) });
  const mobile = scenario === 'mobile-refresh-bind';
  const context = await browser.newContext({ baseURL, viewport: { width: mobile ? 390 : 1440, height: mobile ? 844 : 960 } });
  const page = await context.newPage(); page.setDefaultTimeout(15000);
  const requests = [], responseSnapshots = [], errors = [], checks = {};
  const privateMarker = 'BROWSER_PRIVATE_BODY_' + scenario.replaceAll('-', '_');
  const privateTitle = '仅本机参考标题 <img src=x onerror="window.__privateTitleExecuted=1"> ' + scenario;
  let pid, decision = ['explicit-exclude', 'missing-choice'].includes(scenario) ? 'exclude' : 'bind';
  page.on('pageerror', e => errors.push(e.message));
  context.on('request', request => {
    const url = new URL(request.url());
    if (url.origin !== baseURL) return;
    requests.push({ method: request.method(), path: url.pathname,
      body: request.method() === 'POST' ? request.postDataJSON() : null });
  });
  context.on('response', async response => {
    const request = response.request(), url = new URL(request.url());
    if (url.origin !== baseURL || !url.pathname.startsWith('/projects')) return;
    try { responseSnapshots.push({ method: request.method(), path: url.pathname,
      status: response.status(), body: await response.json() }); } catch { /* Requests aborted by navigation are not privacy evidence. */ }
  });
  const api = async route => { const response = await context.request.get(route); assert.equal(response.status(), 200); return response.json(); };
  const idle = target => target.locator('body[aria-busy="false"]').waitFor();
  const click = (name, target = page) => target.getByRole('button', { name, exact: true }).click();
  async function writeClick(name, target = page) {
    const sent = target.waitForRequest(r => r.method() === 'POST');
    await click(name, target); await sent; await idle(target);
  }
  const confirmations = () => requests.filter(r => r.method === 'POST' && r.body?.action === 'confirm_plan');
  async function createAndPlan() {
    await page.goto('/'); await page.locator('.preset-button').first().waitFor();
    const pack = (await api('/material-packs')).find(p => p.subject === 'mathematics');
    const details = await api('/material-packs/mathematics');
    await page.locator('.preset-button').filter({ hasText: pack.title }).click();
    await page.waitForFunction(topic => document.querySelector('#create-form textarea[name=goal]').value === topic, details.profile.goal);
    await writeClick('创建学习记录');
    pid = requests.find(r => r.method === 'POST' && r.path === '/projects').body.request_id.replaceAll('-', ''); pid = 'v3_' + pid;
    await click('导入示例资料'); await page.getByRole('dialog').getByRole('button', { name: pack.title, exact: true }).click();
    await writeClick('确认继续'); await writeClick('AI 整理学习计划');
    assert.equal((await api('/projects/' + pid)).page_state, 'plan_review');
  }
  async function importText(title, content, privateVisibility = true) {
    await click('＋ 粘贴 / 上传资料'); const dialog = page.getByRole('dialog');
    await dialog.locator('input[name=title]').fill(title);
    await dialog.locator('textarea[name=source_description]').fill('隔离技术测试来源；不作正式内容质量评价。');
    await dialog.locator('textarea[name=content]').fill(content);
    await dialog.locator('select[name=visibility]').selectOption(privateVisibility ? 'assessment_private' : 'teaching');
    await writeClick('导入资料');
  }
  async function importPrivateAndReplan() {
    await importText(privateTitle, '# 评价参考\n' + privateMarker + '\n对等式两边做同样运算，并代回验证。');
    const after = await api('/projects/' + pid);
    assert.equal(after.requires_replan, true); assert.equal(after.allowed_actions.includes('confirm_plan'), false);
    assert.equal(after.private_references.length, 1);
    assert.deepEqual(Object.keys(after.private_references[0]).sort(), ['label', 'reference_id']);
    await writeClick('重新规划');
    await page.getByRole('heading', { name: '评价参考的用途', exact: true }).waitFor();
    assert.match(await page.locator('.reference-choice strong').innerText(), /仅本机参考标题/);
    assert.equal(await page.locator('.reference-choice img').count(), 0);
    return api('/projects/' + pid);
  }
  async function choose(target, mode = decision) {
    await target.locator('.reference-choice select').selectOption(mode);
    if (mode === 'bind') await target.locator('.reference-choice input[value=node_1]').check();
  }
  async function assertPrivacy(target = page) {
    assert.equal((await target.locator('body').innerText()).includes(privateMarker), false);
    assert.equal(await target.evaluate(marker => [...document.querySelectorAll('input,textarea')]
      .some(element => element.value?.includes(marker)), privateMarker), false,
    'A closed import form must not retain the private reference body in the DOM');
    assert.equal(await target.evaluate(() => window.__privateTitleExecuted || window.__materialExecuted || null), null);
    for (const snapshot of responseSnapshots) {
      const text = JSON.stringify(snapshot.body);
      assert.equal(text.includes(privateMarker), false, 'Private body appeared in a public response: ' + snapshot.path);
      assert.equal(text.includes(privateTitle), false, 'Private title appeared in a public response: ' + snapshot.path);
    }
  }
  async function assertNoOverflow(target = page) {
    assert.equal(await target.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, 'Viewport has horizontal overflow');
    for (const node of await target.locator('.reference-choice select,.reference-targets label').all()) {
      const bounds = await node.boundingBox(); if (bounds) { assert.ok(bounds.x >= 0); assert.ok(bounds.x + bounds.width <= (mobile ? 390 : 1440)); }
    }
  }
  try {
    await createAndPlan(); const firstPlan = await importPrivateAndReplan();
    if (scenario === 'mobile-refresh-bind') {
      await page.evaluate(id => localStorage.removeItem('skilltree.v3.reference-labels-' + id), pid);
      await page.reload(); await page.locator('.reference-choice').waitFor();
      assert.equal(await page.locator('.reference-choice strong').innerText(), '评价参考 1');
      checks.generic_label_after_cache_clear = true;
      await choose(page); await assertNoOverflow();
      await page.screenshot({ path: path.join(evidence, 'mobile-generic-reference-selected.png'), fullPage: true });
    } else if (scenario === 'missing-choice') {
      const before = confirmations().length;
      await click('确认并冻结计划'); assert.match(await page.locator('#message').innerText(), /请为每份评价参考选择/);
      assert.equal(confirmations().length, before, 'Unselected reference must not send a POST');
      checks.missing_purpose_post_count = confirmations().length - before;
      await page.locator('.reference-choice select').selectOption('bind');
      await click('确认并冻结计划'); assert.match(await page.locator('#message').innerText(), /请为每份评价参考选择/);
      assert.equal(confirmations().length, before, 'Binding without nodes must not send a POST');
      checks.missing_nodes_post_count = confirmations().length - before;
      await choose(page, 'exclude');
    } else if (scenario === 'safe-text') {
      const publicTitle = '公开脚本文本检查';
      const malicious = '<script>window.__materialExecuted=1</script>\n<img src=x onerror="window.__materialExecuted=2">';
      await importText(publicTitle, '# 安全文本\n' + malicious, false);
      await page.locator('.source-row').filter({ hasText: publicTitle }).getByRole('button', { name: '查看来源', exact: true }).click();
      await page.getByRole('dialog').locator('.source-content').waitFor();
      assert.match(await page.getByRole('dialog').locator('.source-content').innerText(), /<script>/);
      assert.equal(await page.getByRole('dialog').locator('script,img').count(), 0);
      checks.source_html_rendered_as_text = true;
      await page.screenshot({ path: path.join(evidence, 'safe-public-source-text.png'), fullPage: true });
      await click('关闭弹窗'); await writeClick('重新规划'); await choose(page);
    } else await choose(page);

    if (scenario === 'stale-and-duplicate') {
      const stale = await context.newPage(); stale.setDefaultTimeout(15000);
      await stale.goto('/'); await stale.locator('.reference-choice').waitFor(); await choose(stale);
      let release, started; const gate = new Promise(resolve => { release = resolve; }); const arrived = new Promise(resolve => { started = resolve; });
      let intercepted = false;
      await page.route('**/projects/' + pid + '/resume', async route => {
        if (!intercepted && route.request().postDataJSON()?.action === 'confirm_plan') { intercepted = true; started(); await gate; }
        return route.continue();
      });
      const before = confirmations().length;
      await page.getByRole('button', { name: '确认并冻结计划', exact: true }).dblclick(); await arrived;
      assert.equal(confirmations().length, before + 1, 'A double click must submit only once');
      checks.double_click_post_count = confirmations().length - before;
      assert.equal(await page.getByRole('button', { name: '确认并冻结计划', exact: true }).isEnabled(), false);
      release(); await idle(page);
      const original = confirmations().at(-1).body;
      const replay = await context.request.post('/projects/' + pid + '/resume', { data: original });
      assert.equal(replay.status(), 200, 'Exact request replay must reuse frozen facts');
      checks.exact_replay_status = replay.status();
      const rejected = stale.waitForResponse(r => r.url().endsWith('/resume') && r.status() === 409);
      await writeClick('确认并冻结计划', stale); checks.stale_confirmation_status = (await rejected).status();
      assert.match(await stale.locator('#message').innerText(), /过期|最新|变化|冲突/);
      await stale.getByRole('button', { name: '开始学习', exact: true }).waitFor({ state: 'visible' });
      await stale.screenshot({ path: path.join(evidence, 'stale-confirmation-refreshed.png'), fullPage: true });
      await stale.close();
    } else await writeClick('确认并冻结计划');

    const frozen = await api('/projects/' + pid);
    assert.equal(frozen.frozen, true); assert.deepEqual(frozen.private_references, []);
    const submitted = confirmations().at(-1).body;
    assert.equal(submitted.private_references.length, 1);
    assert.equal(submitted.private_references[0].reference_id, firstPlan.private_references[0].reference_id);
    assert.equal(submitted.private_references[0].action, decision);
    assert.deepEqual(submitted.private_references[0].node_ids, decision === 'bind' ? ['node_1'] : []);
    await page.screenshot({ path: path.join(evidence, mobile ? 'mobile-frozen-plan.png' : 'desktop-frozen-plan.png'), fullPage: true });
    await writeClick('开始学习'); assert.equal((await api('/projects/' + pid)).page_state, 'learning');
    await assertPrivacy(); await assertNoOverflow(); assert.deepEqual(errors, []);
    await page.screenshot({ path: path.join(evidence, mobile ? 'mobile-learning.png' : 'desktop-learning.png'), fullPage: true });
    await fs.writeFile(path.join(evidence, 'result.json'), JSON.stringify({ scenario, passed: true, project_id: pid, decision,
      viewport: { width: mobile ? 390 : 1440, height: mobile ? 844 : 960 }, private_marker: privateMarker,
      confirmation_request_count: confirmations().length, public_response_count: responseSnapshots.length,
      checks: { ...checks, private_body_absent_from_dom: true, private_body_absent_from_public_responses: true,
        no_script_execution: true, no_horizontal_overflow: true },
      page_errors: errors, requests, response_statuses: responseSnapshots.map(({ method, path, status }) => ({ method, path, status })) }, null, 2));
  } catch (error) {
    await page.screenshot({ path: path.join(evidence, 'failed.png'), fullPage: true }).catch(() => {});
    await fs.writeFile(path.join(evidence, 'failure.json'), JSON.stringify({ scenario, project_id: pid, error: error.stack, errors, requests }, null, 2)).catch(() => {});
    throw error;
  } finally { await context.close(); await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
