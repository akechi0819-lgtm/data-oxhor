"""Install SQL-native management breakdown and country dimensions."""
from pathlib import Path


def install_dimensions(con):
    """Create dimension result views over the already-installed candidate inputs."""
    con.execute((Path(__file__).parent / "sql/dimensions.sql").read_text(encoding="utf-8"))
