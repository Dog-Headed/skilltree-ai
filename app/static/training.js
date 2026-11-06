'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const node = (tag, text, cls) => { const e = document.createElement(tag); if (text) e.textContent = text; if (cls) e.className = cls; return e; };
  const displayName = member => member.role === 'admin' && member.display_name === '\u57f9\u8bad管理员' ? '学习管理员' : member.display_name;
  const link = (text, href, cls) => {const e=node('a',text,cls);e.href=href;return e;};
  let session;
  window.addEventListener('storage', e => { if (e.key === 'skilltree.auth.changed') location.reload(); });
  window.addEventListener('pageshow', e => { if (e.persisted) location.reload(); });
  async function get(url) { const r=await fetch(url,{cache:'no-store'}); if(r.status===401){location.replace('/login');throw new Error('请登录。');} const v=await r.json();if(!r.ok)throw new Error(v.error?.message||'读取失败，请刷新重试。');return v; }
  function hero(label,title,description) {const h=node('section',null,'hero'),copy=node('div');copy.append(node('span',label,'badge'),node('h1',title),node('p',description));const mark=node('div',null,'hero-mark');mark.setAttribute('aria-hidden','true');mark.innerHTML='<svg viewBox="0 0 22 26" aria-hidden="true"><path d="M11 25 C11 18 10 13 11 6" fill="none" stroke="var(--stem)" stroke-width="2" stroke-linecap="round"/><path d="M11 12 C 15 11 18 7 18 2 C 13 2 11 6 11 12Z" fill="var(--leaf-deep)"/><path d="M11 16 C 7 15.5 4 12.5 4 8.5 C 8 8.5 10.5 11.5 11 16Z" fill="var(--leaf-soft)" stroke="var(--leaf)" stroke-width="1.2"/></svg>';h.append(copy,mark);$('content').append(h);}
  function card(number,title,text,action,href,featured=false,icon=''){const e=link('',href,'card'+(featured?' featured':''));if(icon){const img=node('img',null,'card-icon');img.src=icon;img.alt='';e.append(img);}e.append(node('span',number,'card-number'),node('h3',title),node('p',text),node('span',action+' →','action'));return e;}
  function empty(title,text){const e=node('section',null,'empty');e.append(node('h2',title),node('p',text),link('返回首页','/','button secondary'));$('content').append(e);}
  function heading(title,subtitle){const e=node('div',null,'section-heading');e.append(node('h2',title),node('small',subtitle));$('content').append(e);}
  async function post(url,body){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session.csrf_token},body:JSON.stringify(body)});const v=await r.json();if(!r.ok)throw new Error(v.error?.message||v.error||'操作失败，请刷新资料列表核对。');return v;}
  async function materialsPage(unit){
    const api=unit?'/training/api/admin/materials':'/training/api/materials';
    hero(unit?'单位资料库':'个人资料库',unit?'准备可靠的学习资料':'从自己的资料开始学习',unit?'上传原件，核对解析正文与来源位置，再用这份资料准备课程。':'上传后先核对原文，再建立属于自己的学习路线。个人资料仅当前身份可见。');
    $('content').append(node('p','支持文字 PDF、DOCX、XLSX、PPTX、UTF-8 TXT / Markdown，办公文件不超过 8 MiB，TXT / Markdown 不超过 128 KiB。办公文件正文最多 12,000 字符；PDF 最多 10 页，PPTX 最多 15 张。超过该上限的 PDF、PPTX、DOCX 会自动拆成多个章节，不提高上限。能可靠识别标题时按标题拆；识别不了时按页或长度分段，并在章节里写明，不会把按页结果称作按标题。扫描件、旧版 Office、宏和需打开密码的文件暂不支持。Excel 公式仅展示，不执行。','notice'));
    const form=node('form',null,'material-form'),file=node('input'),title=node('input'),submit=node('button','上传并解析','button'),status=node('p','请选择一份资料。','material-status');
    file.type='file';file.name='file';file.required=true;file.accept='.pdf,.docx,.xlsx,.pptx,.txt,.md,.markdown';file.setAttribute('aria-label','选择学习资料');title.name='title';title.maxLength=256;title.required=true;title.placeholder='资料标题';title.setAttribute('aria-label','资料标题');submit.type='submit';status.setAttribute('role','status');
    file.addEventListener('change',()=>{title.value=file.files[0]?.name.replace(/\.[^.]+$/,'')||'';});form.append(file,title,submit,status);$('content').append(form);
    const library=node('section',null,'material-library'),preview=node('section',null,'material-preview');$('content').append(library,preview);
    async function show(id){
      const data=await get(api+'/'+id);const stateLabel=data.auto_split?'已自动拆分为 '+(data.chapter_count||0)+' 个章节':({ready:'解析完成',failed:'解析失败',processing:'正在解析'}[data.status]);preview.replaceChildren(node('h2',data.title),node('p',data.filename+' · '+stateLabel));
      if(data.status!=='ready'){preview.append(node('p',data.error||'解析尚未完成，请稍后刷新。','error'));return;}
      if(data.auto_split){
        preview.append(node('p','该文件已自动拆分为 '+(data.chapter_count||0)+' 个章节。请分别核对各章，再准备课程。','notice'));
        for(const chapter of data.chapters||[]){const open=node('button',chapter.title,'button secondary');open.type='button';open.addEventListener('click',()=>show(chapter.id).catch(e=>{status.textContent=e.message;}));preview.append(open);}
        preview.append(link('下载原件',api+'/'+id+'/original','button secondary'));
        return;
      }
      const parsed=data.parsed;preview.append(node('p',parsed.format.toUpperCase()+' · 正文 '+parsed.content.length+' 字符','dim'),link('下载原件',api+'/'+id+'/original','button secondary'));
      for(const warning of parsed.warnings)preview.append(node('p',warning,'notice'));
      const details=node('details'),summary=node('summary','解析全文与来源位置');details.append(summary,node('pre',parsed.content,'material-text'));
      for(const block of parsed.blocks){details.append(node('h3',block.label+' · 正文行 '+block.line_start+'–'+block.line_end));if(block.rows){const table=node('table');for(const [index,row] of block.rows.entries()){const tr=node('tr');for(const value of row)tr.append(node(index===0?'th':'td',value));table.append(tr);}details.append(table);}}
      preview.append(details);
      const start=node('form',null,'material-form'),goal=node('textarea'),prior=node('input'),button=node('button','用这份资料准备课程','button'),message=node('p');goal.name='goal';goal.required=true;goal.maxLength=4000;goal.value='依据《'+data.title+'》学习其中的核心规则、适用条件和操作步骤';goal.setAttribute('aria-label','学习目标');prior.name='prior';prior.placeholder='已有基础（可选）';prior.maxLength=4000;prior.setAttribute('aria-label','已有基础');button.type='submit';start.append(node('h3','你的学习目标'),goal,prior,button,message);if(unit)start.append(node('p','Planner 生成并确认草稿后，回到「课程与发布」发布这一固定版本。手填节点不能代替这份草稿。','notice'));preview.append(start);
      start.addEventListener('submit',async event=>{event.preventDefault();button.disabled=true;message.textContent='正在创建课程并导入已核对资料…';try{const created=await post('/projects',{request_id:crypto.randomUUID(),intent:{goal:goal.value.trim(),prior_knowledge:prior.value.trim()}});await post(api+'/'+id+'/attach',{project_id:created.project_id,request_id:crypto.randomUUID()});location.assign('/learn#/p/'+encodeURIComponent(created.project_id)+'/learn');}catch(e){message.textContent=e.message;button.disabled=false;}});
      preview.scrollIntoView({block:'start',behavior:'smooth'});
    }
    async function refresh(){const data=await get(api);library.replaceChildren(node('h2',unit?'已上传单位资料':'我的资料'));const visible=data.materials.filter(material=>material.kind!=='chapter');if(!visible.length)library.append(node('p','还没有上传资料。上传成功后，可在这里核对正文和来源位置。'));for(const material of visible){const row=node('div',null,'material-row'),label=material.auto_split?material.title+' · 已自动拆分为 '+material.chapter_count+' 个章节':material.title+' · '+({ready:'解析完成',failed:'解析失败',processing:'正在解析'}[material.status]);const open=node('button',label,'button secondary');open.type='button';open.addEventListener('click',()=>show(material.id).catch(e=>{status.textContent=e.message;}));row.append(open,node('small',material.filename));library.append(row);}}
    form.addEventListener('submit',async event=>{event.preventDefault();const selected=file.files[0];if(!selected)return;submit.disabled=true;status.textContent='正在上传并解析原件，请等待…';try{if(selected.size>(/\.(txt|md|markdown)$/i.test(selected.name)?131072:8388608))throw new Error('文件超过大小限制，请拆分后上传。');const bytes=new Uint8Array(await selected.arrayBuffer());let binary='';for(const byte of bytes)binary+=String.fromCharCode(byte);const result=await post(api,{request_id:crypto.randomUUID(),filename:selected.name,title:title.value.trim(),data_base64:btoa(binary)});status.textContent=result.auto_split?('该文件已自动拆分为 '+result.chapter_count+' 个章节。'):'解析完成，请核对正文和来源位置。';await refresh();await show(result.id);}catch(e){status.textContent=e.message;await refresh();}finally{submit.disabled=false;}});
    await refresh();
  }
  async function membersPanel(data){
    heading('单位成员','按完整邮箱或账号 ID 查找已注册用户，加入本单位为员工');
    const members=node('div',null,'members');
    function paint(){members.replaceChildren();for(const member of data.members){const e=node('div',null,'member');e.append(node('strong',displayName(member)),node('small',member.role==='admin'?'学习管理员':'员工'),node('small',member.account));if(member.role==='employee'){const rm=node('button','移出单位','button secondary');rm.type='button';rm.addEventListener('click',async()=>{if(!confirm('仅撤销单位成员身份，个人学习记录会保留。确认移出？'))return;try{await post('/training/api/admin/members/remove',{account:member.account});data.members=data.members.filter(x=>x.account!==member.account);paint();status.textContent='已移出 '+member.account;}catch(err){status.textContent=err.message;}});e.append(rm);}members.append(e);}}
    const form=node('form',null,'material-form'),input=node('input'),submit=node('button','查找并加入','button'),status=node('p','输入完整账号邮箱或稳定账号 ID。不会列出全站目录，也不会展示对方私人课程。','material-status');
    input.name='login';input.required=true;input.maxLength=254;input.placeholder='user@example.test';input.setAttribute('aria-label','账号邮箱或 ID');submit.type='submit';status.setAttribute('role','status');
    form.append(input,submit,status);$('content').append(form,members);paint();
    form.addEventListener('submit',async event=>{event.preventDefault();submit.disabled=true;status.textContent='正在查找…';try{const q=input.value.trim();const found=await get('/training/api/admin/members/lookup?q='+encodeURIComponent(q));if(found.in_other_unit){status.textContent='该账号已属于其他单位，本版不能自动转移。';return;}if(found.in_this_unit){status.textContent='该账号已在本单位（'+found.role+'）。';return;}const added=await post('/training/api/admin/members',{login:found.login});if(!data.members.some(x=>x.account===added.account))data.members.push({account:added.account,display_name:added.display_name,role:added.role});data.members.sort((a,b)=>a.role===b.role?a.account.localeCompare(b.account):(a.role==='admin'?-1:1));paint();status.textContent=(added.created?'已加入 ':'已在本单位 ')+added.login;input.value='';}catch(err){status.textContent=err.message;}finally{submit.disabled=false;}});
  }
  function courseOptionLabel(course){return course.title+' · '+course.course_id+' · v'+course.version;}
  async function coursesPage(){
    const data=await get('/training/api/admin/overview');
    const drafts=await get('/training/api/admin/course-drafts');
    hero('课程与发布','确认草稿，再冻结这一版','发布引用 Planner 已生成并保存在服务端的草稿 revision。手填的占位节点不会成为课程。');
    const publishable=(drafts.drafts||[]).filter(item=>item.publishable);
    if(!publishable.length){
      const box=node('section',null,'empty');
      box.append(node('h2','还没有可发布的草稿'),node('p','先在学习资料页使用「用这份资料准备课程」。Planner 生成并确认目标、依赖和评价规则后，草稿会出现在这里。'),link('去准备资料','/training/admin/materials','button secondary'));
      $('content').append(box);
    }
    const form=node('form',null,'material-form'),draftSelect=node('select'),title=node('input'),revise=node('select'),requiredBox=node('div'),preview=node('div'),submit=node('button','确认发布这一版本','button'),status=node('p','发布后不可原地改写。新主题请作为新课程发布；只有修订同一门课时才沿用课程身份。','material-status');
    draftSelect.required=true;draftSelect.setAttribute('aria-label','课程草稿');draftSelect.append(node('option','选择已确认的草稿'));
    for(const draft of publishable){const option=node('option',draft.title+' · revision '+draft.draft_revision);option.value=draft.project_id;draftSelect.append(option);}
    title.required=true;title.maxLength=200;title.placeholder='课程标题';title.setAttribute('aria-label','课程标题');
    revise.setAttribute('aria-label','课程身份');const freshCourse=node('option','发布为新课程');freshCourse.value='';revise.append(freshCourse);
    const seen=new Map();
    for(const course of data.courses){const prev=seen.get(course.course_id);if(!prev||course.version>prev.version)seen.set(course.course_id,course);}
    for(const course of seen.values()){const option=node('option','修订：'+courseOptionLabel(course));option.value=course.course_id;revise.append(option);}
    submit.type='submit';status.setAttribute('role','status');
    form.append(draftSelect,title,revise,requiredBox,preview,submit,status);
    if(publishable.length)$('content').append(form);
    function paint(draft){
      requiredBox.replaceChildren(node('p','必学节点（可取消不计入进度的节点；其前置仍会保留在学习计划中）'));
      preview.replaceChildren();
      if(!draft){title.value='';return;}
      title.value=draft.title||'';
      const open=link('在学习引擎中查看或调整此草稿','/learn#/p/'+encodeURIComponent(draft.project_id)+'/learn','button secondary');
      preview.append(open);
      const rules=new Map((draft.policy&&draft.policy.objective_rules||[]).map(rule=>[rule.objective_id,rule]));
      if(draft.policy)preview.append(node('p','总分通过阈值 '+draft.policy.total_pass_threshold,'dim'));
      for(const item of draft.nodes||[]){
        const label=node('label',null,'remember'),box=node('input');
        box.type='checkbox';box.checked=true;box.value=item.node_id;
        label.append(box,document.createTextNode(' 必学 · '+item.title+' · 前置 '+(item.prerequisite_ids&&item.prerequisite_ids.length?item.prerequisite_ids.join('、'):'无')));
        requiredBox.append(label);
        const block=node('div',null,'member');
        block.append(node('strong',item.node_id+' · '+item.title));
        for(const objective of item.objectives||[]){
          const rule=rules.get(objective.objective_id);
          block.append(node('small',objective.observable_outcome));
          block.append(node('small','目标 '+objective.objective_id+' · 能力 '+(objective.required_capability_ids||[]).join(',')+(objective.criterion_ids&&objective.criterion_ids.length?' · 标准 '+objective.criterion_ids.join(','):'')+(rule?' · 阈值 '+rule.pass_threshold:'')));
        }
        preview.append(block);
      }
    }
    draftSelect.addEventListener('change',()=>{paint(publishable.find(item=>item.project_id===draftSelect.value)||null);});
    form.addEventListener('submit',async event=>{
      event.preventDefault();submit.disabled=true;status.textContent='正在按服务端草稿发布…';
      try{
        const draft=publishable.find(item=>item.project_id===draftSelect.value);
        if(!draft)throw new Error('请选择一份已确认的草稿。');
        const required=[...requiredBox.querySelectorAll('input[type=checkbox]:checked')].map(box=>box.value);
        if(!required.length)throw new Error('请至少选择一个必学节点。');
        const payload={request_id:crypto.randomUUID(),draft_project_id:draft.project_id,draft_revision:draft.draft_revision,title:title.value.trim(),required_nodes:required,material_version_ids:draft.material_version_ids};
        if(revise.value)payload.course_id=revise.value;
        const result=await post('/training/api/admin/courses/publish',payload);
        status.textContent='已发布 '+result.title+' · '+result.course_id+' · v'+result.version+'（'+result.id+'）';
        location.reload();
      }catch(error){status.textContent=error.message;submit.disabled=false;}
    });
    for(const draft of drafts.drafts||[]){
      if(draft.publishable)continue;
      const row=node('div',null,'member');
      row.append(node('strong',draft.title),node('small','revision '+(draft.draft_revision||'')),node('small',draft.reason||'暂不能发布'),link('打开草稿','/learn#/p/'+encodeURIComponent(draft.project_id)+'/learn','button secondary'));
      $('content').append(row);
    }
    heading('已发布课程','每门课有独立身份；修订才会增加版本');
    if(!data.courses.length)$('content').append(node('p','还没有已发布课程。'));
    else{const list=node('div',null,'members');for(const course of data.courses){const item=node('div',null,'member');item.append(node('strong',course.title),node('small',course.course_id),node('small','v'+course.version),node('small',course.id),node('small',course.published_at||''));list.append(item);}$('content').append(list);}
  }
  async function render(){
    session=await get('/session');const m=session.training,admin=m.role==='admin',guest=m.role==='guest',personal=m.role==='personal',path=location.pathname;
    const unaffiliated=guest||personal;
    $('unit-name').textContent=m.unit_name;$('identity').textContent=displayName(m)+' · '+(admin?'管理员':guest?'游客':personal?'个人账号':'员工');document.title=(admin?'学习管理':unaffiliated?'自主学习':'员工学习')+' · SkillTree';
    $('logout').hidden=guest;if(unaffiliated){if(guest)$('switch-account').textContent='登录 / 注册';else $('switch-account').textContent='切换账号';document.querySelector('.unit-label').textContent='个人学习空间';document.querySelector('footer').firstChild.textContent='SkillTree · 让好奇长成能力 ';}
    const nav=admin?[['学习管理首页','/training/admin'],['成员管理','/training/admin/members'],['学习资料','/training/admin/materials'],['课程与发布','/training/admin/courses'],['任务下发','/training/admin/tasks'],['学习看板','/training/admin/dashboard']]:[['学习首页','/learn#/garden'],['自由学习','/learn'],['上传资料学习','/training/materials'],['我的学习任务','/training/tasks']];
    for(const [label,href] of nav.filter(([,href])=>!unaffiliated||href!=='/training/tasks')){const a=link(label,href,'nav-link'+(path===href?' active':''));if(path===href)a.setAttribute('aria-current','page');$('navigation').append(a);if(path===href)a.scrollIntoView({block:'nearest',inline:'nearest'});}
    $('content').replaceChildren(node('p','SKILLTREE / LEARN AND GROW','eyebrow'));
    if(path==='/training/admin'||path==='/training/admin/members'){
      const data=await get('/training/api/admin/overview');
      if(path==='/training/admin'){
        hero('学习管理空间','把一份知识，变成共同的成长。','从资料到课程，从任务到学习结果。在这里组织共同学习，让每位员工沿着自己的进度前行。');
        const cards=node('div',null,'cards');cards.append(card('01 / MATERIALS','学习资料','集中准备学习资料，为后续生成课程保留可靠依据。','查看资料入口','/training/admin/materials',true),card('02 / MEMBERS','成员管理','按邮箱查找已注册个人账号，加入本单位后才能接收任务。','管理成员','/training/admin/members'),card('03 / COURSES','课程与下发','确认知识树，再将同一课程分配给多位员工独立学习。','查看课程入口','/training/admin/courses'),card('04 / PROGRESS','学习看板','查看学习任务范围内的真实学习结果与待补弱目标。','查看看板入口','/training/admin/dashboard'));$('content').append(cards);
        heading('单位成员','当前成员一览');const members=node('div',null,'members');for(const member of data.members){const e=node('div',null,'member');e.append(node('strong',displayName(member)),node('small',member.role==='admin'?'学习管理员':'员工'),node('small',member.account));members.append(e);}$('content').append(members);$('content').append(link('打开成员管理 →','/training/admin/members','button secondary'));
        heading('学习任务','来自当前单位的实际记录');if(!data.tasks.length)empty('还没有学习任务','发布课程并下发后，这里会显示任务。');else{const list=node('div',null,'members');for(const task of data.tasks){const e=node('div',null,'member');e.append(node('strong',task.title),node('small',task.course_version_id),node('small',task.due_at||'无截止时间'),node('small',task.id));list.append(e);}$('content').append(list);$('content').append(link('去任务下发 →','/training/admin/tasks','button secondary'));}
      }else{
        hero('成员管理','选择账号加入本单位','只添加已注册的个人账号为员工。不会转移私人课程，也不能在此提升管理员。');
        await membersPanel(data);
      }
    }else if(path==='/training/home'){
      hero(unaffiliated?'个人学习空间':'员工学习空间',unaffiliated?'今天想学些什么？':displayName(m)+'，今天想学些什么？',guest?'从好奇出发，也可以带上自己的资料。无需登录，就能规划知识树、学习与测评。':personal?'你已是个人账号，可以自由学习和上传资料；加入单位后才会看到单位任务。':'从自己的目标出发，或跟随单位安排的学习任务。每个人都有独立的学习记录，积累的能力会一直保留。');
      const cards=node('div',null,'cards');cards.append(card('01 / EXPLORE','自由学习','告诉 AI 你想学什么、已有怎样的基础，规划属于自己的知识树。','开始自由学习','/learn',true,'/assets/training-icon-free-learn.png'),card('02 / MATERIALS','上传资料学习','围绕课程讲义、阅读笔记或自选资料，建立自己的学习路径。','查看资料入口','/training/materials',false,'/assets/training-icon-upload.png'));if(!unaffiliated)cards.append(card('03 / ASSIGNED','我的学习任务','在这里领取单位安排的课程，按照自己的进度学习与测评。','查看我的任务','/training/tasks',false,'/assets/training-icon-tasks.png'));$('content').append(cards);
      heading('属于你的学习',unaffiliated?'你的目标，你的节奏':'自主学习与学习任务分别记录');
      if(guest)$('content').append(node('p','游客可以用通用知识或自己的办公资料学习。进度与当前浏览器身份关联，请保留浏览器数据；注册个人账号或登录已有账号后，课程和个人资料会保留。','notice'),link('注册并保留进度 →','/login?register=1','button'));
      else if(personal)$('content').append(node('p','个人账号可以自由学习和上传资料。只有管理员把你加入单位后，才会出现单位任务入口。','notice'));
      else $('content').append(node('p','自由学习和办公资料学习已可使用。单位任务将在下发后显示。','notice'));
    }else if(path==='/training/materials'||path==='/training/admin/materials'){
      await materialsPage(path==='/training/admin/materials');
    }else if(path==='/training/admin/courses'){
      await coursesPage();
    }else if(path==='/training/admin/tasks'){
      const data=await get('/training/api/admin/overview');
      hero('任务下发','把课程送到需要的人手中','选择已发布课程和员工下发。每人独立学习，开始后不会复制其他人的进度。');
      const form=node('form',null,'material-form'),title=node('input'),course=node('select'),due=node('input'),people=node('div'),submit=node('button','下发任务','button'),status=node('p','只会创建员工任务行，不会复制别人的学习进度。','material-status');
      title.required=true;title.maxLength=200;title.placeholder='任务标题';title.setAttribute('aria-label','任务标题');
      course.required=true;course.setAttribute('aria-label','课程版本');course.append(node('option','选择课程版本'));
      for(const c of data.courses){const o=node('option',c.title+' · v'+c.version);o.value=c.id;course.append(o);}
      due.type='datetime-local';due.setAttribute('aria-label','截止时间');
      people.append(node('p','选择员工（可多选）'));
      const checks=[];for(const member of data.members.filter(m=>m.role==='employee')){const label=node('label',null,'remember'),box=node('input');box.type='checkbox';box.value=member.account;label.append(box,document.createTextNode(' '+displayName(member)+' · '+member.account));people.append(label);checks.push(box);}
      submit.type='submit';form.append(title,course,due,people,submit,status);$('content').append(form);
      form.addEventListener('submit',async event=>{event.preventDefault();submit.disabled=true;status.textContent='正在下发…';try{const accounts=checks.filter(c=>c.checked).map(c=>c.value);if(!accounts.length)throw new Error('请至少选择一名员工。');const payload={request_id:crypto.randomUUID(),course_version_id:course.value,title:title.value.trim(),accounts};if(due.value)payload.due_at=new Date(due.value).toISOString();const result=await post('/training/api/admin/tasks/assign',payload);status.textContent='已下发给 '+result.assignees.length+' 人';location.reload();}catch(e){status.textContent=e.message;submit.disabled=false;}});
      heading('已下发任务','本单位任务');
      if(!data.tasks.length)empty('还没有学习任务','发布课程后可在上方下发。');
      else{const list=node('div',null,'members');for(const task of data.tasks){const e=node('div',null,'member');e.append(node('strong',task.title),node('small',task.course_version_id),node('small',task.due_at||'无截止时间'),node('small',task.id));list.append(e);}$('content').append(list);}
    }else if(path==='/training/tasks'){
      const data=await get('/training/api/my-tasks');hero('单位安排','我的学习任务','这里只显示分配给当前账号的单位学习。开始后会按已发布课程初始化你自己的独立项目。');
      if(!data.tasks.length)empty('暂时没有分配给你的学习任务','管理员下发后，这里会显示真实任务和截止时间。');
      else{const list=node('div',null,'members');for(const task of data.tasks){const e=node('div',null,'member');const status=task.status==='completed'?'已完成':(task.project_id?'进行中':'未开始');const progress=task.progress?('必学 '+task.progress.required_passed+'/'+task.progress.required_total):'';e.append(node('strong',task.title),node('small',task.due_at||'无截止时间'),node('small',status+(progress?' · '+progress:'')),node('small',task.course_version_id));const go=node('button',task.project_id?'继续学习':'开始学习','button');go.type='button';go.addEventListener('click',async()=>{go.disabled=true;try{let projectId=task.project_id;if(!projectId){const started=await post('/training/api/my-tasks/'+encodeURIComponent(task.id)+'/start',{request_id:crypto.randomUUID()});projectId=started.project_id;}location.assign('/learn#/p/'+encodeURIComponent(projectId)+'/learn');}catch(err){go.disabled=false;alert(err.message);}});e.append(go);list.append(e);}$('content').append(list);}
    }else if(path==='/training/admin/dashboard'){
      const data=await get('/training/api/admin/dashboard');
      hero('学习看板','让成长有迹可循','进度只统计任务范围内已达标的必学节点，来自真实学习事实，不把打开页面或提交次数当成完成。');
      if(data.empty){empty('还没有可统计的学习任务','发布课程并下发给员工后，这里会显示下发、已开始与已完成人数。');}
      else{
        for(const task of data.tasks){
          const panel=node('section',null,'member');
          const counts=task.counts||{};
          panel.append(node('strong',task.title),
            node('small','下发 '+(counts.assigned||0)+' · 已开始 '+(counts.started||0)+' · 已完成 '+(counts.completed||0)+(task.overdue?' · 已逾期':'')),
            node('small',task.due_at||'无截止时间'));
          const open=node('button','查看员工明细','button secondary');open.type='button';
          open.addEventListener('click',async()=>{
            open.disabled=true;
            try{
              const board=await get('/training/api/admin/tasks/'+encodeURIComponent(task.id)+'/board');
              const box=node('div',null,'members');
              box.append(node('p','进度口径：已达标必学节点 / 课程全部必学节点。逾期单独标记，不覆盖学习状态。','notice'));
              if(!board.employees.length)box.append(node('p','此任务还没有指派员工。'));
              for(const emp of board.employees){
                const row=node('div',null,'member');
                const prog=emp.progress||{};
                const label=(emp.status==='completed'?'已完成':emp.status==='in_progress'?'进行中':'未开始')+(emp.overdue?' · 逾期':'');
                row.append(node('strong',emp.account),node('small',label),
                  node('small','必学 '+(prog.required_passed||0)+'/'+(prog.required_total||0)),
                  node('small',emp.updated_at||emp.started_at||'尚未开始'));
                if(emp.recent_assessment)row.append(node('small','最近测评：'+(emp.recent_assessment.passed?'通过':'未通过')+' · '+(emp.recent_assessment.effective_action||'')));
                if(emp.remediation_targets&&emp.remediation_targets.length)row.append(node('small','待补弱：'+emp.remediation_targets.join(', ')));
                box.append(row);
              }
              panel.append(box);open.remove();
            }catch(err){open.disabled=false;alert(err.message);}
          });
          panel.append(open);$('content').append(panel);
        }
      }
    }else{
      empty('页面不存在','请从导航重新进入。');
    }
  }
  $('logout').addEventListener('click',async()=>{try{const r=await fetch('/auth/logout',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session.csrf_token},body:'{}'});if(!r.ok&&r.status!==401)throw new Error('退出未完成，请刷新重试。');try{const prefix='skilltree.v3.'+encodeURIComponent(session.account)+'.';for(const key of Object.keys(localStorage))if(key.startsWith(prefix))localStorage.removeItem(key);localStorage.setItem('skilltree.auth.changed',String(Date.now()));}catch{}location.replace('/login');}catch(e){$('content').prepend(node('p',e.message,'error'));}});
  render().catch(e=>{$('content').replaceChildren(node('p',e.message,'error'),link('重新读取',location.pathname,'button secondary'));});
})();
