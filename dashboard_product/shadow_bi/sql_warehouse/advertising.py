"""Read warehouse facts/expenses directly with the existing ROI SQL rules."""
from pathlib import Path


def install_advertising(con, *, config_root):
    con.execute('CREATE OR REPLACE VIEW business.expense_details AS SELECT * FROM expenses.expense_rows')
    con.execute('CREATE OR REPLACE VIEW business.expense_source_details AS SELECT * FROM expenses.expense_sources')
    con.execute('''CREATE OR REPLACE VIEW business.expense_rows AS
        SELECT source_key AS source_id,business_line,business_group,platform,start_date,end_date,amount
        FROM expenses.expense_rows''')
    con.execute('''CREATE OR REPLACE VIEW business.expense_sources AS
        SELECT source_key AS source_id,business_line,business_group,platform,grain,
         min(start_date) AS start_date,max(end_date) AS end_date
        FROM expenses.expense_rows GROUP BY ALL''')
    template=(Path(config_root)/'dashboard_product/management/sql/advertising_rollup.sql').read_text()
    substitutions={
        'PERIODS': "SELECT period_id,start_date,through_date,(start_date-INTERVAL '1 year')::DATE,(through_date-INTERVAL '1 year')::DATE FROM business.periods WHERE status<>'future'",
        'BUSINESS_DAILY': 'SELECT event_date,business_line,expense_group,platform,coalesce(orders,0),coalesce(cash,0) FROM business.online_daily',
        'EXPENSE_ROWS': 'SELECT source_id,business_line,business_group,platform,start_date,end_date,amount FROM business.expense_rows',
        'EXPENSE_SOURCES': 'SELECT source_id,business_line,business_group,platform,grain,start_date,end_date FROM business.expense_sources',
    }
    for token,statement in substitutions.items():
        marker='VALUES /* '+token+' */'
        if template.count(marker)!=1:raise ValueError('费用SQL输入合同变化：'+token)
        template=template.replace(marker,statement)
    con.execute('CREATE OR REPLACE VIEW business.advertising_rollup AS '+template)
    pieces=[]
    for number,scope in enumerate(('被动','主动','全部')):
        if scope=='被动':
            pieces.append("SELECT '被动' AS acquisition_scope,* FROM business.advertising_rollup")
            continue
        # All business classification is SQL; only the established fee projection
        # is omitted for active/all training, exactly as the old scope switch.
        body=(Path(config_root)/'dashboard_product/management/sql/advertising_rollup.sql').read_text()
        for token,statement in substitutions.items():
            if token=='BUSINESS_DAILY':
                statement="SELECT event_date,business_line,expense_group,platform,coalesce(orders,0),coalesce(cash,0) FROM business.online_scoped_daily WHERE acquisition_scope='"+scope+"'"
            elif token in ('EXPENSE_ROWS','EXPENSE_SOURCES'):
                statement+=" WHERE business_line='abroad'"
            body=body.replace('VALUES /* '+token+' */',statement)
        name='business._advertising_scope_'+str(number)
        con.execute('CREATE OR REPLACE VIEW '+name+' AS '+body)
        fee_columns=('spend','spend_status','roi','cost_per_order','roi_start_date','roi_through_date','roi_spend','roi_cash','roi_orders')
        replacements=','.join("CASE WHEN business_line='training' THEN NULL ELSE "+c+' END AS '+c for c in fee_columns)
        pieces.append("SELECT '"+scope+"' AS acquisition_scope,* REPLACE ("+replacements+') FROM '+name)
    con.execute('CREATE OR REPLACE VIEW business.scoped_advertising_rollup AS '+' UNION ALL BY NAME '.join(pieces))
    con.execute('''CREATE OR REPLACE VIEW business.scoped_online_daily AS
      WITH days AS (
       SELECT p.period_id,CAST(d AS DATE) AS event_date FROM business.periods p,
        LATERAL generate_series(p.start_date,p.through_date,INTERVAL '1 day') t(d) WHERE p.through_date IS NOT NULL
      ), keys AS (
       SELECT d.*,a.acquisition_scope,l.business_line FROM days d
       CROSS JOIN (VALUES ('被动'),('主动'),('全部')) a(acquisition_scope)
       CROSS JOIN (VALUES ('training'),('abroad')) l(business_line)
      ), daily_business AS (
       SELECT acquisition_scope,event_date,business_line,sum(orders) AS orders,sum(cash) AS cash
       FROM business.online_scoped_daily GROUP BY ALL
      ), active_cash AS (
       SELECT a.acquisition_scope,CAST(f.event_date AS DATE) AS event_date,sum(f.value) AS cash
       FROM business.facts f CROSS JOIN (VALUES ('主动'),('全部')) a(acquisition_scope)
       WHERE f.business_line='training' AND f.team_id='online_platform' AND f.metric='cash'
        AND (a.acquisition_scope='全部' OR f.acquisition_mode=a.acquisition_scope) GROUP BY ALL
      )
      SELECT k.*,coalesce(r.orders,0) AS orders,
       CASE WHEN k.business_line='training' AND k.acquisition_scope<>'被动' THEN coalesce(c.cash,0)
        WHEN k.business_line='abroad' AND NOT(k.event_date BETWEEN clock.abroad_start AND clock.abroad_through) THEN NULL
        ELSE coalesce(r.cash,0) END AS cash,
       old.spend,coalesce(old.spend_status,'missing') AS spend_status,
       CASE WHEN k.business_line='training' AND k.acquisition_scope<>'被动' THEN NULL
        WHEN k.business_line='abroad' AND NOT(k.event_date BETWEEN clock.abroad_start AND clock.abroad_through) THEN NULL ELSE old.roi END AS roi
      FROM keys k LEFT JOIN daily_business r ON r.event_date=k.event_date
       AND r.business_line=k.business_line AND r.acquisition_scope=k.acquisition_scope
      LEFT JOIN business.advertising_rollup old ON old.period_id=k.period_id AND old.event_date=k.event_date
       AND old.business_line=k.business_line AND old.record_type='daily'
      LEFT JOIN active_cash c ON c.acquisition_scope=k.acquisition_scope AND c.event_date=k.event_date
      CROSS JOIN config.clock clock''')
    con.execute('''CREATE OR REPLACE VIEW business.update_dates AS
       SELECT through_date AS training_through,abroad_through,
        (SELECT max(end_date) FROM expenses.expense_rows) AS expense_through
       FROM config.clock''')
