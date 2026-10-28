"""Real browser + real account API, using a temporary database and port."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import tempfile
import threading
from wsgiref.simple_server import WSGIRequestHandler, make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.tools'))
from playwright.sync_api import sync_playwright, expect
from webapp import Application
from serve import LocalServer
from scripts.verification_support import verification_source

TRACK = {'catalogId':'deezer:543138072','provider':'deezer','title':'Azul Da Cor Do Mar','artist':'Tim Maia','album':'Tim Maia','year':'1970','duration':204,'artwork':'https://cdn-images.dzcdn.net/images/cover/6fff1800943f08605efa4580b9006da3/500x500-000000-80-0-0.jpg','previewUrl':'','url':'https://www.deezer.com/track/543138072'}
OUT = ROOT / 'verification'
OUT.mkdir(exist_ok=True)


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


def music_fixture(route):
    if '/api/search?' in route.request.url:
        route.fulfill(json={'results': [TRACK], 'provider': 'deezer'})
    elif '/api/lyrics?' in route.request.url:
        route.fulfill(json={'status': 'not_found'})
    elif '/api/track?' in route.request.url:
        route.fulfill(json=TRACK)
    elif '/api/login-artwork' in route.request.url:
        route.fulfill(status=503,json={'error':'Use the bundled fallback in this test.'})
    else:
        route.continue_()


def register(page, origin, username):
    page.goto(origin)
    page.locator('#auth-form').wait_for(state='visible')
    page.locator('[data-auth-mode="register"]').click()
    page.locator('[name="displayName"]').first.fill(username.capitalize())
    page.locator('[name="email"]').fill(username + '@example.com')
    page.locator('[name="username"]').fill(username)
    page.locator('#auth-form [name="password"]').fill('test-browser-password-123')
    page.locator('[name="remember"]').check()
    page.locator('#auth-submit').click()
    expect(page.locator('#app-shell')).to_be_visible()
    expect(page.locator('#auth-screen')).to_be_hidden()


def create_post(page, message, visibility='public', query='Tim Maia'):
    page.locator('[data-page="diario"]').click()
    page.locator('#write-entry').click()
    page.locator('#composer-track-picker input').fill(query)
    page.locator('#composer-track-picker .catalog-result').first.click()
    page.locator('#entry-form [name="reflection"]').fill(message)
    page.locator('#entry-form [name="visibility"]').select_option(visibility)
    page.locator('#entry-form [type="submit"]').click()
    expect(page.locator('#composer')).to_be_hidden()


def main():
    checks, errors = [], []
    with tempfile.TemporaryDirectory() as directory:
        application = Application(verification_source(Path(directory) / 'browser.sqlite3'), production=False)
        server = make_server('127.0.0.1', 0, application, server_class=LocalServer, handler_class=QuietHandler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        origin = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='chrome', headless=True)
                a = browser.new_context(viewport={'width':1440,'height':1000})
                b = browser.new_context(viewport={'width':390,'height':844}, is_mobile=True, has_touch=True)
                for context in (a, b):
                    context.route('**/api/**', music_fixture)
                    context.on('page', lambda page: page.on('pageerror', lambda e: errors.append(str(e))))
                page = a.new_page()
                page.goto(origin)
                page.locator('#auth-form').wait_for(state='visible')
                page.evaluate('document.fonts.ready')
                page.screenshot(path=str(OUT / 'auth-login-desktop.png'), full_page=True)
                assert page.locator('.auth-covers img').count() == 20
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                register(page, origin, 'test_pedro')
                expect(page.locator('#feed-empty')).to_be_visible()
                assert page.locator('.story').count() == 0
                checks.append('login gate and real registration; no fictional people in the authenticated feed')
                create_post(page, 'Meu primeiro comentário público salvo na conta.')
                create_post(page, 'Minha lembrança privada que só eu posso ler.', 'private')
                expect(page.locator('#diary-entries .diary-card')).to_have_count(2)
                page.reload()
                expect(page.locator('#diary-entries .diary-card')).to_have_count(2)
                assert page.evaluate('localStorage.getItem("ressoa.entries")') is None
                assert all(cookie['httpOnly'] for cookie in a.cookies() if cookie['name']=='ressoa_session')
                checks.append('public/private entries persist in the database, cookie session resumes and no account posts enter localStorage')

                phone = b.new_page()
                phone.goto(origin);phone.locator('#auth-form').wait_for(state='visible')
                phone.screenshot(path=str(OUT / 'auth-login-mobile.png'), full_page=True)
                phone.locator('[data-auth-mode="register"]').click()
                phone.screenshot(path=str(OUT / 'auth-register-mobile.png'), full_page=True)
                register(phone, origin, 'test_clara')
                expect(phone.locator('.story')).to_have_count(1)
                expect(phone.locator('.story')).to_contain_text('comentário público')
                assert 'lembrança privada' not in phone.locator('#story-track').inner_text()
                phone.locator('[data-like]').click()
                expect(phone.locator('[data-like]')).to_have_attribute('aria-pressed','true')
                phone.locator('[data-follow]').click()
                expect(phone.locator('[data-follow]')).to_have_attribute('aria-pressed','true')
                phone.locator('[data-repost]').click()
                expect(phone.locator('[data-repost]')).to_have_attribute('aria-pressed','true')
                phone.screenshot(path=str(OUT / 'account-feed-mobile.png'), full_page=True)
                phone.reload();expect(phone.locator('[data-like]')).to_have_attribute('aria-pressed','true')
                checks.append('second real account sees only public posts; follow, like and repost survive reload')

                page.locator('#diary-entries [data-read]').last.click()
                page.locator('[data-interactions]').click()
                expect(page.locator('#people-content')).to_contain_text('Test_clara')
                expect(page.locator('#people-title')).to_have_text('Curtidas e reposts')
                expect(page.locator('#people-content .person-row')).to_have_count(1)
                expect(page.locator('#people-content .interaction-label')).to_have_text('Curtiu · Repostou')
                page.screenshot(path=str(OUT/'interactions-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                page.screenshot(path=str(OUT/'interactions-mobile.png'),full_page=True)
                page.set_viewport_size({'width':1440,'height':1000})
                page.locator('#people-content [data-person]').click()
                expect(page.locator('#profile-content h1')).to_have_text('Test_clara')
                expect(page.locator('#people-dialog')).to_be_hidden()
                page.locator('[data-page="diario"]').click()
                page.keyboard.press('Escape');page.keyboard.press('Escape')
                page.locator('#diary-entries [data-read]').last.click()
                page.locator('#reader [data-edit]').click()
                page.locator('#entry-form [name="reflection"]').fill('Meu comentário público agora está editado.')
                page.locator('#entry-form [type="submit"]').click()
                page.locator('#edit-publish-only').click()
                expect(page.locator('#reader .reader-text')).to_contain_text('agora está editado')
                page.locator('#reader [data-reader-pin]').click()
                page.locator('#reader [data-feature]').click()
                page.locator('#weekly-form [name="reflection"]').fill('Um comentário independente para a semana.')
                page.locator('#weekly-form [type="submit"]').click()
                expect(page.locator('#weekly-dialog')).to_be_hidden()
                expect(page.locator('#define-weekly')).to_be_disabled()
                page.locator('#delete-weekly').click();page.locator('#confirm-action').click()
                expect(page.locator('#delete-weekly')).to_be_hidden()
                expect(page.locator('#define-weekly')).to_be_disabled()
                expect(page.locator('#diary-entries .diary-card')).to_have_count(2)
                checks.append('owner sees real liker; editing/pinning and weekly independent deletion are backed by the server')

                page.locator('[data-page="perfil"]').click();page.locator('#edit-profile').click()
                page.locator('#profile-form [name="bio"]').fill('Meu diário está salvo na conta.')
                page.locator('#profile-form [type="submit"]').click()
                expect(page.locator('#profile-editor')).to_be_hidden()
                expect(page.locator('#profile-content')).to_contain_text('Meu diário está salvo na conta.')
                page.locator('#logout').click();expect(page.locator('#auth-form')).to_be_visible()
                assert page.locator('#app-shell').is_hidden()
                page.locator('#auth-form [name="identifier"]').fill('test_pedro@example.com')
                page.locator('#auth-form [name="password"]').fill('wrong-password')
                page.locator('#auth-submit').click();expect(page.locator('#auth-error')).to_contain_text('incorretos')
                page.locator('#auth-form [name="password"]').fill('test-browser-password-123')
                page.locator('#auth-submit').click();expect(page.locator('#app-shell')).to_be_visible()
                page.locator('[data-page="perfil"]').click()
                expect(page.locator('#profile-content')).to_contain_text('Meu diário está salvo na conta.')
                checks.append('profile survives logout, password errors are shown and email login restores the same account')

                # A failed write must keep the editor and must not invent a saved entry.
                page.locator('[data-page="diario"]').click();page.locator('#write-entry').click()
                page.locator('#composer-track-picker input').fill('Tim Maia');page.locator('#composer-track-picker .catalog-result').first.click()
                page.locator('#entry-form [name="reflection"]').fill('Este comentário fica aberto quando a gravação falha.')
                page.route('**/api/entries',lambda route:route.fulfill(status=503,json={'error':'Falha temporária de gravação.'}))
                page.locator('#entry-form [type="submit"]').click()
                expect(page.locator('#toast')).to_contain_text('Falha temporária')
                expect(page.locator('#composer')).to_be_visible()
                expect(page.locator('#entry-form [type="submit"]')).to_be_enabled()
                page.unroute('**/api/entries')
                page.locator('#entry-form [type="submit"]').click();expect(page.locator('#composer')).to_be_hidden()
                expect(page.locator('#diary-entries .diary-card')).to_have_count(3)
                checks.append('failed database write keeps text/editor; retry saves one entry without a false success')

                # An editor opened before another device writes must conflict safely.
                stale=a.new_page();stale.goto(origin+'/#diario')
                expect(stale.locator('#diary-entries .diary-card')).to_have_count(3)
                stale.locator('#diary-entries [data-read]').last.click();stale.locator('#reader [data-edit]').click()
                stale.locator('#entry-form [name="reflection"]').fill('Alteração feita na aba antiga sem apagar entradas novas.')
                create_post(page,'Uma ressoa criada em outra aba durante a edição.')
                stale.locator('#entry-form [type="submit"]').click()
                stale.locator('#edit-publish-only').click()
                expect(stale.locator('#toast')).to_contain_text('outro dispositivo')
                expect(stale.locator('#composer')).to_be_visible()
                stale.locator('#entry-form [type="submit"]').click()
                stale.locator('#edit-publish-only').click()
                expect(stale.locator('#reader .reader-text')).to_contain_text('aba antiga')
                state=application.db.bootstrap(application.db.login({'identifier':'test_pedro','password':'test-browser-password-123'}))
                assert len(state['entries'])==4
                assert any('criada em outra aba' in post['text'] for post in state['entries'])
                stale.close()
                checks.append('stale tab cannot overwrite newer entries; user can retry while retaining the edited text')

                old_context=browser.new_context(viewport={'width':390,'height':844})
                old_context.route('**/api/**',music_fixture)
                old_data={'ressoa.entries':[{'id':'old-browser-id','track':1,'text':'Um diário antigo preservado com sua visibilidade.','visibility':'private'}],
                          'ressoa.profile':{'displayName':'Nome antigo','handle':'old_user','bio':'Minha bio antes das contas','favorites':[1],'background':1,'pinned':[]}}
                old_context.add_init_script('const old='+json.dumps(old_data)+';for(const [key,value] of Object.entries(old))localStorage.setItem(key,JSON.stringify(value));')
                old_page=old_context.new_page();old_page.on('pageerror',lambda e:errors.append(str(e)))
                register(old_page,origin,'test_legacy')
                old_page.locator('[data-page="diario"]').click();expect(old_page.locator('#legacy-import,#import-local')).to_have_count(0)
                expect(old_page.locator('#diary-entries .diary-card')).to_have_count(0)
                assert old_page.evaluate('JSON.parse(localStorage.getItem("ressoa.entries"))[0].id')=='old-browser-id'
                old_page.reload();expect(old_page.locator('#legacy-import,#import-local')).to_have_count(0)
                old_page.locator('[data-page="perfil"]').click();expect(old_page.locator('#profile-content')).not_to_contain_text('Minha bio antes das contas')
                expect(old_page.locator('#profile-content')).not_to_contain_text('Um diário antigo')
                old_context.close()
                checks.append('local import UI is removed; browser originals are kept and never imported automatically into the account')

                for width in (360,390,640,768,1440):
                    page.set_viewport_size({'width':width,'height':900})
                    for tab in ('foryou','diario','perfil'):
                        page.locator(f'[data-page="{tab}"]').click()
                        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'), (width,tab)
                checks.append('authenticated layout has no horizontal overflow at 360, 390, 640, 768 and 1440px')
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown();server.server_close();worker.join(timeout=5)
    report = dict(result='PASS', checks=checks, javascript_errors=errors, database='temporary; no real user accounts created')
    (OUT / 'accounts-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__ == '__main__':
    main()
