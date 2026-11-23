"""Save the training Tencent account's dedicated normal login session."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_acquisition.auth.auth_sessions import AuthSessionPaths, write_auth_session

SERVICE = 'tencent_ads_73047077'
ORIGIN = 'https://ad.qq.com'


def save_login(workspace: Path) -> None:
    from playwright.sync_api import sync_playwright

    paths = AuthSessionPaths(workspace, SERVICE)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=False)
        try:
            context = browser.new_context(accept_downloads=True)
            if paths.cookies.is_file():
                context.add_cookies(json.loads(paths.cookies.read_text()))
            if paths.local_storage.is_file():
                storage = json.loads(paths.local_storage.read_text())
                context.add_init_script('if(location.origin==="https://ad.qq.com"){const saved=' + json.dumps(storage) + ';for(const [key,value] of Object.entries(saved))localStorage.setItem(key,value)}')
            page = context.new_page()
            page.goto(ORIGIN + '/atlas/73047077/report/index?tab=account', wait_until='domcontentloaded')
            print('腾讯语培专用窗口正在验证登录；如需登录，请使用可访问 73047077 的已有账号。', flush=True)
            page.wait_for_function('document.body && document.body.innerText.includes("ID:73047077")', timeout=600000)
            cookies = context.cookies([ORIGIN])
            storage = page.evaluate('Object.fromEntries(Object.entries(localStorage))')
            if not cookies or not isinstance(storage, dict):
                raise RuntimeError('tencent_login_session_state_empty_or_invalid')
            write_auth_session(SERVICE, cookies=cookies, local_storage=storage, paths=paths)
        finally:
            browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    save_login(parser.parse_args().workspace)


if __name__ == '__main__':
    main()
