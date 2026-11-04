/* Actual Edge browser, real server and model. Writes only new acceptance projects. */
const {chromium}=require('playwright');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const origin=process.argv[2]||'http://127.0.0.1:18780',dir=path.resolve(process.argv[3]||'work/training-demo/day01');
const password=process.env.TRAINING_ACCEPTANCE_PASSWORD||'SkillTreeDemo2026!';
const accounts=['admin@example.test','employee.a@example.test','employee.b@example.test','employee.c@example.test'];
(async()=>{
 await fs.mkdir(dir,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'}),ctx=await browser.newContext({viewport:{width:1440,height:1000}});
 const page=await ctx.newPage(),errors=[],report={origin,date:new Date().toISOString(),model:'real configured provider',roles:[],errors};
 page.setDefaultNavigationTimeout(60000);
 // Use the browser's network route for public checks, including system proxy settings.
 const requestGet=async url=>{const v=await page.evaluate(async url=>{const r=await fetch(url,{signal:AbortSignal.timeout(45000)});return{status:r.status,value:await r.json()};},url);return{status:()=>v.status,json:async()=>v.value};};
 page.on('pageerror',e=>errors.push(e.message));
 const screenshot=async name=>page.screenshot({path:path.join(dir,name+'.png'),fullPage:true});
 async function login(i){console.log('Signing in:',accounts[i]);await page.goto(origin+'/login',{waitUntil:'domcontentloaded'});await page.locator('#account').fill(accounts[i]);await page.locator('#password').fill(password);await page.locator('#login-submit').click();await page.waitForURL('**/training/'+(i?'home':'admin'),{waitUntil:'domcontentloaded'});await page.locator('#identity').filter({hasText:i?'员工':'管理员'}).waitFor();report.roles.push(accounts[i]);}
 try{
  await login(0);await page.getByText('已预置的真实登录身份').waitFor();await screenshot('admin-home');
  assert.equal(await page.locator('.member').count(),4);
  await page.setViewportSize({width:390,height:844});await screenshot('admin-mobile');assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.setViewportSize({width:1440,height:1000});
  await page.goto(origin+'/training/admin/courses');await page.getByRole('heading',{name:'功能建设中'}).waitFor();await screenshot('course-empty');
  for(const i of [2,3]){await login(i);await page.getByRole('link',{name:/查看我的任务/}).click();await page.getByRole('heading',{name:'暂时没有分配给你的学习任务'}).waitFor();assert.equal((await requestGet(origin+'/projects').then(r=>r.json())).length,0);}
  await login(1);await page.getByRole('link',{name:/开始自由学习/}).click();await page.locator('#current-account').waitFor();await page.locator('#garden-home').click();
  await page.locator('#create-form textarea[name=goal]').fill('理解百分比的含义，能计算一个数的百分之几，并区分增长百分比与百分点');
  await page.locator('#create-form textarea[name=prior]').fill('会四则运算，不熟悉百分比');
  await page.locator('#create-form textarea[name=goal]').dispatchEvent('input');
  const savedA=await page.evaluate(()=>Object.keys(localStorage).filter(k=>k.includes('employee.a%40example.test')));
  assert(savedA.length>0);
  await login(2);await page.getByRole('link',{name:/开始自由学习/}).click();await page.locator('#current-account').waitFor();await page.locator('#garden-home').click();
  assert.equal(await page.locator('#create-form textarea[name=goal]').inputValue(),'');
  const other=await requestGet(origin+'/training/api/admin/overview?role=admin');assert.equal(other.status(),403);
  const denied=await requestGet(origin+'/training/admin');assert.equal(denied.status(),403);
  report.storage_isolation=true;report.employee_admin_rejected=true;
  await login(1);await screenshot('employee-home');await page.setViewportSize({width:390,height:844});await screenshot('employee-mobile');assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.setViewportSize({width:1440,height:1000});
  await page.getByRole('link',{name:/开始自由学习/}).click();await page.locator('#current-account').waitFor();await page.locator('#garden-home').click();
  assert.match(await page.locator('#create-form textarea[name=goal]').inputValue(),/百分比/);
  const created=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/projects');
  await page.getByRole('button',{name:'种下这棵树',exact:true}).click();const result=await (await created).json();
  report.project_id=result.project_id;report.created_state=result.page_state;assert.equal(result.page_state,'profile_review');await screenshot('free-preparation');
  await page.getByRole('button',{name:'AI 整理学习计划',exact:true}).waitFor();
  const started=Date.now();await page.getByRole('button',{name:'AI 整理学习计划',exact:true}).click();
  let view;const deadline=Date.now()+420000;
  while(Date.now()<deadline){await page.waitForTimeout(2000);const r=await requestGet(origin+'/projects/'+result.project_id);assert.equal(r.status(),200);view=await r.json();if(view.page_state==='plan_review'||['error','budget_exhausted','materials_required'].includes(view.page_state))break;}
  report.elapsed_seconds=(Date.now()-started)/1000;report.plan_state=view?.page_state;report.nodes=view?.nodes?.length;report.node_titles=view?.nodes?.map(n=>n.title);
  await fs.writeFile(path.join(dir,'real-model-route.json'),JSON.stringify(view,null,2));
  assert.equal(view.page_state,'plan_review',JSON.stringify({state:view.page_state,error:view.error,actions:view.allowed_actions}));assert(view.nodes.length>0);
  await page.getByText('预览生长路线',{exact:true}).waitFor({timeout:30000});await screenshot('real-model-route');
  await page.goto(origin+'/training/materials');await page.getByRole('heading',{name:'从自己的资料开始学习'}).waitFor();await page.locator('input[name=file]').waitFor();await screenshot('materials-entry');
  await login(2);assert.equal((await requestGet(origin+'/projects').then(r=>r.json())).length,0);assert.equal((await requestGet(origin+'/projects/'+result.project_id)).status(),404);
  assert.deepEqual(errors,[]);report.passed=true;
 }catch(e){report.passed=false;report.failure=e.stack;await screenshot('failure').catch(()=>{});throw e;}
 finally{await fs.writeFile(path.join(dir,'browser-result.json'),JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
