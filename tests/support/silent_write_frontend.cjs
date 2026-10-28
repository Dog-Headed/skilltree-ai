const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs/promises'),{randomUUID}=require('node:crypto');
(async()=>{
 const [baseURL,size,evidence]=process.argv.slice(2),width=Number(size),browser=await chromium.launch({headless:true,channel:'msedge'});
 try {
  const context=await browser.newContext({baseURL,viewport:{width,height:960}}),page=await context.newPage();
  const post=async(path,data)=>{const r=await context.request.post(path,{data});assert(r.ok());return r.json();};
  const initial=await post('/projects',{request_id:randomUUID(),intent:{goal:'Synthetic silent response recovery',prior_knowledge:'synthetic'}}),pid=initial.project_id;
  const complete=await post('/projects/'+pid+'/resume',{request_id:randomUUID(),pending_input_id:initial.pending_input_id,draft_revision:initial.draft_revision,action:'confirm_profile'});
  assert.equal(complete.page_state,'plan_review');let submitted=false,writes=0,release,seenResolve;const seen=new Promise(r=>seenResolve=r);const errors=[];
  page.on('pageerror',e=>errors.push(e.message));await page.clock.install();
  await page.route('**/projects/'+pid,route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(submitted?complete:initial)}));
  await page.route('**/projects/'+pid+'/resume',async route=>{writes++;submitted=true;seenResolve();await new Promise(r=>release=r);await route.abort().catch(()=>{});});
  await page.goto('/#/p/'+pid+'/learn');await page.getByRole('button',{name:'AI 整理学习计划',exact:true}).click();await seen;
  await page.locator('body[aria-busy="true"]').waitFor();await page.clock.fastForward(61000);
  await page.getByRole('button',{name:'确认这条路线',exact:true}).waitFor();await page.locator('body[aria-busy="false"]').waitFor();
  assert.equal(writes,1);assert.deepEqual(errors,[]);release();
  await page.screenshot({path:evidence+'/recovered.png',fullPage:true});
  const report={passed:true,width,writes,read_only_recovery:true,errors};await fs.writeFile(evidence+'/result.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));await context.close();
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
