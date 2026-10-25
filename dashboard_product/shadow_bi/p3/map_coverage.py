"""Bind P0's exact feature/scope inventory to actual P3 native chart IDs."""
import csv,json
from dashboard_product.shadow_bi.p3.catalog import ROOT,AUDIT,VIEWS
B=json.loads((AUDIT/'evidence/bootstrap.json').read_text());by={v.key:v for v in VIEWS}

def keys(i):
 if i==1:return ['overview_market']
 if i<=8:return ['overview_lines','overview_window']
 if i<=10:return ['overview_lines','overview_supplemental','overview_yoy']
 if i<=14 or i==17:return ['overview_targets']
 if i<=16:return ['overview_abroad_targets']
 if i<=20:return ['overview_countries','overview_countries_child']
 if i==21:return ['virtual_market']
 if i<=30:return ['virtual_people']
 if i<=40:return ['online_summary','online_window']
 if i<=49:return ['online_platforms']
 if i==50:return ['online_platform_groups']
 if i==51:return ['online_trend_spend']
 if i==52:return ['online_trend']
 if i==53:return ['online_trend_cash']
 if i in [54,55]:return ['online_latest','online_daily']
 if i<=57:return ['online_daily']
 if i<=60:return ['online_groups']
 if i<=62:return ['online_countries','online_countries_child']
 if i<=67:return ['prep_lines','prep_groups','prep_window']
 if i<=75:return ['prep_people']
 if i<=80:return ['university_lines','university_groups','university_window']
 if i<=88:return ['university_people']
 if i<=96:return ['prep_personal_channels','prep_lines']
 if i<=103:return ['overview_channels','overview_channels_child']
 if i<=111:return ['overview_schools','overview_schools_child']
 if i==112:return ['overview_grades']
 if i<=119:return ['prep_channels','prep_channels_child','prep_personal_channels']
 if i<=127:return ['prep_schools','prep_schools_child']
 if i==128:return ['prep_grades']
 if i<=135:return ['university_channels','university_channels_child']
 if i<=143:return ['university_schools','university_schools_child']
 if i==144:return ['university_grades']
 if i==156:return ['capacity_pending','capacity_pending_count','capacity_markers']
 if i<=158:return ['capacity_month']
 if i<=168:return ['capacity_radar','capacity_radar_values','capacity_annual_targets','capacity_annual_products']
 return ['activities']

def main():
 original=list(csv.DictReader((ROOT/'.local/audits/shadow-bi-p0-20261022/feature-coverage.csv').open(encoding='utf-8-sig')))
 rows=[]
 for old in original:
  i=int(old['id'][1:]);ks=keys(i);views=[by[k] for k in ks];old['p0_recorded_migration_status']=old.pop('new_version_status')
  locations=['/p3/activity/' if v.page=='activities' else f'/superset/dashboard/shadow-bi-p3-{v.page}/ → {v.section} → {v.title}' for v in views]
  proof='evidence/final-api.log；evidence/final-sql-sealed.log；evidence/final-finite.log；evidence/final-controls-complete.log（日志末行指向实际完整API/SQL回执目录）'
  note='已实现并自动核对；待总线程与用户确认'
  if i==20:note+='；P0国家条线原字段只有线上/线下/待确认/合计工单，现金/人头在业务线总览，未伪造国家金额与人数'
  if i==156:note+='；本批待核0，无非空待核UI样本，另保留49条marker诊断'
  rows.append({**old,'new_location':'; '.join(locations),'p3_dataset_keys':';'.join(ks),'p3_dataset_ids':';'.join(str(B['datasets'][k]) for k in ks),'p3_chart_ids':';'.join(str(B['charts'][k]['id']) for k in ks if k in B['charts']),'p3_visible_columns':'; '.join(dict.fromkeys(c for v in views for c in v.columns)),'p3_evidence':proof,'p3_status':note})
 out=ROOT/'docs/shadow-bi-p3-feature-mapping-20261022.csv'
 with out.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 scopes=list(csv.DictReader((ROOT/'.local/audits/shadow-bi-p0-20261022/filter-scopes.csv').open(encoding='utf-8-sig')))
 native={}
 for page,p in B['pages'].items():
  for item in p['filters']:native[page+'/'+item['name']]={'id':item['id'],'chart_ids':item['chartsInScope'],'excluded':item['scope']['excluded'],'cascadeParentIds':item['cascadeParentIds'],'required':item['controlValues']['enableEmptyFilter']}
 targets=[['overview/期间'],['overview/管理单元'],['overview/目标团队'],['overview/个人月份','virtual/个人月份'],[p+'/含删除回收' for p in ['overview','virtual','prep','university','capacity']],[p+'/含死单' for p in ['overview','virtual','prep','university','capacity']],['prep/业务组'],['prep/个人月份','university/个人月份'],['prep/月模式','university/月模式'],['学校表头：工单/现金/工单同比/工单占比/现金占比'],['原生学校→年级下钻；渠道×业务组、学校×年级独立表与服务端分页'],['年级顺序、工单、现金表头'],['capacity/产能月份'],['capacity/线下团队'],['capacity/产品范围'],['/p3/activity/ #search #prev #next'],['/p3/activity/ 临时投入输入与sessionStorage'],['online/线上期间'],['online/业务线'],['online/平台业务线'],['online/平台；平台表搜索'],['平台表工单/工单占比/工单同比/平台表头']]
 mapped=[]
 for old,new in zip(scopes,targets):mapped.append({**old,'p3_controls':new,'native_bindings':{k:native[k] for k in new if k in native},'p3_status':'已映射；见实际API边界与浏览器记录；待用户确认'})
 mapped[2]['p3_note']='原生级联管理单元；非市场总计时只提供全部（原版隐藏控件），不提供对该单元无意义的线上/线下选择。'
 assert len(rows)==181 and len(mapped)==22
 (ROOT/'docs/shadow-bi-p3-filter-scopes-20261022.json').write_text(json.dumps(mapped,ensure_ascii=False,indent=2))
 print('181 features / 22 scopes mapped to actual P3 IDs')
if __name__=='__main__':main()
