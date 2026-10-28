const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),{randomUUID}=require('node:crypto');
(async()=>{
 const [baseURL,size,evidence]=process.argv.slice(2),width=Number(size);
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try {
  const context=await browser.newContext({baseURL,viewport:{width,height:960}}),page=await context.newPage();
  page.setDefaultTimeout(12000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
  async function post(path,data){const r=await context.request.post(path,{data});assert(r.ok());return r.json();}
  let view=await post('/projects',{request_id:randomUUID(),intent:{goal:'Synthetic replacement modal',prior_knowledge:'synthetic'}});
  const pid=view.project_id,base='/projects/'+pid;
  async function act(action){view=await post(base+'/resume',{request_id:randomUUID(),pending_input_id:view.pending_input_id,draft_revision:view.draft_revision,action});}
  await act('confirm_profile');await act('confirm_plan');view=await post(base+'/begin',{request_id:randomUUID()});await act('start_quiz');
  assert.equal(view.page_state,'quiz');const quiz=view;
  const failed={...view,page_state:'error',error_type:'ModelOutputValidationError',error_code:'model_task_exhausted',failed_task_kind:'quiz',
   allowed_actions:['return_to_teaching','replace_assessment','rest'],notice:'Synthetic failed quiz'};
  let writes=0,release,settled=false;
  await page.route('**'+base,route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(settled?quiz:failed)}));
  await page.route('**'+base+'/resume',async route=>{
   const data=route.request().postDataJSON();assert.equal(data.action,'replace_assessment');assert.equal(data.assessment_id,failed.assessment_id);writes++;
   await new Promise(resolve=>{release=resolve;});settled=true;
   await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(quiz)});
  });
  await page.goto('/#/p/'+pid+'/learn');const dialog=page.getByRole('dialog');
  for(const cancel of ['关闭弹窗','取消','escape']){
   await page.getByRole('button',{name:'申请换题',exact:true}).click();await dialog.waitFor();
   if(cancel==='escape')await page.keyboard.press('Escape');else await dialog.getByRole('button',{name:cancel,exact:true}).click();
   await dialog.waitFor({state:'hidden'});assert.equal(writes,0);
  }
  await page.getByRole('button',{name:'申请换题',exact:true}).click();
  await dialog.getByRole('button',{name:'确认继续',exact:true}).click();
  await dialog.waitFor({state:'hidden',timeout:2000});
  await page.locator('body[aria-busy="true"]').waitFor();assert.equal(writes,1);
  await page.getByRole('button',{name:width===390?'打开学习记录':'我的花园',exact:true}).click();
  // Dismissing a read-only dialog while an operation runs must not cancel or resend it.
  for(const cancel of ['关闭弹窗','escape']){
   await page.getByRole('button',{name:'能力范围',exact:true}).click();await dialog.waitFor();
   if(cancel==='escape')await page.keyboard.press('Escape');else await dialog.getByRole('button',{name:cancel,exact:true}).click();
   await dialog.waitFor({state:'hidden'});assert.equal(writes,1);
  }
  assert.match(await page.locator('.status-card').innerText(),/未通过格式或课程规则检查/);
  assert.doesNotMatch(await page.locator('.status-card').innerText(),/响应太慢或网络不稳定/);
  await page.screenshot({path:evidence+'/pending.png',fullPage:true});
  release();await page.locator('body[aria-busy="false"]').waitFor();await page.locator('#quiz-form').waitFor();
  assert.equal(writes,1);assert.deepEqual(errors,[]);
  await page.screenshot({path:evidence+'/ready.png',fullPage:true});
  const report={passed:true,width,writes,errors,scope:'Synthetic HTTP result; actual browser, modal, and request lifecycle'};
  await fs.writeFile(evidence+'/result.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));await context.close();
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
