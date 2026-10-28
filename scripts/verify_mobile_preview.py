"""Capture the current login at mobile size without changing firewall or account data."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import os
import json
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'.tools'))
from playwright.sync_api import sync_playwright
origin=os.getenv('RESSOA_TEST_URL','http://localhost:8000')
(root/'verification').mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(origin)
    page.locator('#auth-form').wait_for(state='visible')
    assert page.locator('#app-shell').is_hidden()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(root/'verification'/'mobile-preview-login.png'),full_page=True)
    assert not errors,errors
    report={'result':'PASS','url':origin,'viewport':'390x844, emulated','javascript_errors':errors,'physical_phone_tested':False,'firewall_changed':False}
    (root/'verification'/'mobile-preview-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    browser.close()
