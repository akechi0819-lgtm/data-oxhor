"use strict";
window.CapacityView = (()=>{
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=v=>typeof v==='number'&&Number.isFinite(v)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(v):'—';
  const pct=v=>typeof v==='number'&&Number.isFinite(v)?`${(v*100).toFixed(1)}%`:'—';
  const states=new WeakMap();
  function brief(m){return `<strong>${m?.actual==null?'未接入':num(m.actual)}</strong><small>同期 ${num(m?.prior)}</small><small class="${m?.yoy<0?'negative':'positive'}">同比 ${pct(m?.yoy)}</small>`;}
  function radar(p){
    const axes=p?.radar?.axes||[];if(axes.length!==6)return '<p>六维数据未就绪</p>';
    const cx=180,cy=124,r=82,point=(i,ratio)=>{const angle=-Math.PI/2+i*Math.PI/3;return [cx+Math.cos(angle)*r*ratio,cy+Math.sin(angle)*r*ratio];};
    const polygon=ratio=>axes.map((_,i)=>point(i,ratio).join(',')).join(' ');
    let svg=`<svg viewBox="0 0 360 255" role="img" aria-label="${esc(p.name)}与本团队均值的六维对比">`;
    [.25,.5,.75,1].forEach(k=>{svg+=`<polygon points="${polygon(k)}" fill="none" stroke="#dbe4ed"/>`;});
    axes.forEach((a,i)=>{const pt=point(i,1),label=point(i,1.34);svg+=`<line x1="${cx}" y1="${cy}" x2="${pt[0]}" y2="${pt[1]}" stroke="#e2e9ef"/><text x="${label[0]}" y="${label[1]+4}" text-anchor="${i===0||i===3?'middle':i<3?'start':'end'}" font-size="12" fill="#344f69">${esc(a.label)}</text>`;});
    [['mean','#98a8b7'],['value','#2864ba']].forEach(([field,color])=>{
      const points=axes.map((a,i)=>point(i,typeof a[field]==='number'?Math.max(0,Math.min(1,a[field]/a.scale)):0));
      if(axes.every(a=>typeof a[field]==='number'))svg+=`<polygon points="${points.map(p=>p.join(',')).join(' ')}" fill="${color}" fill-opacity=".15" stroke="${color}" stroke-width="2"/>`;
      axes.forEach((a,i)=>{if(typeof a[field]==='number')svg+=`<circle cx="${points[i][0]}" cy="${points[i][1]}" r="3" fill="${color}"/>`;});
    });svg+='</svg>';
    return `<header><h3>个人六维对比 · 语培</h3><span>${esc(p.name)} / 本团队均值</span></header>${svg}<div class="radar-key"><span>● 个人</span><span>● 团队均值</span></div><table class="radar-values"><thead><tr><th>维度</th><th>个人</th><th>均值</th><th>相对均值</th></tr></thead><tbody>${axes.map(a=>`<tr><th>${esc(a.label)}</th><td>${a.key==='conversion'?pct(a.value):num(a.value)}</td><td>${a.key==='conversion'?pct(a.mean):num(a.mean)}</td><td>${pct(a.relative)}</td></tr>`).join('')}</tbody></table><div class="capacity-reference"><span>标准现金产能 <b>${num(p.cash_capacity)}元</b></span><span>时间进度完成率 <b>${pct(p.cash_progress_completion)}</b></span></div>`;
  }
  function render(container,people,metadata,filter='all'){
    let s=states.get(container);if(!s){s={name:null};states.set(container,s);container.addEventListener('click',e=>{const button=e.target.closest('[data-capacity-person]');if(button){s.name=button.dataset.capacityPerson;draw();}});}
    const rows=people.filter(p=>filter==='all'||p.peer_group===filter).sort((a,b)=>b.orders-a.orders||a.name.localeCompare(b.name,'zh-CN'));
    if(!rows.some(p=>p.name===s.name))s.name=rows[0]?.name;
    s.rows=rows;s.metadata=metadata;
    function draw(){const rows=s.rows,selected=rows.find(p=>p.name===s.name);container.innerHTML=`<p class="capacity-meta">2027财年累计：${esc(s.metadata.capacity_start)} — ${esc(s.metadata.data_through)}</p><div class="capacity-workspace"><section class="capacity-ledger"><header><h3>人员贡献明细</h3><span>当前筛选 ${rows.length} 人 · 按工单总量降序</span></header><div class="capacity-scroll"><table><thead><tr><th>人员</th><th>大学语培</th><th>高中语培</th><th>预备语培</th><th>留学工单</th><th>其他工单</th><th>工单合计<br>当期／同期／同比</th><th>语培现金（元）<br>当期／同期／同比</th><th>签约人头<br>当期／同期／同比</th></tr></thead><tbody>${rows.map(p=>`<tr class="${p.name===s.name?'selected':''}"><th><button type="button" data-capacity-person="${esc(p.name)}" aria-pressed="${p.name===s.name}">${esc(p.name)}</button><small class="capacity-identity">${p.home_team==='offline_market'?'线下':p.home_team==='online_private'?'虚拟人':'线上'} · ${esc(p.home_group)} · ${p.business_line==='abroad'?'留学':'语培'}</small></th>${['大学','高中','留学预备'].map(g=>`<td class="${p.home_group===g?'home-contribution':''}">${num(p.destinations?.[g]?.actual)}</td>`).join('')}<td>${num(p.abroad_orders)}</td><td>${num(p.other_orders)}</td><td>${brief(p.orders_metric)}</td><td>${brief(p.cash_metric)}</td><td>${brief(p.heads_metric)}</td></tr>`).join('')||'<tr><td colspan="9">本团队暂无人员</td></tr>'}</tbody></table></div><p class="capacity-hint">浅蓝格为所属业务组。</p></section><section class="capacity-radar">${selected?radar(selected):'<p>请选择有数据的团队</p>'}</section></div>`;}
    draw();
  }
  return {render};
})();
