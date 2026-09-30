"use strict";
window.FlatTables = (() => {
  const states=new WeakMap();
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const n=v=>typeof v==='number'?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(v):'—';
  const pct=v=>typeof v==='number'?`${(v*100).toFixed(1)}%`:'—';
  function metric(m){return `<strong>${m?.status==='not_connected'?'未接入':m?.status==='not_configured'?'不纳部门统计':m?.status==='future'?'尚未开始':n(m?.actual)}</strong><small>同期 ${n(m?.prior)} · 同比 <span class="${m?.yoy<0?'negative':'positive'}">${pct(m?.yoy)}</span></small>`;}
  const share=r=>`<span>工单 ${pct(r.share)}</span><small>现金 ${pct(r.cash_share)}</small>${r.channel_cash_share!=null?`<small>渠道内 ${pct(r.channel_cash_share)}</small>`:''}`;
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
    const label=line==='training'?'语培':'留学', result=rows(s,line,schools);
    const headers=gradeMode?'<th>年级</th>':schools?'<th class="rank-col">排名</th><th>学校</th>':'<th>二级渠道</th>';
    const body=result.rows.map(r=>`<tr>${schools&&!gradeMode?`<td class="rank-col">${r.rank}</td>`:''}<th>${esc(r.name)}${r.subname?`<small>${schools?'年级':'业务组'}：${esc(r.subname)}</small>`:''}${!schools?`<small>${esc(r.first_channel||'')}</small>`:''}</th><td>${metric(r.orders)}</td><td>${metric(r.cash)}</td><td>${share(r)}</td></tr>`).join('');
    const info=gradeMode?`${result.total}个年级`:schools?`${s.more[line]?'全部':'前30所'} · 共${result.total}所`:`${result.total}个渠道`;
    const empty=line==='abroad'&&s.options.noAbroad?'本板块不汇总部门留学，个人完成请看人员贡献。':'本期暂无记录';
    return `<section class="flat-card"><header><h3>${label} · ${gradeMode?'年级表现':schools?'学校排名':'渠道表现'}</h3><span>${info}${line==='abroad'?' · 现金未接入':''}</span></header><div class="flat-scroll"><table class="flat-table ${schools&&!gradeMode?'is-schools':''}"><thead><tr>${headers}<th>工单 · 当期／同期／同比</th><th>现金（元）· 当期／同期／同比</th><th>占比</th></tr></thead><tbody>${body||`<tr><td colspan="${schools&&!gradeMode?5:4}">${empty}</td></tr>`}</tbody></table></div>${schools&&!gradeMode&&result.total>30?`<button type="button" data-more="${line}" class="flat-more">${s.more[line]?'收起，仅看前30所':`查看更多学校（30名以后，共${result.total-30}所）`}</button>`:''}</section>`;
  }
  function draw(container,s){
    let html='';
    container.classList.toggle('flat-single',s.options.mode && s.options.mode!=='both');
    if(s.options.mode==='grades'){
      container.innerHTML=`<div class="flat-controls"><label>排序 <select aria-label="年级排序" data-setting="sort"><option value="grade" ${s.sort==='grade'?'selected':''}>年级顺序</option><option value="orders" ${s.sort==='orders'?'selected':''}>工单量降序</option><option value="cash" ${s.sort==='cash'?'selected':''}>现金降序</option></select></label><span>按整体年级汇总，不依附学校列表</span></div><div class="flat-grid">${panel(s,'training',true)}${panel(s,'abroad',true)}</div>`;
      return;
    }
    if(s.options.mode!=='schools')html+=`<div class="flat-controls"><strong>渠道表现</strong><label>展示粒度 <select aria-label="渠道展示粒度" data-setting="channelMode"><option value="channel" ${s.channelMode==='channel'?'selected':''}>按渠道</option><option value="group" ${s.channelMode==='group'?'selected':''}>渠道 × 业务组</option></select></label></div><div class="flat-grid">${panel(s,'training',false)}${panel(s,'abroad',false)}</div>`;
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
  return {render};
})();
