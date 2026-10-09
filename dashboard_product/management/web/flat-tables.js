"use strict";
window.FlatTables = (() => {
  const states=new WeakMap();
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const n=v=>typeof v==='number'?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(v):'—';
  const pct=v=>typeof v==='number'?`${(v*100).toFixed(1)}%`:'—';
  const metricActual=m=>{
    if(m===null||m===undefined)return '—';
    if(typeof m!=='object')return n(m);
    if(m.status==='not_connected')return '未接入';
    if(m.status==='not_configured')return '归属待确认';
    if(m.status==='future')return '尚未开始';
    if(m.status==='not_covered')return '该期间未覆盖';
    if(m.status==='separate_counts'){
      if(m.display)return esc(m.display);
      const parts=Array.isArray(m.parts)?m.parts.map(part=>`${esc(part.label||'')} ${n(part.actual)}${part.unit?` ${esc(part.unit)}`:''}`).join('／'):'';
      return parts||'—';
    }
    if((m.status==='available'||m.status==='partial')&&m.display)return esc(m.display);
    return n(m.actual);
  };
  const metricValue=(m,key='actual')=>{const value=key==='actual'?metricActual(m):n(m?.[key]);return key==='actual'&&typeof m?.actual==='number'&&m?.unit&&!m?.display?`${value} ${esc(m.unit)}`:value;};
  const incomparable=m=>['partial','not_covered','separate_counts'].includes(m?.status);
  function metric(m){return `<strong>${metricActual(m)}</strong><small>同期 ${incomparable(m)?'—':n(m?.prior)} · 同比 <span class="${m?.yoy<0?'negative':'positive'}">${pct(incomparable(m)?null:m?.yoy)}</span></small>`;}
  function comparisonMetric(m){return `<td>${metricActual(m)}</td><td>${incomparable(m)?'—':n(m?.prior)}</td><td><span class="${m?.yoy<0?'negative':'positive'}">${pct(incomparable(m)?null:m?.yoy)}</span></td>`;}
  const share=r=>`<span>工单 ${pct(r.share)}</span><small>现金 ${pct(r.cash_share)}</small>${r.channel_cash_share!=null?`<small>渠道内 ${pct(r.channel_cash_share)}</small>`:''}`;
  function personalAbroadPanels(people,{start,through,caption,showStatusToggle=false,statusMode='01'}={}){
    const windowRange=start||through?`${start||'—'} — ${through||'—'}`:'';
    const windowLabel=[caption,windowRange].filter(Boolean).join(' · ');
    const statusToggle=showStatusToggle?[[0,'删除／回收'],[1,'死单']].map(([bit,label])=>`<label class="order-status-control"><input class="order-status-bit-toggle" type="checkbox" role="switch" data-status-bit="${bit}" aria-label="包含${label}工单"${statusMode[bit]==='1'?' checked':''}><span class="order-status-track" aria-hidden="true"></span><span>包含${label}</span></label>`).join(''):'';
    return (Array.isArray(people)?people:[]).map(person=>{
      const channels=Array.isArray(person.abroad_channels)?person.abroad_channels:[];
      const hasCash=channels.some(channel=>channel.cash!==null&&channel.cash!==undefined);
      const rows=channels.map(channel=>`<tr><th>${esc(channel.name)}</th><td>${esc(channel.first_channel||'—')}</td><td>${metricValue(channel.orders,'actual')}</td><td>${incomparable(channel.orders)?'—':metricValue(channel.orders,'prior')}</td><td><span class="${channel.orders?.yoy<0?'negative':'positive'}">${pct(incomparable(channel.orders)?null:channel.orders?.yoy)}</span></td>${hasCash?`<td>${metricValue(channel.cash,'actual')}</td>`:''}<td>${pct(channel.share)}</td></tr>`).join('');
      const empty=person.abroad_actual==null?'该个人统计窗口尚未开始':'当前窗口暂无留学渠道数据';
      const cashSummary=person.cash_actual!==null&&person.cash_actual!==undefined?`<span>个人现金 <strong>${metricValue(person.cash_actual,'actual')}</strong></span>`:'';
      return `<section class="flat-card personal-abroad-panel"><header><h3>高中留学 · ${esc(person.name)}个人渠道构成</h3><div class="personal-abroad-head-controls"><span>${esc(windowLabel||'个人统计窗口')}</span>${statusToggle}</div></header><div class="personal-abroad-summary"><span>个人工单完成 <strong>${metricValue(person.abroad_actual,'actual')}</strong></span>${cashSummary}</div><div class="flat-scroll personal-abroad-scroll"><table class="flat-table personal-abroad-table"><thead><tr><th>二级渠道</th><th>一级渠道</th><th>工单当期</th><th>工单同期</th><th>工单同比</th>${hasCash?'<th>现金（元）</th>':''}<th>本人占比</th></tr></thead><tbody>${rows||`<tr><td colspan="${hasCash?7:6}">${empty}</td></tr>`}</tbody></table></div></section>`;
    }).join('');
  }
  function rows(s,line,schools){
    if(s.options.mode==='grades'){
      const order=['学龄前','幼儿','幼儿园小班','幼儿园中班','幼儿园大班','一年级','二年级','三年级','四年级','五年级','六年级','初一','初二','初三','高一','高二','高三','10年级(国外高中)','11年级(国外高中)','12年级(国外高中)','13年级(国外高中)','大一','大二','大三','大四','大五','研一','研二','研三','研究生以上','博一','博二','博士在读','博士毕业','大学已毕业','在职','年级待确认'];
      const list=[...(s.data?.grades_by_line?.[line]||[])];
      list.sort((a,b)=>s.sort==='grade' ? (order.includes(a.name)?order.indexOf(a.name):999)-(order.includes(b.name)?order.indexOf(b.name):999)||a.name.localeCompare(b.name,'zh-CN') : (b[s.sort==='cash'&&line==='training'?'cash':'orders']?.actual||0)-(a[s.sort==='cash'&&line==='training'?'cash':'orders']?.actual||0));
      return {rows:list,total:list.length};
    }
    if(schools){
      const list=[...(s.data?.schools_by_line?.[line]||[])];
      const sort=s.sort==='cash'&&line==='training'?'cash':'orders';
      list.sort((a,b)=>(b[sort]?.actual||0)-(a[sort]?.actual||0)||(b.orders?.actual||0)-(a.orders?.actual||0)||a.name.localeCompare(b.name,'zh-CN'));
      const chosen=s.more[line]?list:list.slice(0,30);
      const flat=s.schoolMode==='grade'?chosen.flatMap((r,i)=>(r.grades||[]).map(g=>({...g,name:r.name,subname:g.name,rank:i+1}))):chosen.map((r,i)=>({...r,rank:i+1}));
      return {rows:flat,total:list.length};
    }
    const list=(s.data?.channels||[]).filter(r=>r.business_line===line);
    return {rows:s.channelMode==='group'?list.flatMap(r=>(r.groups||[]).map(g=>({...g,name:r.name,subname:g.name,first_channel:r.first_channel}))):list,total:list.length};
  }
  function panel(s,line,schools){
    const gradeMode=s.options.mode==='grades';
    const channelComparison=!schools&&s.options.mode==='both';
    const label=line==='training'?'语培':'留学', result=rows(s,line,schools);
    const headers=gradeMode?'<th>年级</th>':schools?'<th class="rank-col">排名</th><th>学校</th>':'<th>二级渠道</th>';
    const cashLabel='现金';
    const metricHeaders=channelComparison?`<th>工单·当期</th><th>工单·同期</th><th>工单·同比</th><th>${cashLabel}·当期（元）</th><th>${cashLabel}·同期（元）</th><th>${cashLabel}·同比</th><th>占比</th>`:`<th>工单 · 当期／同期／同比</th><th>${cashLabel}（元）· 当期／同期／同比</th><th>占比</th>`;
    const body=result.rows.map(r=>`<tr>${schools&&!gradeMode?`<td class="rank-col">${r.rank}</td>`:''}<th>${esc(r.name)}${r.subname?`<small>${schools?'年级':'业务组'}：${esc(r.subname)}</small>`:''}${!schools?`<small>${esc(r.first_channel||'')}</small>`:''}</th>${channelComparison?`${comparisonMetric(r.orders)}${comparisonMetric(r.cash)}`:`<td>${metric(r.orders)}</td><td>${metric(r.cash)}</td>`}<td>${share(r)}</td></tr>`).join('');
    const info=gradeMode?`${result.total}个年级`:schools?`${s.more[line]?'全部':'前30所'} · 共${result.total}所`:`${result.total}个渠道`;
    const empty=line==='abroad'&&s.options.noAbroad?'本板块不汇总部门留学，个人完成请看人员贡献。':'本期暂无记录';
    return `<section class="flat-card ${channelComparison?'is-channel-card':''}"><header><h3>${label} · ${gradeMode?'年级表现':schools?'学校排名':'渠道表现'}</h3><span>${info}</span></header><div class="flat-scroll"><table class="flat-table ${schools&&!gradeMode?'is-schools':''} ${channelComparison?'is-channel-comparison':''}"><thead><tr>${headers}${metricHeaders}</tr></thead><tbody>${body||`<tr><td colspan="${channelComparison?8:schools&&!gradeMode?5:4}">${empty}</td></tr>`}</tbody></table></div>${schools&&!gradeMode&&result.total>30?`<button type="button" data-more="${line}" class="flat-more">${s.more[line]?'收起，仅看前30所':`查看更多学校（30名以后，共${result.total-30}所）`}</button>`:''}</section>`;
  }
  function draw(container,s){
    let html='';
    container.classList.toggle('flat-single',s.options.mode && s.options.mode!=='both');
    if(s.options.mode==='grades'){
      container.innerHTML=`<div class="flat-controls"><label>排序 <select aria-label="年级排序" data-setting="sort"><option value="grade" ${s.sort==='grade'?'selected':''}>年级顺序</option><option value="orders" ${s.sort==='orders'?'selected':''}>工单量降序</option><option value="cash" ${s.sort==='cash'?'selected':''}>现金降序</option></select></label><span>按整体年级汇总，不依附学校列表</span></div><div class="flat-grid">${panel(s,'training',true)}${panel(s,'abroad',true)}</div>`;
      return;
    }
    if(s.options.mode!=='schools'){
      const personal=s.options.personalAbroad;
      const abroadPanel=personal?.people?.length?personalAbroadPanels(personal.people,personal):panel(s,'abroad',false);
      html+=`<div class="flat-controls"><strong>渠道表现</strong><label>展示粒度 <select aria-label="渠道展示粒度" data-setting="channelMode"><option value="channel" ${s.channelMode==='channel'?'selected':''}>按渠道</option><option value="group" ${s.channelMode==='group'?'selected':''}>渠道 × 业务组</option></select></label></div><div class="flat-grid ${s.options.mode==='both'?'is-channel-grid':''}">${panel(s,'training',false)}${abroadPanel}</div>`;
    }
    if(s.options.mode!=='channels')html+=`<div class="flat-controls"><strong>学校排名</strong><label>排序 <select aria-label="学校排序" data-setting="sort"><option value="orders" ${s.sort==='orders'?'selected':''}>工单量降序</option><option value="cash" ${s.sort==='cash'?'selected':''}>现金降序</option></select></label><label>展示粒度 <select aria-label="学校展示粒度" data-setting="schoolMode"><option value="school" ${s.schoolMode==='school'?'selected':''}>学校</option><option value="grade" ${s.schoolMode==='grade'?'selected':''}>学校 × 年级</option></select></label></div><div class="flat-grid">${panel(s,'training',true)}${panel(s,'abroad',true)}</div>`;
    container.innerHTML=html;
  }
  function render(container,data,options={}){
    let s=states.get(container);
    if(!s){s={channelMode:'channel',schoolMode:'school',sort:options.mode==='grades'?'grade':'orders',more:{training:false,abroad:false}};states.set(container,s);
      container.addEventListener('change',e=>{const key=e.target.dataset.setting;if(key){s[key]=e.target.value;s.more={training:false,abroad:false};draw(container,s);container.querySelector(`[data-setting="${key}"]`)?.focus();}});
      container.addEventListener('click',e=>{const line=e.target.dataset.more;if(line){s.more[line]=!s.more[line];draw(container,s);}});
    }
    if(s.options?.key!==options.key)s.more={training:false,abroad:false};
    s.data=data;s.options=options;draw(container,s);
  }
  return {render,personalAbroadPanels};
})();
