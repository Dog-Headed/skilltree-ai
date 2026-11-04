'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const node = (tag, text, cls) => { const e = document.createElement(tag); if (text) e.textContent = text; if (cls) e.className = cls; return e; };
  const link = (text, href, cls) => {const e=node('a',text,cls);e.href=href;return e;};
  let session;
  window.addEventListener('storage', e => { if (e.key === 'skilltree.auth.changed') location.reload(); });
  window.addEventListener('pageshow', e => { if (e.persisted) location.reload(); });
  async function get(url) { const r=await fetch(url,{cache:'no-store'}); if(r.status===401){location.replace('/login');throw new Error('请登录。');} const v=await r.json();if(!r.ok)throw new Error(v.error?.message||'读取失败，请刷新重试。');return v; }
  function hero(label,title,description) {const h=node('section',null,'hero'),copy=node('div');copy.append(node('span',label,'badge'),node('h1',title),node('p',description));const mark=node('div','✳','hero-mark');mark.setAttribute('aria-hidden','true');h.append(copy,mark);$('content').append(h);}
  function card(number,title,text,action,href,featured=false){const e=link('',href,'card'+(featured?' featured':''));e.append(node('span',number,'card-number'),node('h3',title),node('p',text),node('span',action+' →','action'));return e;}
  function empty(title,text){const e=node('section',null,'empty');e.append(node('h2',title),node('p',text),link('返回首页','/','button secondary'));$('content').append(e);}
  function heading(title,subtitle){const e=node('div',null,'section-heading');e.append(node('h2',title),node('small',subtitle));$('content').append(e);}
  async function render(){
    session=await get('/session');const m=session.training,admin=m.role==='admin',path=location.pathname;
    $('unit-name').textContent=m.unit_name;$('identity').textContent=m.display_name+' · '+(admin?'管理员':'员工');document.title=(admin?'培训管理':'员工学习')+' · SkillTree';
    const nav=admin?[['培训管理首页','/training/admin'],['培训资料','/training/admin/materials'],['课程与发布','/training/admin/courses'],['培训下发','/training/admin/tasks'],['学习看板','/training/admin/dashboard']]:[['学习首页','/training/home'],['自由学习','/learn'],['上传资料学习','/training/materials'],['我的培训任务','/training/tasks']];
    for(const [label,href] of nav){const a=link(label,href,'nav-link'+(path===href?' active':''));if(path===href)a.setAttribute('aria-current','page');$('navigation').append(a);}
    $('content').replaceChildren(node('p','SKILLTREE / LEARNING AT WORK','eyebrow'));
    if(path==='/training/admin'){
      const data=await get('/training/api/admin/overview');hero('培训管理空间','把一份知识，变成共同的成长。','从资料到课程，从任务到学习结果。在这里组织单位培训，让每位员工沿着自己的进度前行。');
      const cards=node('div',null,'cards');cards.append(card('01 / MATERIALS','培训资料','集中准备培训资料，为后续生成课程保留可靠依据。','查看资料入口','/training/admin/materials',true),card('02 / COURSES','课程与下发','确认知识树，再将同一课程分配给多位员工独立学习。','查看课程入口','/training/admin/courses'),card('03 / PROGRESS','学习看板','查看培训任务范围内的真实学习结果与待补弱目标。','查看看板入口','/training/admin/dashboard'));$('content').append(cards);
      heading('单位成员','已预置的真实登录身份');const members=node('div',null,'members');for(const member of data.members){const e=node('div',null,'member');e.append(node('strong',member.display_name),node('small',member.role==='admin'?'培训管理员':'员工'),node('small',member.account));members.append(e);}$('content').append(members);
      heading('培训任务','来自当前单位的实际记录');empty(data.tasks.length?'培训任务':'还没有培训任务',data.tasks.length?'任务学习入口将在后续阶段开放。':'课程发布与培训下发尚未开放。当前没有示例课程、成绩或统计。');
    }else if(path==='/training/home'){
      hero('员工学习空间',m.display_name+'，今天想学些什么？','从自己的目标出发，或跟随单位的培训安排。每个人都有独立的学习记录，积累的能力会一直保留。');
      const cards=node('div',null,'cards');cards.append(card('01 / EXPLORE','自由学习','告诉 AI 你想学什么、已有怎样的基础，规划属于自己的知识树。','开始自由学习','/learn',true),card('02 / MATERIALS','上传资料学习','围绕手边的制度、岗位手册或工作资料，建立自己的学习路径。','查看资料入口','/training/materials'),card('03 / TRAINING','我的培训任务','在这里领取单位安排的课程，按照自己的进度学习与测评。','查看我的任务','/training/tasks'));$('content').append(cards);
      heading('属于你的学习','个人课程与单位培训分别记录');$('content').append(node('p','自由学习已可使用。资料上传入口和培训任务将在后续阶段接通；现在可以先进入学习花园，创建或继续自己的课程。','notice'));
    }else if(path==='/training/tasks'){
      const data=await get('/training/api/my-tasks');hero('单位安排','我的培训任务','这里只显示分配给当前账号的单位培训；个人自由学习记录保存在学习花园。');empty(data.tasks.length?'任务学习入口尚未开放':'暂时没有分配给你的培训',data.tasks.length?'任务已记录，领取与学习功能将在后续阶段接通。':'管理员下发功能尚未开放。收到培训后，这里会显示真实任务和截止时间。');
    }else{
      const details={
        '/training/materials':['私人资料学习','上传资料学习','办公文件上传、解析预览与来源定位将在 Day 2 接通。当前尚不能在此导入文件。'],
        '/training/admin/materials':['单位培训资料','准备培训的可靠依据','单位资料上传与解析预览将在 Day 2 接通。当前没有已上传的培训资料。'],
        '/training/admin/courses':['课程与发布','一份课程，多人独立学习','课程预览、版本确认和发布将在 Day 3 接通。当前没有已发布课程。'],
        '/training/admin/tasks':['培训下发','把课程送到需要的人手中','选择员工和下发培训将在 Day 3 接通。当前尚不能创建或分配任务。'],
        '/training/admin/dashboard':['学习看板','让成长有迹可循','培训进度看板将在 Day 4 接通。当前没有培训学习事实，不展示成绩或统计。']
      };const d=details[path];hero(d[0],d[1],d[2]);empty('功能建设中',d[2]);
      if(!admin)$('content').append(link('先去自由学习 →','/learn','button'));
    }
  }
  $('logout').addEventListener('click',async()=>{try{const r=await fetch('/auth/logout',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session.csrf_token},body:'{}'});if(!r.ok&&r.status!==401)throw new Error('退出未完成，请刷新重试。');try{const prefix='skilltree.v3.'+encodeURIComponent(session.account)+'.';for(const key of Object.keys(localStorage))if(key.startsWith(prefix))localStorage.removeItem(key);localStorage.setItem('skilltree.auth.changed',String(Date.now()));}catch{}location.replace('/login');}catch(e){$('content').prepend(node('p',e.message,'error'));}});
  render().catch(e=>{$('content').replaceChildren(node('p',e.message,'error'),link('重新读取',location.pathname,'button secondary'));});
})();
