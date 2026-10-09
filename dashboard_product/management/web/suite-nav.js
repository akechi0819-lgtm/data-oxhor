"use strict";
(() => {
  function mount() {
    if(document.getElementById('suite-navigation'))return;
    const page=document.body.dataset.board || document.body.dataset.page || 'overview';
    const routes=[['overview','市场总览','./index.html#overview'],['virtual','线上虚拟人','./index.html?unit=virtual#overview'],['online','线上平台','./online.html'],['prep_high','留学预备＋高中','./prep_high.html'],['university','大学','./university.html'],['capacity','人员产能','./index.html#capacity'],['activities','市场活动','./index.html#activities']];
    const header=document.createElement('header');header.id='suite-navigation';
    header.innerHTML='<a class="suite-brand" href="./index.html#overview">经营看板</a><nav aria-label="全局导航">'+routes.map(([key,label,url])=>`<a id="suite-${key}" data-route="${key}" href="${url}">${label}</a>`).join('')+'</nav>';
    document.body.prepend(header);
    const old=document.querySelector('.board-topbar');
    if(old){const filter=old.querySelector('.period-filter');if(filter)document.querySelector('.board-heading').append(filter);old.remove();}
    if(page==='online')document.body.classList.add('suite-online');
    function active(){let key=page==='overview'?(location.hash.slice(1)||'overview'):page;if(key==='overview'&&(document.body.dataset.unit||new URLSearchParams(location.search).get('unit'))==='virtual')key='virtual';header.querySelectorAll('[data-route]').forEach(a=>{a.classList.toggle('active',a.dataset.route===key);if(a.dataset.route===key)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});}
    active();window.addEventListener('hashchange',active);window.addEventListener('management-unit-change',active);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})();
