"""Tencent Docs export downloader."""

from data_acquisition.connectors.tencent_docs.downloader import (
    DownloadReceipt,
    TencentDocsDownloadError,
    TencentDocsExportConfig,
    download_tencent_doc_xlsx,
)

__all__ = [
    "DownloadReceipt",
    "TencentDocsDownloadError",
    "TencentDocsExportConfig",
    "download_tencent_doc_xlsx",
]
