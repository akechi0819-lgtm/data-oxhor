"""SQL classification using the existing fixed alias/key dictionaries."""
from pathlib import Path
from dashboard_product.management.platforms import (
    ABROAD_PAID_CHANNEL_SEPARATORS, ABROAD_PAID_THIRD_CHANNELS,
    _BRANDS, _SOURCE_CATEGORIES, _RECORD_KEYS, _CASH_ENRICHMENT_LABELS,
)
from .relations import load_rows


def install_platforms(con):
    load_rows(con,'config','platform_aliases',[
        {'kind':kind,'platform':platform,'alias':alias.lower()}
        for kind, rows in [('brand',_BRANDS),('category',_SOURCE_CATEGORIES)]
        for platform, aliases in rows for alias in aliases])
    load_rows(con,'config','channel_keys',[
        {'channel_group':group,'key':key} for group,keys in _RECORD_KEYS.items() for key in sorted(keys)])
    load_rows(con,'config','cash_enrichment_labels',[{'label':v} for v in sorted(_CASH_ENRICHMENT_LABELS)])
    load_rows(con,'config','abroad_paid_third_channels',[
        {'label':label,'platform':platform}
        for platform,labels in ABROAD_PAID_THIRD_CHANNELS.items() for label in labels])
    sql=(Path(__file__).parent/'sql/platforms.sql').read_text()
    con.execute(sql.replace('__ABROAD_PAID_CHANNEL_SEPARATORS__', ABROAD_PAID_CHANNEL_SEPARATORS))
