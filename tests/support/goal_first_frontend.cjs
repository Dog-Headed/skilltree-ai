const {chromium}=require('playwright');const assert=require('node:assert/strict');const fs=require('node:fs/promises');
(async()=>{
 const [baseURL,size,evidence]=process.argv.slice(2),width=Number(size);
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const context=await browser.newContext({baseURL,viewport:{width,height:width===390?844:960},reducedMotion:'no-preference'});
 const page=await context.newPage();page.setDefaultTimeout(15000);
 const requests=[],errors=[],ids=[];
 let releaseCreation;
 await page.route('**/projects',async route=>{
  if(route.request().method()==='POST')await new Promise(resolve=>{releaseCreation=resolve;});
  await route.continue();
 });
 page.on('request',r=>requests.push({method:r.method(),path:new URL(r.url()).pathname}));page.on('pageerror',e=>errors.push(e.message));
 const api=async path=>{const r=await context.request.get(path);assert.equal(r.status(),200);return r.json();};
 const click=name=>page.getByRole('button',{name,exact:true}).click();
 const write=async name=>{
  const sent=page.waitForRequest(r=>r.method()==='POST');await click(name);await sent;
  if(name==='种下这棵树'){
   await page.locator('#busy-notice:visible').waitFor();
   assert.equal(await page.locator('#busy-text').evaluate(n=>getComputedStyle(n).animationName),'thinking-shimmer');
   assert.equal(await page.locator('.thinking-dots i').count(),3);
   await page.screenshot({path:evidence+'/thinking.png',animations:'allow'});
   await page.emulateMedia({reducedMotion:'reduce'});
   assert.equal(await page.locator('#busy-text').evaluate(n=>getComputedStyle(n).animationName),'none');
   await page.emulateMedia({reducedMotion:'no-preference'});
   releaseCreation();
  }
  await page.locator('body[aria-busy="false"]').waitFor();
 };
 const create=async goal=>{
  await page.locator('#create-form textarea[name=goal]').fill(goal);await page.locator('#create-form textarea[name=prior]').fill('零基础');
  await write('种下这棵树');const list=await api('/projects');const project=list[0];ids.push(project.project_id);return project.project_id;
 };
 try{
  await page.goto('/');await page.locator('#create-form').waitFor();
  await page.evaluate(()=>localStorage.setItem('skilltree.v3.selection',JSON.stringify({id:'project_old_v2',tab:'legacy'})));
  await page.reload();await page.locator('#create-form').waitFor();
  assert.equal(await page.getByRole('button',{name:'V2 历史',exact:true}).count(),0);
  for(const field of ['bounded_goal','subject_label','topic','learning_mode','capability','scope_in','scope_out'])assert.equal(await page.locator('#create-form [name='+field+']').count(),0);
  assert.equal(await page.locator('#create-form textarea').count(),2);
  await page.screenshot({path:evidence+'/create.png',fullPage:true,animations:'disabled'});
  const first=await create('从零学习英语基础');assert.deepEqual((await api('/projects/'+first)).sources,[]);
  await write('AI 整理学习计划');let view=await api('/projects/'+first);assert.equal(view.page_state,'plan_review');
  assert.equal(view.learning_basis,'ai_generated');assert.match(view.sources[0].trust_note,/AI生成/);
  await write('确认这条路线');await write('开始学习');await write('我准备好了，开始小测');
  await page.locator('#quiz-form textarea').fill('我依据这份Fake流程资料说明规则及理由；这是合成验收答案，不代表真人学习成绩。');
  await write('提交这次小测');assert.equal((await api('/projects/'+first)).page_state,'completed');
  await page.getByRole('heading',{name:'这片叶子长成了',exact:true}).waitFor();
  assert.equal(await page.locator('.result-plant .a-unfurl').count(),1);
  await page.screenshot({path:evidence+'/result.png',fullPage:true,animations:'disabled'});
  await page.reload();await page.getByRole('heading',{name:'这片叶子长成了',exact:true}).waitFor();
  assert.equal(await page.locator('.a-unfurl').count(),0);
  await click('回到生长图谱');
  const writesBeforeReplay=requests.filter(r=>r.method==='POST').length;
  await click('重播生长');
  assert(await page.locator('.a-sprout').count()>0);
  assert.equal(requests.filter(r=>r.method==='POST').length,writesBeforeReplay);
  await click('结果');
  await click('查看学习小结');await page.getByRole('heading',{name:'这次学习已经完成',exact:true}).waitFor();
  await click(width===390?'打开学习记录':'我的花园');
  await click('＋ 种一棵树');await page.locator('#create-form').waitFor();
  const second=await create('学习本公司的培训制度');await write('AI 整理学习计划');view=await api('/projects/'+second);
  assert.equal(view.page_state,'materials_required');assert.equal(view.learning_basis,'requires_material');
  assert.match(await page.locator('#content').innerText(),/不会由AI编造/);
  await click('＋ 粘贴 / 上传资料');const dialog=page.getByRole('dialog');
  await dialog.locator('input[name=title]').fill('合成培训制度');await dialog.locator('textarea[name=source_description]').fill('测试提供的合成制度，不是现实公司政策');
  await dialog.locator('input[type=file]').setInputFiles({name:'training.md',mimeType:'text/markdown',buffer:Buffer.from('# 培训规则\n每周五安排一小时培训，不能参加时提前一天向负责人申请。文件没有规定罚款，不得编造罚款。','utf8')});
  await write('导入资料');await write('重新规划');view=await api('/projects/'+second);
  assert.equal(view.learning_basis,'provided_material');assert.equal(view.sources.length,1);
  await write('确认这条路线');await write('开始学习');view=await api('/projects/'+second);
  assert.match(view.tutor.text,/每周五/);assert.equal(view.learning_basis,'provided_material');
  await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:evidence+'/provided-learning.png',fullPage:true,animations:'disabled'});
  assert.deepEqual(errors,[]);
  const report={passed:true,width,project_ids:ids,legacy_requests:requests.filter(r=>r.path.startsWith('/legacy/')),errors,scope:'Fake flow only; actual browser and UTF-8 file upload, not content-quality validation'};
  await fs.writeFile(evidence+'/result.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
