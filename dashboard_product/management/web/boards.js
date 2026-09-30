"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const board = document.body.dataset.board;
  const ids = board === "university" ? ["university"] : ["prep", "high"];
  const state = {data:null, base:null, period:"FY27", person:null, monthMode:"performance", tab:"overview", mask:7, cache:new Map(), request:0};
  const esc = value => String(value ?? "").replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = v => typeof v === 'number' && Number.isFinite(v) ? new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(v) : '—';
  const pct = v => typeof v === 'number' && Number.isFinite(v) ? `${(v*100).toFixed(1)}%` : '—';
  const period = () => (state.data||state.base).periods.find(p=>p.id===state.period);
  const teams = p => board==='prep_high' ? state.mask===0?[]:(p?.teams||[]) : (p?.teams||[]).filter(t=>ids.includes(t.id));
  const status = m => m?.status === 'not_connected' ? '未接入' : m?.status === 'not_configured' ? '不纳入考核' : m?.status === 'future' ? '尚未开始' : number(m?.actual);
  const target = m => m?.target == null ? '未配置' : number(m.target);
  const yoy = m => `<span class="${m?.yoy < 0 ? 'yoy-negative':'yoy-positive'}">${pct(m?.yoy)}</span>`;
  function progress(m,p) {
    if(m?.completion==null) return `<span class="status-text">${m?.status==='future'?'尚未开始':m?.target==null?'目标未配置':'暂无完成进度'}</span>`;
    return `<div class="metric-progress"><span class="progress-track"><i class="progress-fill" style="width:${Math.min(100,Math.max(0,m.completion*100))}%"></i><i class="time-marker" style="left:${Math.min(100,Math.max(0,(p.time_progress||0)*100))}%"></i></span><span class="metric-progress-label">${pct(m.completion)}</span></div>`;
  }
  function metric(m,label,p) {
    const missing=m?.status==='not_connected'||m?.status==='not_configured';
    return `<div class="metric-unit"><span class="metric-title">${label}</span><div class="metric-primary"><strong>${status(m)}</strong></div>${missing?'<span class="status-text">'+(label==='人头'||label==='现金'?'留学现金尚未接入':'暂不考核')+'</span>':`<div class="metric-compare"><span>同期 ${number(m?.prior)}</span>${yoy(m)}</div>${label==='人头'?'':`<div class="metric-target">目标 <strong>${target(m)}</strong></div>${progress(m,p)}`}`}</div>`;
  }
  function table(rows,p,targets=false) {
    return `<div class="table-frame"><table class="compact-yoy"><thead><tr><th>业务组</th><th>工单当期</th><th>同期</th><th>同比</th>${targets?'<th>工单目标</th><th>完成率</th>':''}<th>现金当期（元）</th><th>同期</th><th>同比</th>${targets?'<th>现金目标</th><th>完成率</th>':''}</tr></thead><tbody>${rows.map(r=>`<tr><th>${esc(r.name)}</th><td>${number(r.orders?.actual)}</td><td>${number(r.orders?.prior)}</td><td>${yoy(r.orders)}</td>${targets?`<td>${target(r.orders)}</td><td>${pct(r.orders?.completion)}</td>`:''}<td>${number(r.cash?.actual)}</td><td>${number(r.cash?.prior)}</td><td>${yoy(r.cash)}</td>${targets?`<td>${target(r.cash)}</td><td>${pct(r.cash?.completion)}</td>`:''}</tr>`).join('')}</tbody></table></div>`;
  }
  function renderOverview() {
    const p=period(), selected=teams(p);
    $('board-caption').textContent=`${p.label} · 团队自然月 · 数据截至 ${state.base.metadata.data_through}`;
    $('period-note').textContent=`${p.start_date} — ${p.through_date || p.end_date}  ·  时间进度 ${pct(p.time_progress)}`;
    if(board==='university') {
      const t=selected[0];
      $('university-lines').innerHTML=['training','abroad'].map(line=>`<section class="line-ledger"><header class="line-ledger-head"><h2>${line==='training'?'大学语培':'大学留学'}</h2><small>${line==='training'?'工单 · 现金 · 人头':'按八人团队贡献归属'}</small></header><div class="metric-strip">${['orders','cash','heads'].map((key,i)=>metric(t.lines[line][key],['工单','现金','人头'][i],p)).join('')}</div></section>`).join('');
      $('business-groups-body').innerHTML=(t.business_groups||[]).map(row=>`<tr><th>${esc(row.name)}</th>${['orders','cash','heads'].map((key,i)=>`<td class="group-metric">${metric(row[key],['工单','现金','人头'][i],p)}</td>`).join('')}</tr>`).join('');
      let detail=$('university-yoy');
      if(!detail){detail=document.createElement('div');detail.id='university-yoy';$('business-groups-body').closest('section').append(detail);}
      detail.innerHTML=`<div class="section-bar"><h2>业务组同期对比</h2></div>${table(t.yoy_groups||[],p)}`;
    } else {
      const t=selected[0];
      if(!t){$('prep-teams').innerHTML='<p class="empty-state">请选择至少一个业务组</p>';return;}
      $('prep-teams').innerHTML=`<section class="team-workspace"><header class="team-section-head"><h2>${esc(t.name)}</h2><p>所选业务组汇总</p></header><div class="table-frame"><table class="workbook-table"><thead><tr><th>范围</th><th>工单</th><th>现金（元）</th><th>人头</th></tr></thead><tbody><tr><th>${esc(t.name)}</th>${['orders','cash','heads'].map((key,i)=>`<td>${metric(t.lines.training[key],['工单','现金','人头'][i],p)}</td>`).join('')}</tr></tbody></table></div><div class="section-bar"><h3>业务组目标与完成进度</h3></div>${table(t.business_groups||[],p,true)}<div class="section-bar"><h3>业务组同期对比</h3></div>${table(t.yoy_groups||[],p)}</section>`;
    }
  }

  function brief(m){return `<strong>${status(m)}</strong><small>同期 ${number(m?.prior)} · 同比 ${pct(m?.yoy)}</small>`;}
  function renderDetails() {
    FlatTables.render($('flat-board-details'),teams(period())[0],{mode:'both',key:state.period+'|'+state.mask,noAbroad:board==='prep_high'});
  }
  function peopleTable(t) {
    const header='<tr><th>人员</th><th>语培目标</th><th>语培完成</th><th>留学目标</th><th>留学完成</th><th>现金目标（元）</th><th>现金完成</th><th>现金完成率</th><th>人头</th></tr>';
    const rows=(t.people||[]).map(r=>`<tr><th>${esc(r.name)}<small>${r.business_line==='abroad'?'留学市场':'语培市场'}</small></th><td>${r.training_target==null?'未配置':number(r.training_target)}</td><td>${number(r.training_actual)}<small>${pct(r.training_completion)}</small></td><td>${r.home_group!=='大学'?'不下达':r.abroad_target==null?'未配置':number(r.abroad_target)}</td><td>${number(r.abroad_actual)}</td><td>${target(r.cash_actual)}</td><td>${status(r.cash_actual)}</td><td>${pct(r.cash_actual?.completion)}</td><td>${status(r.heads_actual)}</td></tr>`).join('');
    return {header,rows};
  }
  function renderPeople() {
    const p=(state.data||state.base).periods.find(p=>p.id===state.person);
    const selected=teams(p).map(t=>state.monthMode==='calendar'?{...t,...t.person_calendar}:t);
    $('person-month-mode').setAttribute('aria-checked',String(state.monthMode==='calendar'));
    $('people-window').textContent=selected[0]?`${state.monthMode==='calendar'?'自然月':'绩效月'}窗口 ${selected[0].person_start} — ${selected[0].person_through || '尚未开始'} · 时间进度 ${pct(selected[0].person_progress)}`:'暂无人员';
    if(board==='university') $('people-body').innerHTML=peopleTable(selected[0]).rows;
    else $('prep-people').innerHTML=selected.map(t=>{const {header,rows}=peopleTable(t);return `<section class="compact-section"><div class="section-bar"><h2>${esc(t.name)}</h2></div><div class="table-frame"><table class="people-table"><thead>${header}</thead><tbody>${rows}</tbody></table></div></section>`;}).join('');
  }
  function renderCountries() {
    if(board!=='university')return;
    const groups=teams(period())[0]?.country_groups||[];
    $('country-groups').innerHTML=groups.map(g=>`<details class="country-group"><summary><strong>${esc(g.line)}</strong><span>${number(g.total)} 单 · 展开国家</span></summary><div class="table-frame"><table><thead><tr><th>国家</th><th>线上</th><th>线下</th><th>待确认</th><th>合计</th></tr></thead><tbody>${g.countries.map(r=>`<tr><th>${esc(r.country)}</th><td>${number(r.online)}</td><td>${number(r.offline)}</td><td>${number(r.unassigned)}</td><td>${number(r.total)}</td></tr>`).join('')}</tbody></table></div></details>`).join('')||'<p class="empty-state">暂无国家条线记录</p>';
  }
  function showTab(name) {
    state.tab=name;
    document.querySelectorAll('[data-tab]').forEach(button=>{const active=button.dataset.tab===name;button.classList.toggle('is-active',active);button.setAttribute('aria-selected',String(active));});
    document.querySelectorAll('.board-pane').forEach(p=>p.hidden=p.id!=='pane-'+name);
    if(name==='details')renderDetails();
    if(name==='people')renderPeople();
    if(name==='countries')renderCountries();
  }
  document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>showTab(b.dataset.tab)));
  document.querySelectorAll('[data-team-jump]').forEach(a=>a.addEventListener('click',()=>showTab('overview')));
  $('period-select').addEventListener('change',e=>{state.period=e.target.value;renderOverview();showTab(state.tab);});
  $('person-period-select').addEventListener('change',e=>{state.person=e.target.value;renderPeople();});
  $('person-month-mode').addEventListener('click',()=>{state.monthMode=state.monthMode==='performance'?'calendar':'performance';renderPeople();});

  async function selectGroups() {
    const token=++state.request;
    state.mask=[...document.querySelectorAll('.segment-filter input:checked')].reduce((n,input)=>n+Number(input.value),0);
    if(!state.mask){state.data=null;$('segment-status').textContent='请选择至少一个业务组';renderOverview();showTab(state.tab);return;}
    $('segment-status').textContent='正在切换…';
    try {
      let data=state.cache.get(state.mask);
      if(!data){const response=await fetch(`./prep_high.${state.mask}.data.json`,{cache:'no-store'});if(!response.ok)throw Error('missing selection');data=await response.json();}
      if(token!==state.request)return;
      if(data.metadata.run_id!==state.base.metadata.run_id||data.metadata.snapshot_id!==state.base.metadata.snapshot_id||data.metadata.created_at!==state.base.metadata.created_at)throw Error('selection identity mismatch');
      state.cache.set(state.mask,data);state.data=data;
      $('segment-status').textContent=(state.mask&3)===1||(state.mask&3)===2?'青少、初中未单独下达目标，不拆分整体目标。':'';
      renderOverview();showTab(state.tab);
    } catch(error){if(token!==state.request)return;$('segment-status').textContent='筛选数据无法加载，请刷新后重试。';console.error(error);}
  }
  document.querySelectorAll('.segment-filter input').forEach(input=>input.addEventListener('change',selectGroups));
  document.querySelectorAll('[data-groups]').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('.segment-filter input').forEach(input=>input.checked=button.dataset.groups==='all');selectGroups();}));

  const embedded=$('dashboard-data');
  const loading=embedded?Promise.resolve(JSON.parse(embedded.textContent)):fetch(`./${board}.data.json`,{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('数据未就绪');return r.json();});
  loading.then(data=>{
    state.data=data;state.base=data;state.person=data.metadata.data_through.slice(0,7);
    if(board==='prep_high') Object.entries(data.selection_views||{'7':data}).forEach(([key,value])=>state.cache.set(Number(key),value));
    $('period-select').innerHTML=data.periods.map(p=>`<option value="${esc(p.id)}">${esc(p.label)}</option>`).join('');
    $('person-period-select').innerHTML=data.periods.filter(p=>/^\d{4}-\d{2}$/.test(p.id)).map(p=>`<option value="${esc(p.id)}">${esc(p.label)}</option>`).join('');
    $('period-select').value=state.period;$('person-period-select').value=state.person;
    $('period-select').disabled=false;$('person-period-select').disabled=false;$('person-month-mode').disabled=false;
    $('freshness-label').textContent='数据截止';$('freshness-date').textContent=data.metadata.data_through;
    $('footer-source').textContent=`截至 ${data.metadata.data_through}`;
    $('load-state').hidden=true;renderOverview();
  }).catch(error=>{$('load-state').hidden=false;$('load-state').className='load-state is-visible is-error';$('load-state').textContent='数据加载失败，请重新生成看板。';console.error(error);});
})();
