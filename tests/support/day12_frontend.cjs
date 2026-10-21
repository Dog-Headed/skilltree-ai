/* Exercise the shipped HTML/JS in a fresh headless browser, never the user's
 * open browser/profile. All writes target the pytest-owned Fake server. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const [baseURL, scenario, evidence] = process.argv.slice(2);
  const browser = await chromium.launch({ headless: true,
    ...(process.env.SKILLTREE_TEST_BROWSER_CHANNEL ? { channel: process.env.SKILLTREE_TEST_BROWSER_CHANNEL } : {}) });
  const context = await browser.newContext({ baseURL, viewport: { width: 1440, height: 960 } });
  const page = await context.newPage(); page.setDefaultTimeout(15000);
  const requests = [], errors = [], ids = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => requests.push({ method: request.method(), path: new URL(request.url()).pathname,
    body: request.method() === 'POST' ? request.postDataJSON() : null }));
  const api = async route => { const response = await context.request.get(route); assert.equal(response.status(), 200); return response.json(); };
  const pending = () => page.evaluate(() => JSON.parse(localStorage.getItem('skilltree.v3.creation-request')));
  const idle = () => page.locator('body[aria-busy="false"]').waitFor();
  const clicks = name => page.getByRole('button', { name, exact: true }).click();
  async function writeClick(name) {
    const sent = page.waitForRequest(request => request.method() === 'POST');
    await clicks(name); await sent; await idle();
  }
  async function preset(subject = 'mathematics') {
    const pack = await api('/material-packs/' + subject);
    const option = (await api('/material-packs')).find(item => item.subject === subject);
    await page.locator('.preset-button').filter({ hasText: option.title }).click();
    await page.locator('#create-form input[name="topic"]').filter({ visible: true }).waitFor();
    await page.waitForFunction(topic => document.querySelector('#create-form input[name="topic"]').value === topic, pack.profile.topic);
    return pack;
  }
  const creations = () => requests.filter(r => r.method === 'POST' && r.path === '/projects');
  async function create(subject = 'mathematics') {
    if (!(await page.locator('#create-form').count())) await clicks('＋ 新建学习');
    await page.locator('#create-form').waitFor(); await preset(subject);
    await writeClick('创建学习记录');
    const request = creations().at(-1), pid = 'v3_' + request.body.request_id.replaceAll('-', '');
    ids.push(pid); return { pid, request, view: await api('/projects/' + pid) };
  }
  async function openImport(subject) {
    const pack = await api('/material-packs/' + subject);
    const option = (await api('/material-packs')).find(item => item.subject === subject);
    await clicks('导入示例资料');
    await page.getByRole('dialog').getByRole('button', { name: option.title, exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: '确认继续', exact: true }).waitFor();
  }
  async function importPack(subject) { await openImport(subject); await writeClick('确认继续'); }
  async function assertListEnabled() {
    const buttons = page.locator('#project-list button'); assert.ok(await buttons.count() >= 4);
    for (const button of await buttons.all()) assert.equal(await button.isEnabled(), true);
  }
  async function selectAndOpenMenu(topic) {
    await page.locator('.project-link').filter({ hasText: topic }).first().click();
    await page.waitForFunction(title => document.getElementById('page-title').textContent === title, topic);
    await page.locator('.project-row.active .project-more').click();
    assert.equal(await page.getByRole('menuitem', { name: '重命名', exact: true }).isVisible(), true);
  }
  try {
    await page.goto('/'); await page.locator('.preset-button').first().waitFor();
    if (scenario === 'completed-new') {
      const a = await create(); await importPack('mathematics');
      await writeClick('确认档案与范围'); await writeClick('确认并冻结计划'); await writeClick('开始学习');
      for (const answer of ['-5', '7']) {
        await writeClick('开始测评');
        await page.locator('#quiz-form .answer-numeric').fill(answer);
        await page.locator('#quiz-form textarea').fill('对等式两边做同样的运算，并将结果代回验证。');
        await writeClick('提交本卷答案');
      }
      const finished = await api('/projects/' + a.pid);
      assert.equal(finished.page_state, 'completed'); assert.equal(finished.completed_node_ids.length, 2);
      assert.equal(await pending(), null);
      await clicks('＋ 新建学习'); const b = await create();
      assert.notEqual(b.pid, a.pid); assert.notEqual(b.request.body.request_id, a.request.body.request_id);
      assert.deepEqual(b.request.body.profile, a.request.body.profile);
      assert.equal(b.view.page_state, 'profile_review'); assert.deepEqual(b.view.completed_node_ids || [], []);
      assert.deepEqual(await api('/projects/' + a.pid), finished);
      assert.equal(await pending(), null);
    } else if (['response-lost-found', 'response-lost-unreadable', 'create-not-committed'].includes(scenario)) {
      let first = true, failedId, hideQuery = scenario === 'response-lost-unreadable';
      await page.route('**/projects', async route => {
        if (route.request().method() !== 'POST' || !first) return route.continue();
        first = false; failedId = 'v3_' + route.request().postDataJSON().request_id.replaceAll('-', '');
        if (scenario === 'create-not-committed') return route.abort('connectionfailed');
        await route.fetch(); return route.fulfill({ status: 200, contentType: 'application/json', body: '{' });
      });
      await page.route('**/projects/*', route => hideQuery && route.request().method() === 'GET'
        ? route.abort('connectionfailed') : route.continue());
      await preset(); await writeClick('创建学习记录');
      assert.equal(creations().length, 1, 'A lost response must not automatically replay the POST');
      assert.ok(requests.some(r => r.method === 'GET' && r.path === '/projects/' + failedId));
      if (scenario === 'response-lost-found') {
        ids.push(failedId); assert.equal(await pending(), null);
        await clicks('＋ 新建学习'); const next = await create(); assert.notEqual(next.pid, failedId);
      } else {
        const original = await pending(); assert.equal(original.request_id, creations()[0].body.request_id);
        // Reload and the explicit New button must preserve an unresolved attempt.
        await page.reload(); await page.locator('.preset-button').first().waitFor();
        await clicks('＋ 新建学习'); await idle();
        assert.equal((await pending()).request_id, original.request_id);
        hideQuery = false; await preset(); await writeClick('创建学习记录');
        assert.equal(creations().length, 2); assert.deepEqual(creations()[0].body, creations()[1].body);
        assert.equal(await pending(), null); ids.push(failedId);
        assert.equal((await api('/projects/' + failedId)).page_state, 'profile_review');
      }
    } else if (scenario === 'legacy-request') {
      const a = await create(); await clicks('＋ 新建学习'); const b = await create('english');
      // Simulate the stale successful request retained by the older frontend.
      await page.evaluate(record => localStorage.setItem('skilltree.v3.creation-request', JSON.stringify(record)),
        { request_id: a.request.body.request_id, profile: JSON.stringify(a.request.body.profile) });
      await clicks('＋ 新建学习'); await page.locator('#create-form').waitFor();
      assert.equal(await pending(), null);
      const c = await create(); assert.notEqual(c.pid, a.pid); assert.notEqual(c.pid, b.pid);
      assert.deepEqual(c.request.body.profile, a.request.body.profile);
    } else {
      const a = await create(); await clicks('＋ 新建学习'); const b = await create('english');
      let release; const gate = new Promise(resolve => { release = resolve; });
      let started; const arrived = new Promise(resolve => { started = resolve; });
      let injected = false, hideQuery = false;
      await page.route('**/projects/' + b.pid + '/sources', async route => {
        if (route.request().method() !== 'POST' || injected) return route.continue();
        injected = true; started(); await gate;
        if (scenario !== 'import-success') { hideQuery = scenario === 'import-recovery-failure'; return route.abort('connectionfailed'); }
        return route.continue();
      });
      await page.route('**/projects/' + b.pid, route => hideQuery ? route.abort('connectionfailed') : route.continue());
      await openImport('english'); await clicks('确认继续'); await arrived;
      for (const button of await page.locator('#project-list button').all()) assert.equal(await button.isEnabled(), false);
      assert.equal(await page.locator('#new-project').isEnabled(), false);
      release(); await idle();
      await assertListEnabled();
      if (scenario === 'import-success') {
        assert.match(await page.locator('#message').innerText(), /已导入/);
        assert.ok((await api('/projects/' + b.pid)).sources.length > 0);
      } else {
        assert.match(await page.locator('#message').innerText(), /最新状态/);
        await clicks('关闭弹窗');
      }
      await selectAndOpenMenu(a.view.profile.topic);
    }
    assert.deepEqual(errors, [], 'No uncaught page errors');
    await page.screenshot({ path: path.join(evidence, 'page.png'), fullPage: true });
    await fs.writeFile(path.join(evidence, 'result.json'), JSON.stringify({ scenario, passed: true,
      project_ids: [...new Set(ids)], requests }, null, 2));
  } catch (error) {
    await page.screenshot({ path: path.join(evidence, 'failed.png'), fullPage: true }).catch(() => {});
    throw error;
  } finally { await context.close(); await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
