"""Live music regression on an ephemeral account/database; no lyric text is saved."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import tempfile
import threading
from wsgiref.simple_server import make_server
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'.tools'))
from playwright.sync_api import sync_playwright,expect
from webapp import Application
from serve import LocalServer
from verify_accounts import QuietHandler,create_post

with tempfile.TemporaryDirectory() as directory:
    application=Application(Path(directory)/'media.sqlite3',production=False)
    catalog=json.loads((root/'web'/'spotify-catalog.js').read_text(encoding='utf-8').split('=',1)[1].strip().rstrip(';'))
    track=catalog['tracks'][1]
    track.update(catalogId='spotify:'+track['id'],provider='spotify',artist='Djavan',album='Djavan',duration=296)
    user=application.db.register(dict(email='media-test@example.com',username='media_test',displayName='Teste de áudio',password='media-test-password-123'))
    application.db.save_entries(user,dict(version=0,value=[dict(id='media-post',track=track,text='Uma lembrança para verificar a escuta nesta versão.',visibility='public')]))
    server=make_server('127.0.0.1',0,application,server_class=LocalServer,handler_class=QuietHandler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    origin=f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000})
            media=[];errors=[]
            page.on('response',lambda r:media.append(r.status) if r.request.resource_type=='media' else None)
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(origin);page.locator('#auth-form').wait_for(state='visible')
            page.locator('#auth-form [name="identifier"]').fill('media_test')
            page.locator('#auth-form [name="password"]').fill('media-test-password-123')
            page.locator('#auth-submit').click()
            button=page.locator('.story[aria-hidden="false"] [data-play]')
            button.click();expect(button).to_have_attribute('aria-pressed','true',timeout=30000)
            page.wait_for_timeout(1000);assert any(code in (200,206) for code in media)
            button.click();expect(button).to_have_attribute('aria-pressed','false')
            page.set_viewport_size({'width':390,'height':844})
            button.click();expect(button).to_have_attribute('aria-pressed','true')
            page.screenshot(path=str(root/'verification'/'account-spotify-mobile-live.png'),full_page=True)
            page.locator('[data-page="diario"]').click()
            assert page.locator('#spotify-controller-host iframe').count()==0
            create_post(page,'Uma escuta para guardar os detalhes do dia e os caminhos de volta.',query='Tim Maia Azul da Cor do Mar')
            expect(page.locator('#diary-entries')).to_contain_text('Azul Da Cor Do Mar')
            page.reload();expect(page.locator('#diary-entries')).to_contain_text('Azul Da Cor Do Mar')
            page.locator('[data-page="foryou"]').click()
            index=page.locator('.story').filter(has_text='Azul Da Cor Do Mar').evaluate('(e)=>[...e.parentNode.children].indexOf(e)')
            page.locator('.progress-step').nth(index).click()
            native=page.locator('.story[aria-hidden="false"] [data-play]')
            before=len(media);native.click();expect(native).to_have_attribute('aria-pressed','true',timeout=20000)
            page.wait_for_timeout(1000);assert len(media)>before
            page.locator('.story[aria-hidden="false"] .cover-open').click()
            page.locator('.lyrics-section summary').click()
            page.locator('.lyrics-text').wait_for(timeout=30000)
            length=page.locator('.lyrics-text').evaluate('e=>e.textContent.length')
            assert length>0;page.keyboard.press('Escape')
            assert not errors,errors
            result={'result':'PASS','authenticated':True,'spotify_overlay_desktop_mobile':True,'spotify_destroyed_on_navigation':True,'deezer_search_save_reload_preview':True,'lyrics_received':True,'lyric_character_count':length,'media_statuses':media,'javascript_errors':errors,'database':'temporary'}
            (root/'verification'/'media-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(result,ensure_ascii=False));browser.close()
    finally:
        server.shutdown();server.server_close();worker.join(timeout=5)
