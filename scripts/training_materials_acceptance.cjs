/* Real browser, genuine files and configured real model; never writes learning facts. */
const {chromium}=require('playwright');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const origin=process.argv[2]||'http://127.0.0.1:18780',out=path.resolve(process.argv[3]||'work/training-demo/day02/browser');
const realFile=process.argv[4]||path.resolve('docs/training-demo/samples/培训制度.docx');
const report={origin,date:new Date().toISOString(),model:'real configured provider',uploads:[],errors:[]};
(async()=>{
 await fs.mkdir(out,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge',args:['--no-proxy-server']});
 const ctx=await browser.newContext({viewport:{width:1440,height:1000}}),page=await ctx.newPage();page.setDefaultTimeout(30000);page.setDefaultNavigationTimeout(60000);
 page.on('pageerror',e=>report.errors.push(e.message));
 const request=async(method,url,body)=>page.evaluate(async({method,url,body})=>{const s=await(await fetch('/session')).json();const r=await fetch(url,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':s.csrf_token},...(body?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(60000)});return{status:r.status,value:await r.json()};},{method,url,body});
 const get=url=>request('GET',url),post=(url,body)=>request('POST',url,body);
 const shot=name=>page.screenshot({path:path.join(out,name+'.png'),fullPage:true});
 async function upload(file,unit=false){
  await page.goto(origin+(unit?'/training/admin/materials':'/training/materials'),{waitUntil:'domcontentloaded'});
  await page.locator('input[name=file]').setInputFiles(file);
  const response=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/training/api/'+(unit?'admin/':'')+'materials');
  await page.getByRole('button',{name:'上传并解析',exact:true}).click();const r=await response,v=await r.json();
  assert.equal(r.status(),201,JSON.stringify(v));assert.equal(v.status,'ready');await page.locator('.material-preview details').waitFor();await page.locator('.material-preview summary').click();
  assert((await page.locator('.material-text').innerText()).length>0);
  report.uploads.push({file:path.basename(file),id:v.id,scope:unit?'unit':'private',parser:v.parsed.parser,bytes:v.parsed.original_bytes,sha256:v.parsed.original_sha256,chars:v.parsed.content.length,locations:v.parsed.blocks.map(b=>b.location)});
  return v;
 }
 async function waitProject(pid,states,seconds=480){
  const until=Date.now()+seconds*1000;let view;
  while(Date.now()<until){await page.waitForTimeout(2000);const r=await get('/projects/'+pid);assert.equal(r.status,200);view=r.value;if(states.includes(view.page_state))return view;if(['error','budget_exhausted','materials_required'].includes(view.page_state))throw Error(JSON.stringify(view));}
  throw Error('Timed out: '+JSON.stringify(view));
 }
 try{
  await page.goto(origin+'/',{waitUntil:'domcontentloaded'});await page.getByRole('link',{name:/查看资料入口/}).waitFor();
  const identity=await get('/session');assert.equal(identity.value.training.role,'guest');report.account=identity.value.account;
  for(const name of ['岗位手册.pdf','培训制度.docx','岗位职责表.xlsx','入职流程.pptx']){await upload(path.resolve('docs/training-demo/samples',name));await shot('sample-'+path.extname(name).slice(1));}
  await page.setViewportSize({width:390,height:844});await shot('materials-mobile');assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.setViewportSize({width:1440,height:1000});
  const asset=await upload(realFile);report.material_id=asset.id;await shot('real-document-preview');
  await page.locator('textarea[name=goal]').fill('依据上传的《'+asset.title+'》，学习文中的核心要求、适用条件、重点任务与责任分工。仅按资料原文规划，不补造内部规定。');
  const create=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/projects');
  await page.getByRole('button',{name:'用这份资料准备课程',exact:true}).click();const created=await(await create).json();report.project_id=created.project_id;
  await page.waitForURL('**/learn#/p/'+created.project_id+'/learn',{waitUntil:'commit'});await page.getByRole('button',{name:'AI 整理学习计划',exact:true}).waitFor({timeout:120000});
  let view=(await get('/projects/'+created.project_id)).value;assert(view.sources.length>0);report.initial_state=view.page_state;
  const started=Date.now();await page.getByRole('button',{name:'AI 整理学习计划',exact:true}).click();view=await waitProject(created.project_id,['plan_review']);
  report.route_seconds=(Date.now()-started)/1000;report.node_titles=view.nodes.map(n=>n.title);assert(view.nodes.length>0);
  await fs.writeFile(path.join(out,'route.json'),JSON.stringify(view,null,2));await page.reload({waitUntil:'domcontentloaded'});await page.getByText('预览生长路线',{exact:true}).waitFor();await shot('real-route');
  const confirmed=await post('/projects/'+created.project_id+'/resume',{request_id:crypto.randomUUID(),action:'confirm_plan',pending_input_id:view.pending_input_id,draft_revision:view.draft_revision});
  assert.equal(confirmed.status,200,JSON.stringify(confirmed.value));
  const begun=await post('/projects/'+created.project_id+'/begin',{request_id:crypto.randomUUID()});assert([200,202].includes(begun.status),JSON.stringify(begun.value));
  view=await waitProject(created.project_id,['learning']);
  assert(view.tutor?.citations?.length>0,'Teaching must cite actual source chunks');
  await fs.writeFile(path.join(out,'teaching.json'),JSON.stringify(view,null,2));report.teaching_state=view.page_state;
  await page.reload({waitUntil:'commit'});await page.getByRole('button',{name:/· v1/}).first().waitFor({timeout:120000});await shot('real-teaching');
  const second=await browser.newContext(),other=await second.newPage();await other.goto(origin+'/',{waitUntil:'domcontentloaded'});
  const denied=await other.evaluate(async({pid,aid})=>({project:(await fetch('/projects/'+pid)).status,asset:(await fetch('/training/api/materials/'+aid)).status}),{pid:created.project_id,aid:asset.id});assert.deepEqual(denied,{project:404,asset:404});report.other_guest=denied;await second.close();
  await fs.writeFile(path.join(out,'storage-state.json'),JSON.stringify(await ctx.storageState()));
  assert.deepEqual(report.errors,[]);report.passed=true;
 }catch(e){report.passed=false;report.failure=e.stack;await shot('failure').catch(()=>{});throw e;}
 finally{await fs.writeFile(path.join(out,'storage-state.json'),JSON.stringify(await ctx.storageState()));await fs.writeFile(path.join(out,'result.json'),JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
