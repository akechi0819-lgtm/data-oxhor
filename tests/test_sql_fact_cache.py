import duckdb
import pytest

from dashboard_product.shadow_bi.sql_warehouse.cache import refresh_fact_cache, reorder_fact_cache


def test_source_traversal_keeps_values_flags_types_and_abroad_order():
    con=duckdb.connect()
    try:
        con.execute('CREATE SCHEMA business; CREATE SCHEMA source')
        con.execute("""CREATE TABLE business.fact_cache AS SELECT * FROM (VALUES
            ('b','training',2.25::DECIMAL(24,2),false,true),
            ('z','abroad',-3.5::DECIMAL(24,2),true,true),
            ('a','training',1.0::DECIMAL(24,2),true,false),
            ('y','abroad',NULL::DECIMAL(24,2),true,true))
            t(fact_id,business_line,value,is_business_fact,is_personal_fact)""")
        con.execute("CREATE TABLE source.training_source_order AS SELECT * FROM (VALUES ('a',1),('b',2)) t(fact_id,source_order)")
        before=con.execute('SELECT * FROM business.fact_cache ORDER BY fact_id').fetchall()
        types=con.execute('DESCRIBE business.fact_cache').fetchall()
        reorder_fact_cache(con)
        assert con.execute('SELECT fact_id FROM business.fact_cache').fetchall()==[('a',),('b',),('z',),('y',)]
        assert con.execute('SELECT * FROM business.fact_cache ORDER BY fact_id').fetchall()==before
        assert con.execute('DESCRIBE business.fact_cache').fetchall()==types
        con.execute("DELETE FROM source.training_source_order WHERE fact_id='b'")
        with pytest.raises(ValueError,match='every training fact'):
            reorder_fact_cache(con)
        assert con.execute('SELECT * FROM business.fact_cache ORDER BY fact_id').fetchall()==before
        assert con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name='ordered_fact_stage'").fetchone()[0]==0
    finally:con.close()


def test_one_fact_cache_keeps_both_qualifications_and_refreshes_from_sql():
    con=duckdb.connect()
    try:
        con.execute('CREATE SCHEMA business; CREATE SCHEMA input; CREATE SCHEMA expenses')
        con.execute("CREATE TABLE expenses.existing_cost AS SELECT 100 AS amount")
        con.execute("""CREATE TABLE input.records AS SELECT * FROM (VALUES
            ('a','training',1.00::DECIMAL(24,2),true,true),('b','training',2.00::DECIMAL(24,2),false,true))
            t(fact_id,business_line,value,eligible,personal)""")
        con.execute('CREATE VIEW business.training_facts AS SELECT fact_id,business_line,value FROM input.records WHERE eligible')
        con.execute('CREATE VIEW business.training_personnel_facts AS SELECT fact_id,business_line,value FROM input.records WHERE personal')
        con.execute("CREATE VIEW business.abroad_facts AS SELECT 'c' fact_id,'abroad' business_line,3.0 AS value,'study_abroad' AS customer_domain")
        refresh_fact_cache(con)
        assert con.execute('SELECT count(*) FROM business.fact_cache').fetchone()[0]==3
        assert con.execute('SELECT count(*) FROM business.training_facts').fetchone()[0]==1
        assert con.execute('SELECT count(*) FROM business.training_personnel_facts').fetchone()[0]==2
        con.execute("UPDATE input.records SET value=10 WHERE fact_id='a'")
        refresh_fact_cache(con)
        assert con.execute("SELECT value FROM business.training_facts WHERE fact_id='a'").fetchone()[0]==10
        assert con.execute('SELECT amount FROM expenses.existing_cost').fetchone()[0]==100
        assert con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='personal_fact_stage'").fetchone()[0]==0
    finally:con.close()
