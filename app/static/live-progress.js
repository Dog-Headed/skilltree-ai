/* Only public text snapshots are shown here. Canonical DTOs still drive the UI. */
'use strict';
(() => {
  const labels = { working:'正在准备这次学习…',scope:'正在确认学习范围…',notes:'正在整理学习资料…',
    plan:'正在安排学习路线…',teaching:'正在为你展开讲解…',quiz:'正在准备这一节的小测…',
    grade:'正在核对作答与评分…',diagnosis:'正在判断下一步学习安排…',review:'正在核对题目与反馈…',checking:'正在整理生成内容…' };
  let active = null;
  function clear() {
    active?.stop(); active=null;
    const panel=document.getElementById('live-generation');
    if(panel) { panel.hidden=true; document.getElementById('live-generation-text').textContent=''; }
  }
  function watch(jobId,{renderText}={}) {
    clear();
    const panel=document.getElementById('live-generation'), body=document.getElementById('live-generation-text');
    const source=typeof EventSource==='function'?new EventSource('/jobs/'+encodeURIComponent(jobId)+'/events'):null;
    let errors=0, stopped=false, label='', shown=false;
    const handle={get label(){return label;},stop(){if(stopped)return;stopped=true;source?.close();}};
    active=handle;
    source?.addEventListener('progress',event=>{
      if(stopped || active!==handle)return;
      let value;try {value=JSON.parse(event.data);}catch{return;}
      if(value.state==='queued')label=`正在排队 · 等待位置第 ${Number(value.position)||1} 位`;
      else label=labels[value.stage]||labels.working;
      const busy=document.getElementById('busy-text');if(busy)busy.textContent=label;
      const text=value.stage==='teaching' && typeof value.text==='string'?Array.from(value.text).slice(0,8000).join(''):'';
      if(panel && body){
        const follow=body.scrollHeight-body.scrollTop-body.clientHeight<80;
        if(text && typeof renderText==='function'){
          try {body.replaceChildren(renderText(text));}catch{body.textContent=text;}
        } else body.textContent=text;
        panel.hidden=!text;
        if(text){
          const grading=document.getElementById('grading-state');if(grading)grading.hidden=true;
          if(!shown){shown=true;panel.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});}
          if(follow)body.scrollTop=body.scrollHeight;
        }
      }
      errors=0;
    });
    source?.addEventListener('done',()=>handle.stop());
    source?.addEventListener('closed',()=>{handle.stop();if(panel)panel.hidden=true;if(body)body.textContent='';});
    if(source)source.onerror=()=>{if(++errors>=3)handle.stop();};
    return handle;
  }
  addEventListener('pagehide',clear);
  window.SkillTreeLive={watch,clear};
})();
