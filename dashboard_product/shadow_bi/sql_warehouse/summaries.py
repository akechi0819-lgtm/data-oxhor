from pathlib import Path


def install_summaries(con):
    con.execute((Path(__file__).parent/'sql/summaries.sql').read_text())
