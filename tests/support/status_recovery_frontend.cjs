const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const {randomUUID} = require('node:crypto');
(async () => {
  const [baseURL, size, evidence] = process.argv.slice(2), width = Number(size);
  const browser = await chromium.launch({headless: true, channel: 'msedge'});
  const cases = [], errors = [];
  try {
    for (const outcome of ['failed', 'completed', 'navigation']) {
      const context = await browser.newContext({baseURL, viewport: {width, height: 960}});
      const created = await context.request.post('/projects', {data: {
        request_id: randomUUID(), intent: {goal: 'Synthetic status recovery ' + outcome, prior_knowledge: 'synthetic'}
      }});
      assert.equal(created.status(), 201);
      const initial = await created.json(), pid = initial.project_id;
      const prepared = await context.request.post('/projects/' + pid + '/resume', {data: {
        request_id: randomUUID(), pending_input_id: initial.pending_input_id,
        draft_revision: initial.draft_revision, action: 'confirm_profile'
      }});
      assert.equal(prepared.status(), 200);
      const complete = await prepared.json();
      assert.equal(complete.page_state, 'plan_review');
      const failed = {...initial, error_type: 'ModelOutputValidationError',
        preparation_notice: '这次 AI 准备没有完成，未确认任何计划。'};
      const running = {...initial, page_state: 'running', allowed_actions: [], pending_input_id: null,
        execution_status: 'active', preparation_notice: null};
      const page = await context.newPage();
      page.setDefaultTimeout(20000);
      page.on('pageerror', e => errors.push(e.message));
      let phase = 'initial', writes = 0, reads = 0;
      await page.route('**/projects/' + pid, route => {
        assert.equal(route.request().method(), 'GET');
        let view = initial;
        if (phase === 'running') {
          reads++;
          view = reads === 1 || outcome === 'navigation' ? running : outcome === 'failed' ? failed : complete;
        }
        return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(view)});
      });
      await page.route('**/projects/' + pid + '/resume', route => {
        assert.equal(route.request().method(), 'POST');
        writes++; phase = 'running';
        // A closed client connection/non-JSON proxy response is not a command failure.
        return route.fulfill({status: 502, contentType: 'text/html', body: '<p>connection closed</p>'});
      });
      await page.goto('/#/p/' + pid + '/learn', {waitUntil: 'domcontentloaded'});
      await page.getByRole('button', {name: 'AI 整理学习计划', exact: true}).click();
      await page.getByRole('heading', {name: '正在完成本次操作', exact: true}).waitFor();
      if (outcome === 'navigation') {
        await page.getByRole('button', {name: width === 390 ? '打开学习记录' : '我的花园', exact: true}).click();
        await page.getByRole('button', {name: '＋ 种一棵树', exact: true}).click();
        await page.locator('#create-form').waitFor();
      } else if (outcome === 'failed') {
        await page.getByText(failed.preparation_notice, {exact: true}).waitFor();
      } else {
        await page.getByRole('button', {name: '确认这条路线', exact: true}).waitFor();
      }
      const settledReads = reads;
      await page.waitForTimeout(3500);
      assert.equal(reads, settledReads, 'terminal state/navigation must stop status queries');
      assert.equal(writes, 1, 'status recovery must never replay the command');
      assert.equal(await page.getByRole('heading', {name: '正在完成本次操作', exact: true}).count(), 0);
      if (outcome === 'navigation') assert(await page.locator('#create-form').isVisible());
      await page.screenshot({path: evidence + '/' + outcome + '.png', fullPage: true});
      cases.push(outcome);
      await context.close();
    }
    assert.deepEqual(errors, []);
    const report = {passed: true, width, cases, errors, real_model_requests: 0};
    await fs.writeFile(evidence + '/result.json', JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
