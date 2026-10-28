/* Botanical views over public project data. No model calls or inferred passes. */
'use strict';
window.SkillTreeGarden = function (ctx) {
  const {el, button, chip, list, nodesFor, currentName, state, allowed, command,
    selectProject, projectMenu, quizCard, recoveryCard,
    sourceCard, renderPlan, storage, actionLabels, markdown, citationButtons} = ctx;
  let selected = null;
  let screen = 'learn';
  let project = null;
  let routing = false;
  const statusNames = {passed: '已长成', current: '正在学', available: '可以学', locked: '尚未解锁'};
  const idOf = n => n.node_id || n.id;
  const statusOf = (n, view) => list(view.completed_node_ids).includes(idOf(n)) || n.passed ? 'passed' : n.status || (idOf(n) === view.current_node_id ? 'current' : 'locked');
  function svg(tag, attrs = {}, ...children) {
    const n = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [k, v] of Object.entries(attrs)) if (v != null) n.setAttribute(k, String(v));
    for (const child of children.flat()) if (child) n.append(child);
    return n;
  }
  function text(x, y, value, cls, anchor = 'start') {
    const n = svg('text', {x, y, class: cls, 'text-anchor': anchor}); n.textContent = value; return n;
  }
  function subject(view) {
    const s = [view?.profile?.subject_label, view?.profile?.topic, view?.profile?.goal].join(' ').toLowerCase();
    if (/python|编程|代码|javascript|程序/.test(s)) return 'code';
    if (/数学|方程|代数|math|物理|密度/.test(s)) return 'math';
    if (/英语|语言|english|日语|法语|语法/.test(s)) return 'lang';
    return 'general';
  }
  const artwork = window.SkillTreeBotanical;
  let growth = {grew: [], sprouts: [], replay: false};
  let growthTimer;
  let graphSerial = 0;
  const hash = s => {let h=2166136261;for(const c of s){h^=c.charCodeAt(0);h=Math.imul(h,16777619);}return h>>>0;};
  const jit = (id,salt,amp) => ((hash(id+salt)%2001)/1000-1)*amp;
  const f = v => Math.round(v*10)/10;
  function artNodes(markup) {
    // Markup comes exclusively from the original artwork's numeric geometry.
    const doc=new DOMParser().parseFromString('<svg xmlns="http://www.w3.org/2000/svg">'+markup+'</svg>','image/svg+xml');
    return [...doc.documentElement.children].map(n=>document.importNode(n,true));
  }
  function leaf(kind,status,count=2,size=34,animateVeins=false) {
    const k=Math.max(1,Math.min(5,count));
    const group=svg('g',{class:'plant-leaf node st-'+status});
    if(status==='locked' || status==='available') {
      group.append(...artNodes(artwork.bud(size,status==='available')));
      return group;
    }
    const sway=svg('g',{class:'sway'}),inner=svg('g',status==='current'?{transform:'scale(.8)'}:{});
    inner.append(...artNodes(artwork.leaf(kind,size,status,k,animateVeins?'a-vein':'')));
    sway.append(inner);group.append(sway);return group;
  }
  // Draw only direct dependencies: a prerequisite already implied through another
  // prerequisite stays listed on the specimen card but is not drawn twice.
  function directParents(nodes) {
    const byId=new Map(nodes.map(n=>[idOf(n),n])),memo=new Map();
    const ancestors=id=>{
      if(memo.has(id))return memo.get(id);
      const all=new Set();memo.set(id,all);
      for(const p of list(byId.get(id)?.prerequisite_ids))if(byId.has(p)&&p!==id){all.add(p);for(const a of ancestors(p))all.add(a);}
      return all;
    };
    return new Map(nodes.map(n=>{
      const ps=[...new Set(list(n.prerequisite_ids))].filter(p=>byId.has(p)&&p!==idOf(n));
      return [idOf(n),ps.filter(p=>!ps.some(q=>q!==p&&ancestors(q).has(p)))];
    }));
  }
  // Height is dependency depth; several starting points share one trunk. The
  // plate keeps a bounded width so labels stay legible: a crowded layer folds
  // into staggered rows and the tree grows taller instead of wider.
  function layout(nodes) {
    const direct=directParents(nodes),depths=new Map();
    function depth(id, visiting = new Set()) {
      if (depths.has(id)) return depths.get(id);
      if (visiting.has(id)) return 0;
      const next = new Set(visiting); next.add(id);
      const parents = direct.get(id) || [];
      const result = parents.length ? 1 + Math.max(...parents.map(p => depth(p, next))) : 0;
      depths.set(id, result); return result;
    }
    nodes.forEach(n => depth(idOf(n)));
    const layers = [];
    for (const n of nodes) (layers[depths.get(idOf(n))] ||= []).push(n);
    const narrow=matchMedia('(max-width:600px)').matches;
    // colW: room one node and its label need within a row (narrow plates show numbers only).
    const colW=narrow?66:170,lg=narrow?84:100,sub=narrow?32:42,top=narrow?50:66;
    const widest=Math.max(1,...layers.map(l=>(l||[]).length));
    // A slim plate: it fits the half-width result column and the desk rail without shrinking text.
    const width=narrow?420:Math.max(600,Math.min(680,widest*colW+120));
    const labelRoom=n=>narrow?50:Math.min(9,shortTitle(n.title||idOf(n)).length)*14+46;
    const positions=new Map(),xs=new Map(),rowsOf=[];
    layers.forEach((layer,d)=>{
      if(!layer?.length){rowsOf[d]=1;return;}
      const want=n=>{const px=(direct.get(idOf(n))||[]).map(id=>xs.get(id)).filter(Number.isFinite);return px.length?px.reduce((a,b)=>a+b,0)/px.length:width/2;};
      const ordered=layer.map(n=>({n,d:want(n)})).sort((a,b)=>a.d-b.d||String(idOf(a.n)).localeCompare(String(idOf(b.n))));
      const count=ordered.length;
      // Outer labels point outward, so the row keeps their full length inside the plate.
      let lo=count>1?Math.max(width*.08,labelRoom(ordered[0].n)):width*.12,hi=count>1?Math.min(width*.92,width-labelRoom(ordered[count-1].n)):width*.88;
      if(hi-lo<width*.55){const mid=(lo+hi)/2;lo=Math.max(width*.08,mid-width*.275);hi=Math.min(width*.92,mid+width*.275);}
      const step=count>1?Math.min(colW,(hi-lo)/(count-1)):colW,rows=Math.max(1,Math.min(count,4,Math.ceil(colW/step-.001)));
      rowsOf[d]=rows;
      ordered.forEach((o,i)=>{o.x=i?Math.max(o.d,ordered[i-1].x+step):o.d;});
      // Shift the whole row to stay inside the plate instead of clamping nodes onto each other.
      let shift=ordered.reduce((a,o)=>a+o.d-o.x,0)/count;
      const first=ordered[0].x+shift,end=ordered[count-1].x+shift;
      if(first<lo)shift+=lo-first;else if(end>hi)shift-=end-hi;
      // Neighbours alternate between rows; the middle of the layer sits highest, like a crown.
      ordered.forEach((o,i)=>{const id=idOf(o.n);xs.set(id,o.x+shift);
        positions.set(id,{x:o.x+shift+jit(id,'x',step*.04),row:rows>1?(i+Math.floor(count/2))%rows:0,layer:d,span:rows*step});});
    });
    const trunk=(layers[0]||[]).length>1,forkRise=lg*.55;
    const rel=[];let y=-lg*.64-(trunk?forkRise:0);
    layers.forEach((layer,d)=>{rel[d]=y;y-=lg+(rowsOf[d]-1)*sub;});
    const last=layers.length-1,highest=last<0?-lg*.64:rel[last]-(rowsOf[last]-1)*sub;
    const ground=top-highest,height=ground+(narrow?62:70);
    for(const [id,p] of positions)p.y=ground+rel[p.layer]-p.row*sub+jit(id,'y',lg*.03);
    for(const n of nodes){const id=idOf(n),p=positions.get(id),parents=(direct.get(id)||[]).map(id=>positions.get(id)?.x).filter(Number.isFinite),base=parents.length?parents.reduce((a,b)=>a+b,0)/parents.length:width/2;p.a=Math.max(-30,Math.min(30,(p.x-base)*(narrow?.32:.2)))+jit(id,'a',6);}
    const rootXs=(layers[0]||[]).map(n=>positions.get(idOf(n)).x);
    const fork=trunk?{x:rootXs.reduce((a,b)=>a+b,0)/rootXs.length,y:ground-forkRise*.85}:null;
    return {width,height,ground,positions,narrow,direct,fork};
  }
  function shortTitle(title) {
    const head=String(title).split(/[：:]/)[0].trim();
    return head.length>=2&&head.length<String(title).length?head:String(title);
  }
  function graph(view,{mini=false,interactive=true}={}) {
    const nodes=nodesFor(view),kind=subject(view),{width,height,ground,positions,narrow,direct,fork}=layout(nodes);
    const size=narrow?27:34,uid='growth-'+(++graphSerial);
    const drawing=svg('svg',{viewBox:`0 0 ${width} ${f(height)}`,class:'growth-graph'+(mini?' miniature':''),role:interactive?'group':'img','aria-label':'自下而上的学习依赖图谱'});
    const defs=svg('defs');drawing.append(defs);
    const wave=`C${f(width*.22)} ${f(ground-5)} ${f(width*.38)} ${f(ground+4)} ${f(width*.52)} ${f(ground)} S${f(width*.84)} ${f(ground-4)} ${width} ${f(ground)}`;
    drawing.append(svg('path',{class:'soil',d:`M0 ${f(ground)} ${wave} L${width} ${f(height)} L0 ${f(height)}Z`}),svg('path',{class:'ground',d:`M0 ${f(ground)} ${wave}`}));
    function branch(c,w1,w2,cls,key,delay){
      const path=svg('path',{class:'br '+cls,d:artwork.taper(c,w1,w2)});
      if(delay!=null && !mini){const mask=svg('mask',{id:uid+'-'+key,maskUnits:'userSpaceOnUse',x:0,y:0,width,height}),reveal=svg('path',{class:'mpath a-draw',pathLength:1,d:artwork.centerline(c)});reveal.style.setProperty('--d',delay+'ms');mask.append(reveal);defs.append(mask);path.setAttribute('mask',`url(#${uid}-${key})`);}
      return path;
    }
    const tendrils=svg('g',{class:'tendrils'});drawing.append(tendrils);
    const roots=(x,s)=>svg('path',{class:'root',d:`M${f(x)} ${f(ground)} q${f(-s*.2)} ${f(s*.3)} ${f(-s*.55)} ${f(s*.55)} M${f(x)} ${f(ground)} q${f(s*.05)} ${f(s*.4)} ${f(s*.1)} ${f(s*.8)} M${f(x)} ${f(ground)} q${f(s*.25)} ${f(s*.2)} ${f(s*.6)} ${f(s*.42)}`});
    if(fork){
      const grown=nodes.some(n=>!list(direct.get(idOf(n))).length&&statusOf(n,view)==='passed');
      drawing.append(branch(artwork.curve(fork.x,ground+2,fork.x,fork.y),size*.4,size*.3,grown?'mature':'young','trunk',growth.replay?0:null),roots(fork.x,size*1.3));
    }
    for(const n of nodes){
      const id=idOf(n),p=positions.get(id),parents=direct.get(id)||[],status=statusOf(n,view),index=nodes.indexOf(n),cls=status==='passed'?'mature':'young';
      if(!parents.length){
        if(fork){const c=artwork.curve(fork.x,fork.y+4,p.x,p.y);drawing.append(status==='locked'?svg('path',{class:'br-future',d:artwork.centerline(c)}):branch(c,size*.26,size*.19,cls,'soil-'+index,growth.replay?160:null));}
        else{const bx=p.x+jit(id,'stem',size*.3),c=artwork.curve(bx,ground+2,p.x,p.y);drawing.append(branch(c,size*.27,size*.2,cls,'soil-'+index,growth.replay?0:null),roots(bx,size));}
      }
      // Up to two direct prerequisites merge as branches; beyond that one carries the
      // leaf and the others reach it as faint tendrils.
      const primary=parents.length>2?[...parents].sort((x,y)=>positions.get(y).layer-positions.get(x).layer||Math.abs(positions.get(x).x-p.x)-Math.abs(positions.get(y).x-p.x))[0]:null;
      for(const parent of parents){
        const from=positions.get(parent),c=artwork.curve(from.x,from.y,p.x,p.y-2),minor=primary&&parent!==primary;
        const edge=svg('g',{class:'edge plant-edge'+(minor?' tendril':''),'data-from':parent,'data-to':id});
        const w1=Math.max(size*.07,size*.22-from.layer*size*.036),w2=Math.max(size*.05,w1-size*.05);
        if(minor)edge.append(svg('path',{class:'br-future tendril-line',d:artwork.centerline(c)}));
        else edge.append(status==='locked'?svg('path',{class:'br-future',d:artwork.centerline(c)}):branch(c,w1,w2,cls,index+'-'+nodes.findIndex(x=>idOf(x)===parent),growth.replay?from.layer*280+120:growth.sprouts.includes(id)?950:null));
        (minor?tendrils:drawing).append(edge);
      }
    }
    nodes.forEach((node,i)=>{
      const id=idOf(node),p=positions.get(id),status=statusOf(node,view),grew=growth.grew.includes(id)&&!mini,sprout=growth.sprouts.includes(id)&&!mini;
      const group=svg('g',{transform:`translate(${f(p.x)} ${f(p.y)})`,class:'plant-node node st-'+status+(id===selected?' sel':''),'data-node':id,...(interactive?{tabindex:0,role:'button','aria-label':`${i+1}. ${node.title}，${statusNames[status]}`,'aria-pressed':String(id===selected)}:{})});
      group.append(svg('circle',{r:f(size*.9),cy:f(-size*.45),class:'hit'}));
      const motion=svg('g',{class:grew?'a-unfurl':sprout||growth.replay&&!mini?'a-sprout':''});motion.style.setProperty('--d',(grew?250:sprout?1500:p.layer*280+420)+'ms');
      if(status==='current')motion.append(svg('circle',{class:'ring',cx:0,cy:f(-size*.45),r:f(size*.82)}));
      if(status==='available')motion.append(svg('circle',{class:'halo',cx:0,cy:f(-size*.28),r:f(size*.55)}));
      if(id===view.current_node_id&&view.mode==='remediate')motion.append(svg('circle',{class:'warn-ring',cx:0,cy:f(-size*.45),r:f(size*.98)}));
      if(id===view.review_node_id)motion.append(svg('path',{class:'drop',transform:`translate(${f(size*.62)} ${f(-size*1.05)}) scale(${f(size/34)})`,d:'M0 -9 C5 -3 6 0 6 3 A6 6 0 0 1 -6 3 C-6 0 -5 -3 0 -9Z'}));
      motion.append(svg('g',{transform:`rotate(${f(p.a)})`},leaf(kind,status,list(node.objectives).length,size,grew)));group.append(motion);
      if(!mini){const label=node.title||id,left=p.x<width/2-8,x=(left?-1:1)*(size*.9+6),title=svg('title');// Labels stay on the outer side and are shortened to the room left before the plate edge.
      const fit=Math.max(4,Math.min(13,Math.floor((Math.min(left?p.x:width-p.x,p.span)-size*.9-12)/14))),theme=shortTitle(label);title.textContent=label;group.append(title);
        if(narrow)group.append(text(x,-size*.45,String(i+1).padStart(2,'0'),'ln',left?'end':'start'));
        else group.append(text(x,-size*.55,theme.length>fit?theme.slice(0,fit-1)+'…':theme,'lt',left?'end':'start'),text(x,-size*.55+18,status==='passed'?`已长成 · ${list(node.objectives).length} 个目标`:statusNames[status],'ls st-'+status,left?'end':'start'));}
      if(interactive){const choose=()=>{selected=id;ctx.render();document.querySelector('.specimen h2')?.focus({preventScroll:true});};group.addEventListener('click',choose);group.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose();}});}
      drawing.append(group);
      if(grew&&!matchMedia('(prefers-reduced-motion:reduce)').matches)setTimeout(()=>{if(drawing.isConnected)artwork.burst(drawing,p.x,p.y-size*.55);},0);
    });
    if(!mini){drawing.append(text(width/2,ground+26,'土壤 · 你的基础','soil-k','middle'));const prior=list(view.profile?.prior_knowledge?.self_reported).join('；')||'从这里开始，慢慢生长';drawing.append(text(width/2,ground+45,prior.length>36?prior.slice(0,36)+'…':prior,'soil-t','middle'));
      if(!narrow)drawing.append(svg('path',{class:'axis',d:`M18 ${f(ground-12)} L18 36 M14 42 L18 36 L22 42`}),text(26,44,'终点','axis-t'),text(26,ground-14,'起步','axis-t'));
      if(!nodes.length)drawing.append(text(width/2,height/2,'种下一个目标，等待第一片叶子','lt','middle'));
    }
    if(interactive){const focus=id=>{const ancestors=new Set([id]),queue=[id];while(queue.length){const n=nodes.find(n=>idOf(n)===queue.pop());for(const p of list(n?.prerequisite_ids))if(!ancestors.has(p)){ancestors.add(p);queue.push(p);}}drawing.classList.add('focusing');drawing.querySelectorAll('.plant-node').forEach(n=>n.classList.toggle('anc',ancestors.has(n.dataset.node)));drawing.querySelectorAll('.edge').forEach(e=>e.classList.toggle('anc',ancestors.has(e.dataset.from)&&ancestors.has(e.dataset.to)));};drawing.addEventListener('pointerover',e=>{const n=e.target.closest('[data-node]');if(n)focus(n.dataset.node);});drawing.addEventListener('pointerleave',()=>drawing.classList.remove('focusing'));drawing.addEventListener('focusin',e=>{const n=e.target.closest('[data-node]');if(n)focus(n.dataset.node);});drawing.addEventListener('focusout',()=>drawing.classList.remove('focusing'));}
    return drawing;
  }
  function navigate(next, replace = false) {
    if (state.busy) return;
    screen = next; selected ||= state.view?.current_node_id;
    const hash = state.id ? `#/p/${encodeURIComponent(state.id)}/${next}` : '#/garden';
    if (location.hash !== hash) history[replace ? 'replaceState' : 'pushState'](null,'',hash);
    ctx.render(); window.scrollTo({top:0, behavior:'instant'});
  }
  async function readRoute() {
    if (state.busy) { syncRoute(); return; }
    const match = location.hash.match(/^#\/p\/([^/]+)\/(tree|learn|result)$/);
    routing = true;
    try {
      if (match) {
        screen = match[2];
        const id = decodeURIComponent(match[1]);
        if (id !== state.id) await selectProject(id);
        ctx.render();
      } else if (location.hash === '#/garden') await ctx.newProject();
    } finally {routing = false;}
  }
  function syncRoute() {
    if (routing) return;
    const hash = state.id ? `#/p/${encodeURIComponent(state.id)}/${screen}` : '#/garden';
    if (location.hash !== hash) history.replaceState(null,'',hash);
  }
  // The compass offers exactly one next step; everything else stays in the page.
  const nextSteps = [['retry','重试这一步'],['confirm_profile','让 AI 规划路线'],['confirm_plan','确认路线'],['replan','重新规划路线'],
    ['begin','开始第一课'],['begin_learning','开始第一课'],['start_quiz','开始小测'],['submit_answer','完成小测'],
    ['return_to_current','回到当前小节'],['return_to_teaching','继续学习'],['continue_with_new_budget','追加额度继续']];
  const directSteps = new Set(['confirm_profile','replan','begin','begin_learning','start_quiz','return_to_current','return_to_teaching']);
  function compassAction(view) {
    const slot = document.getElementById('compass-action');
    slot.replaceChildren();
    // A replan is only the next step when the current draft can no longer be confirmed.
    const step = view && !view.read_only && nextSteps.find(([action]) => allowed(action) && (action !== 'replan' || view.requires_replan || !allowed('confirm_plan')));
    if (!step) return;
    const [action, label] = step;
    slot.append(el('button', {type:'button', class:'btn compass-next', 'data-write':'true', disabled:state.busy, text:'下一步：' + label, onclick:() => {
      if (directSteps.has(action)) { command(action); return; }
      // Steps that need the learner's input (choices, answers) open the place where they are given.
      if (screen !== 'learn') navigate('learn');
      const target = action === 'submit_answer' ? document.querySelector('#quiz-form fieldset') : [...document.querySelectorAll('#content .btn.primary')].find(b => b.textContent === actionLabels[action]);
      target?.scrollIntoView({block:'center', behavior:'smooth'});
      if (target?.matches('button')) target.focus({preventScroll:true});
    }}));
  }
  function shell() {
    const view = state.view;
    if (project !== state.id) {project=state.id;selected=view?.current_node_id || null;if (!routing) screen='learn';}
    document.body.dataset.subject = subject(view);
    document.body.dataset.screen = !view ? 'garden' : screen === 'tree' ? 'tree' : screen === 'result' && view.feedback ? 'result' : view.page_state;
    const total = nodesFor(view || {}).length, passed = list(view?.completed_node_ids).length;
    const current = nodesFor(view || {}).find(n => idOf(n) === view?.current_node_id);
    const compass = document.getElementById('growth-compass');
    compass.replaceChildren(el('span', {text: current?.title || (view ? '为新的知识播种' : '每一个目标，都可以生长')}));
    if (total) compass.append(el('span', {class:'growth-segments'},nodesFor(view).map(n=>el('i',{class:statusOf(n,view)}))),el('span',{text:`已长成 ${passed}/${total}`}));
    const nav = document.getElementById('view-tabs'); nav.hidden = !view || !total;
    nav.replaceChildren(...[['tree','生长图谱'],['learn','学习台']].map(([key,label])=>el('button',{type:'button',text:label,'aria-current':screen===key?'page':null,disabled:state.busy,onclick:()=>navigate(key)})));
    if (view?.feedback) nav.append(el('button',{type:'button',text:'结果','aria-current':screen==='result'?'page':null,disabled:state.busy,onclick:()=>navigate('result')}));
    compassAction(view);
    syncRoute();
  }
  function specimen(view) {
    const nodes = nodesFor(view), node = nodes.find(n=>idOf(n)===selected) || nodes.find(n=>idOf(n)===view.current_node_id) || nodes[0];
    if (!node) return el('div');
    const status = statusOf(node,view), prereqs = list(node.prerequisite_ids);
    const inner = el('div',{class:'specimen-inner'},el('div',{class:'specimen-top'},`标本 No.${String(nodes.indexOf(node)+1).padStart(2,'0')}`,chip(statusNames[status],status==='passed'?'green':'cyan')),el('h2',{text:node.title,tabindex:-1}));
    const rows = el('dl');
    const row=(label,value)=>rows.append(el('dt',{text:label}),el('dd',{},value));
    row('生长条件',prereqs.length ? prereqs.map(id=>nodes.find(n=>idOf(n)===id)?.title || id).join(' / ') : '从你的现有基础出发');
    row('学会后能',el('ul',{},list(node.objectives).map(o=>el('li',{text:o.observable_outcome || o.description || o.objective_id}))));
    row('预计',`约 ${node.estimated_minutes || '—'} 分钟`);
    inner.append(rows);
    const current = idOf(node)===view.current_node_id;
    const preparing=!view.learning_runtime_ready&&screen!=='tree';
    if (!preparing && (current || !view.learning_runtime_ready || status==='passed' && view.page_state==='completed')) inner.append(el('div',{class:'actions'},button(view.learning_runtime_ready?'进入学习台':'查看课程准备',()=>navigate('learn'),'primary')));
    inner.append(el('p',{class:'specimen-note',text:status==='locked'?'先完成前置小节，新的芽会自然解锁。':current?'你现在就在这一节。读完讲解、问清楚，再做小测。':status==='passed'?'这一片叶子已经长成。通过记录已保存。':'这节的前置条件已满足，课程会按学习计划安排下一步。'}));
    return el('section',{class:'specimen'},inner);
  }
  function tree(view) {
    const passed=list(view.completed_node_ids).length, nodes=nodesFor(view);
    const species={math:'数学 · 云杉',code:'编程 · 蕨',lang:'语言 · 花藤',general:'通用 · 银杏'}[subject(view)];
    const head=el('header',{class:'garden-heading'},el('div',{class:'eyebrow',text:'生长图谱 · '+species}),el('h1',{text:currentName(view)}),el('p',{text:'目标：'+(view.profile?.bounded_goal || view.profile?.goal || '一步一步，将新知变成自己的能力。')}));
    head.append(button('重播生长',()=>{growth={grew:[],sprouts:[],replay:true};ctx.render();clearTimeout(growthTimer);growthTimer=setTimeout(()=>{growth={grew:[],sprouts:[],replay:false};},8000);}));
    const sheet=el('section',{class:'tree-sheet'},el('div',{class:'plate-caption',text:'图版 · 越往上，需要的前置越多'}),el('div',{class:'graph-scroll'},graph(view)),el('div',{class:'plate-footer',text:`真实学习进度 · 共 ${nodes.length} 节`}));
    const details=el('details',{class:'node-list',open:matchMedia('(max-width:600px)').matches},el('summary',{text:'按列表查看全部小节与依赖'}));
    nodes.forEach((n,i)=>details.append(el('button',{type:'button',class:'node-list-row',onclick:()=>{selected=idOf(n);ctx.render();}},el('span',{text:String(i+1).padStart(2,'0')}),el('span',{text:n.title}),chip(statusNames[statusOf(n,view)]))));
    const legend=el('section',{class:'plant-legend'},el('h3',{text:'怎么读这张图'}),el('div',{class:'legend-grid'},Object.entries(statusNames).map(([key,label])=>{const icon=svg('svg',{viewBox:'-13 -28 26 30','aria-hidden':'true'},leaf(subject(view),key,3,22));return el('div',{},icon,el('span',{text:label}));})),el('div',{class:'garden-summary'},el('strong',{text:`${passed} / ${nodes.length}`}),el('span',{text:'每完成一节，就长出一片新叶。枝条汇合的地方，表示这一节需要多个前置。'})));
    return el('div',{},head,el('div',{class:'tree-layout'},el('div',{},sheet,details),el('aside',{class:'specimen-side'},specimen(view),legend)));
  }
  function nextLabel(p) {
    const current=nodesFor(p).find(n=>idOf(n)===p.current_node_id)?.title;
    return {profile_review:'确认学习起点',materials_required:'补充学习资料',plan_review:'确认生长路线',learning:current?`学习「${current}」`:'继续学习',
      quiz:current?`完成「${current}」的小测`:'完成小测',paused:'休息结束，继续学习',exploring:'继续自由探索',completed:'回顾整棵树'}[p.page_state]||ctx.labels[p.page_state]||'继续';
  }
  function treeName(p) {
    const topic=p.profile?.subject_label;
    return p.display_name || (/python/i.test([topic,p.profile?.goal].join(' '))?'Python':topic==='AI待整理'?currentName(p):topic || currentName(p));
  }
  function plot(p,featured=false) {
    const seed=nodesFor(p).length?graph(p,{mini:true,interactive:false}):document.querySelector('#grading-state .seed').cloneNode(true);
    seed.classList.add('garden-seed');
    const total=nodesFor(p).length,grown=list(p.completed_node_ids).length;
    const open=el('button',{class:'garden-project-open',type:'button',onclick:()=>selectProject(p.project_id)},seed,el('div',{},
      el('span',{class:'eyebrow',text:featured?'继续上次':p.page_state==='completed'?'这段路线已长成':ctx.labels[p.page_state] || '刚刚种下'}),
      el('h3',{text:treeName(p)}),el('p',{class:'tree-goal',text:p.profile?.goal || currentName(p)}),
      el('p',{text:total?`已长成 ${grown} / ${total} 片叶子`:'种子已在这里，等待规划生长路线'}),
      el('p',{class:'tree-next',text:'下一步 · '+nextLabel(p)}),featured?el('span',{class:'btn primary',text:'继续学习'}):null));
    const more=el('button',{type:'button',class:'project-more','aria-label':'管理 '+currentName(p),text:'⋯',onclick:e=>projectMenu(p,e.currentTarget)});
    return el('article',{class:'garden-project'+(featured?' featured':''),'data-subject':subject(p)},open,more);
  }
  function home(welcome) {
    welcome.classList.add('garden-home');
    const heading=welcome.querySelector('.page-heading'),create=welcome.querySelector('#create-card'),presets=welcome.querySelector('.preset-row');
    const leaves=state.projects.reduce((sum,p)=>sum+list(p.completed_node_ids).length,0);
    if (heading) heading.replaceChildren(el('div',{},el('div',{class:'eyebrow',text:'SKILLTREE · A GARDEN OF KNOWLEDGE'}),el('h1',{text:'我的花园'}),el('p',{text:state.projects.length?`你在这里养着 ${state.projects.length} 棵树，已经长出 ${leaves} 片叶子。今天想照料哪一棵，或者种下新的？`:'把好奇种下，让知识慢慢生长。你想种下第一棵什么树？'})));
    // Planting comes first; the example presets sit right under the goal box.
    if (create) { create.classList.add('garden-hero'); heading.after(create); }
    if (presets) { const caption=el('p',{class:'preset-caption',text:'不知道从哪开始？试试一个示例：'}); (create||heading).after(caption,presets); }
    if (!state.projects.length) return welcome;
    const last=storage.read('selection')?.id;
    const featured=state.projects.find(p=>p.project_id===last&&p.page_state!=='completed')||state.projects.find(p=>p.page_state!=='completed'&&nodesFor(p).length);
    const cards=el('div',{class:'garden-projects'});
    for (const p of state.projects) if (p!==featured) cards.append(plot(p));
    const section=el('section',{class:'garden-beds','aria-label':'我的学习树'});
    if (featured) section.append(plot(featured,true));
    if (cards.childElementCount) section.append(el('div',{class:'garden-section-title'},el('h2',{text:featured?'花园里的其他树':'正在生长'})),cards);
    welcome.append(section);
    return welcome;
  }
  function lesson(view) {
    if (screen==='tree') return tree(view);
    if (screen==='result' && view.feedback) return result(view);
    const stage=view.page_state, nodes=nodesFor(view), node=nodes.find(n=>idOf(n)===(view.review_node_id || view.current_node_id));
    const head=el('header',{class:'garden-heading'},el('div',{class:'eyebrow',text:stage==='quiz'?'小测 · 让知识落地':'学习台 · 每次向前一小步'}),el('h1',{text:stage==='completed'?'你的花园，又长大了一点':node?.title || currentName(view)}));
    const main=el('div',{class:'desk-main'});
    if(['running','error','paused','budget_exhausted','assessment_review','completed'].includes(stage)) main.append(recoveryCard(view));
    if(stage==='completed') main.append(graph(view,{interactive:false}));
    if(stage==='quiz') {
      const quiz=quizCard(view); quiz.classList.add('quiz-sheet');
      const progress=el('nav',{class:'quiz-progress','aria-label':'作答进度'});
      quiz.querySelectorAll('fieldset').forEach((q,i)=>{
        q.id='question-'+i;
        const mark=el('button',{type:'button',text:String(i+1).padStart(2,'0'),'aria-label':`转到第 ${i+1} 题`,onclick:()=>q.scrollIntoView({block:'center'})});
        const update=()=>{const done=[...q.querySelectorAll('input,textarea')].some(n=>n.type==='checkbox'||n.type==='radio'?n.checked:!!n.value.trim());mark.classList.toggle('answered',done);mark.setAttribute('aria-label',`第 ${i+1} 题，${done?'已作答':'待作答'}`);};
        q.addEventListener('input',update);update();progress.append(mark);
      });
      main.append(progress,quiz,el('p',{class:'draft-note',text:'草稿自动保存在本机。每一道题都完成后，再提交这次小测。'}));
    }
    if(['learning','exploring'].includes(stage)) {
      if(view.mode==='review') main.append(el('div',{class:'notice blue',text:`先回头补「${node?.title || '前置知识'}」，补完再回到当前小节。`}));
      if(view.mode==='remediate') main.append(el('div',{class:'notice',text:'还差一点。针对上次没达标的目标，再巩固一下。'}));
      if(stage==='exploring') main.append(el('div',{class:'notice blue',text:'自由探索 · 这里可以讨论和追问，不进行正式测评。'}));
      main.append(desk(view,node));
    }
    const extra=el('div',{class:'actions desk-extra'});
    if(stage==='quiz' && allowed('return_to_teaching'))extra.append(button('先返回教学',()=>command('return_to_teaching')));
    if(['learning','exploring','quiz'].includes(stage) && allowed('rest'))extra.append(button(actionLabels.rest,()=>command('rest'),'subtle'));
    if(view.feedback && stage!=='completed')extra.append(button('查看上次小测结果',()=>navigate('result'),'subtle'));
    if(extra.childElementCount)main.append(extra);
    const rail=el('aside',{class:'desk-rail','aria-label':'本节学习目标与进度'},el('button',{type:'button',class:'mini-tree',onclick:()=>navigate('tree')},graph(view,{mini:true,interactive:false}),el('span',{text:'← 返回生长图谱'})));
    if(node)rail.append(el('section',{},el('h3',{text:'学完这一节，你应该能'}),el('ul',{class:'desk-objectives'},list(node.objectives).map(o=>el('li',{text:o.observable_outcome || o.objective_id})))));
    const chance=chances(view);if(chance)rail.append(chance);
    const root=el('div',{},head,el('div',{class:'study-desk'+(stage==='quiz'?' quiz-focus':'')},rail,main));
    root.append(el('details',{class:'section-details'},el('summary',{text:'查看学习资料与完整路线'}),sourceCard(view),renderPlan(view)));
    return root;
  }
  function desk(view,node) {
    const title=view.mode==='remediate'?'针对性补弱':view.mode==='review'?'回顾前置知识':view.page_state==='exploring'?'自由探索':'这一节的讲解';
    const card=el('section',{class:'card lesson-sheet'},el('div',{class:'card-header'},el('h2',{text:title}),node?chip(node.title,'cyan'):null));
    if(view.profile?.learning_mode==='exploration')card.append(el('p',{class:'notice',text:'这门课暂时没有可评分的练习，可以继续提问和讨论。'}));
    // The opening lesson is the turn without a question; `tutor` is only the latest reply.
    const turns=list(view.conversation),opening=[...turns].reverse().find(t=>!t.question),asked=turns.filter(t=>t.question);
    const tutorText=typeof view.tutor==='string'?view.tutor:view.tutor?.text;
    const lessonText=opening?.text||(!asked.length?tutorText:null);
    if(lessonText)card.append(el('div',{class:'lesson-body'},markdown(lessonText),citationButtons(opening?opening.citations:view.tutor?.citations,view)));
    else if(!asked.length)card.append(el('p',{class:'muted',text:'讲解还没有准备好，可以点“刷新状态”看看。'}));
    if(asked.length){
      const thread=el('section',{class:'dialogue','aria-label':'追问记录'},el('h3',{text:'你的追问'}));
      for(const t of asked)thread.append(el('div',{class:'bubble me'},el('span',{class:'who',text:'我'}),el('p',{text:t.question})),el('div',{class:'bubble tutor'},el('span',{class:'who',text:'讲解'}),markdown(t.text),citationButtons(t.citations,view)));
      card.append(thread);
    }
    if(allowed('ask')){
      const key='question-'+view.project_id,q=el('textarea',{name:'question',required:true,maxlength:4000,rows:2,placeholder:'哪里还不清楚？也可以举一个你自己的例子。','aria-label':'向 AI 追问'});
      q.value=storage.read(key,'');q.addEventListener('input',()=>storage.write(key,q.value));
      const form=el('form',{class:'composer'},q,el('button',{type:'submit',class:'btn',text:actionLabels.ask,disabled:state.busy}));
      form.addEventListener('submit',async event=>{event.preventDefault();if(!state.busy&&form.reportValidity())await command('ask',{question:q.value.trim()},{busyText:'正在想怎么讲清楚…',after:()=>storage.remove(key)});});
      card.append(form);
      window.SkillTreeControls?.quickAsks(q,{anchor:form});
      window.SkillTreeControls?.autoGrow(q);
      window.SkillTreeControls?.enterToSend(form,q);
    }
    const row=el('div',{class:'actions lesson-actions'});
    for(const action of ['return_to_current','start_quiz','return_to_teaching'])if(allowed(action))row.append(button(actionLabels[action],()=>command(action,{},action==='start_quiz'?{busyText:'正在为这一节出题…'}:{}),action==='start_quiz'?'primary':''));
    if(row.childElementCount)card.append(row);
    return card;
  }
  function chances(view) {
    const r=view.rounds;if(!r||!['learning','quiz','paused'].includes(view.page_state)||view.profile?.learning_mode==='exploration')return null;
    const limit=Math.max(1,r.round_limit||3),left=Math.max(0,limit-(r.effective_rounds||0));
    return el('section',{class:'chances'},el('h3',{text:'本节闯关机会'}),
      el('div',{class:'chance-dots',role:'img','aria-label':`还有 ${left} 次，共 ${limit} 次`},Array.from({length:limit},(_,i)=>el('i',{class:i<left?'on':''}))),
      el('p',{text:left?`还有 ${left} 次。没通过也没关系，会先针对薄弱处补一补。`:'机会用完了，会先暂停，可以选择再追加一次。'}));
  }
  function result(view) {
    const f=view.feedback,g=f.guard||{},action=g.effective_action,passed=g.passed===true;
    const reliable=f.grading_status==='graded'&&action!=='assessment_review';
    const nodes=nodesFor(view),titleOf=id=>nodes.find(n=>idOf(n)===id)?.title;
    const review=action==='revisit_prerequisite'||view.mode==='review';
    const title=passed?'这片叶子长成了':!reliable?'这次没能可靠评分':review?'地基不太稳，先回头补一补':action==='collect_more_evidence'?'还需要再确认一次':'还差一点，再给它一点养分';
    const next=nodes.find(n=>idOf(n)===view.current_node_id&&idOf(n)!==f.node_id);
    const subtitle=passed?(view.page_state==='completed'?'整条路线都已经长成。':next?`新的芽冒出来了：下一节「${next.title}」。`:'每一次认真作答，都让知识扎根得更深。')
      :!reliable?'这不算你答错，也不会消耗闯关机会。可以换一份新的小测。'
      :review?`问题出在前面的基础上：先回顾「${titleOf(view.review_node_id)||'前置知识'}」，再回到「${f.node_title}」。`
      :'看看哪个目标还没达标，针对它再练一下。';
    const card=el('section',{class:'card result-card',id:'evaluation-feedback'},el('div',{class:'card-header'},el('h2',{text:'每个目标的表现'}),chip(f.node_title||'本节',passed?'green':'cyan')));
    for(const r of list(f.objective_results)){
      const ratio=typeof r.score_ratio==='number'?Math.max(0,Math.min(1,r.score_ratio)):null,th=typeof r.threshold==='number'?r.threshold:null,met=ratio!=null&&th!=null&&ratio>=th;
      const pct=v=>Math.round(v*100)+'%';
      const fill=el('span',{class:'meter-fill'}),meter=el('div',{class:'meter'+(met?' met':''),role:'img','aria-label':`得分率 ${ratio==null?'未知':pct(ratio)}，达标线 ${th==null?'未设置':pct(th)}`},fill);
      fill.style.width=(ratio||0)*100+'%';
      if(th!=null){const line=el('span',{class:'meter-line'});line.style.left=th*100+'%';meter.append(line);}
      card.append(el('div',{class:'objective-meter'},el('div',{class:'meter-head'},el('span',{text:r.observable_outcome||r.objective_id}),el('small',{text:(ratio==null?'—':pct(ratio))+(th!=null?` · 达标线 ${pct(th)}`:'')})),meter,r.required===false?el('small',{class:'dim',text:'选学目标'}):null));
    }
    if(reliable&&f.max_score>0)card.append(el('p',{class:'score-line',text:`本次得分 ${f.total_score} / ${f.max_score} · 只反映这一次作答，不等于掌握程度`}));
    const questions=list(f.question_scores||f.question_results);
    if(questions.length){const detail=el('details',{class:'section-details',open:!passed},el('summary',{text:'逐题点评'}));questions.forEach((q,i)=>detail.append(el('div',{class:'feedback-row'},el('div',{class:'feedback-title'},el('span',{text:`第 ${i+1} 题`}),el('small',{text:`${q.score} / ${q.max_score}`})),q.feedback?el('p',{text:q.feedback}):null)));card.append(detail);}
    if(list(g.reasons).length)card.append(el('details',{class:'section-details'},el('summary',{text:'为什么这样安排'}),el('ul',{class:'reason-list'},list(g.reasons).map(r=>el('li',{text:r})))));
    const go=button(view.page_state==='completed'?'查看学习小结':!reliable?'查看重新测验选项':view.mode==='review'?'回顾前置知识':view.mode==='remediate'?'开始针对性补弱':'继续学习',()=>navigate('learn'),'primary');
    return el('div',{class:'result-view'+(passed?' passed':'')},el('header',{class:'garden-heading'},el('div',{class:'eyebrow',text:'一次小测，一点生长'}),el('h1',{text:title}),el('p',{text:subtitle})),el('div',{class:'result-layout'},el('div',{class:'result-plant'},graph(view,{interactive:false})),el('div',{},card,el('div',{class:'actions'},go,button('回到生长图谱',()=>navigate('tree'))))));
  }
  function prepare(view, root) {
    if(screen==='tree' && nodesFor(view).length)return tree(view);
    root.classList.add('preparation-view');
    const eyebrow=root.querySelector('.eyebrow');if(eyebrow)eyebrow.textContent='播种 · 为这一次学习准备好土壤';
    const plan=root.querySelector('.plan-list');
    if(nodesFor(view).length && plan) {
      const preview=el('div',{class:'route-preview'},el('div',{class:'route-graph'},el('p',{class:'route-hint',text:view.frozen?'这条路线已经确认。点任意一片芽，查看这一节要学会什么。':'所有小节都还是芽苞。点任意一片，查看这一节要学会什么；不满意可以“调整计划”。'}),el('div',{class:'graph-scroll'},graph(view))),specimen(view));
      const list_=el('details',{class:'section-details route-list'},el('summary',{text:`按列表查看全部 ${nodesFor(view).length} 个小节`}));
      plan.before(preview);plan.before(list_);list_.append(plan);
    }
    return root;
  }
  function afterWrite(body, view, previous) {
    clearTimeout(growthTimer);
    const completed=new Set(list(previous?.completed_node_ids));
    growth={grew:list(view?.completed_node_ids).filter(id=>!completed.has(id)),sprouts:nodesFor(view||{}).filter(n=>n.status!=='locked'&&nodesFor(previous||{}).find(old=>idOf(old)===idOf(n))?.status==='locked').map(idOf),replay:false};
    growthTimer=setTimeout(()=>{growth={grew:[],sprouts:[],replay:false};},6000);
    if(body.action==='submit_answer' && view?.feedback)screen='result';
    else if(!routing)screen='learn';
  }
  function init() {
    const theme=storage.read('theme','light');
    document.documentElement.dataset.theme=theme==='dark'?'dark':'light';
    const toggle=document.getElementById('theme-toggle');
    const label=()=>{toggle.textContent=document.documentElement.dataset.theme==='dark'?'☀':'☾';toggle.setAttribute('aria-label',document.documentElement.dataset.theme==='dark'?'切换浅色外观':'切换深色外观');};label();
    toggle.addEventListener('click',()=>{const next=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=next;storage.write('theme',next);label();});
    document.getElementById('garden-home').addEventListener('click',()=>ctx.newProject());
    document.getElementById('records-toggle').addEventListener('click',()=>{const side=document.getElementById('sidebar');side.classList.add('open');document.getElementById('sidebar-shade').hidden=false;document.getElementById('mobile-menu').setAttribute('aria-expanded','true');});
    window.addEventListener('hashchange',readRoute);
    matchMedia('(max-width:600px)').addEventListener('change',()=>{if(!state.busy)ctx.render();});
  }
  return {shell,home,lesson,prepare,afterWrite,init,readRoute,navigate,graph,syncRoute};
};
