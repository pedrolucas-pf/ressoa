"""Real edit decisions and save controls, with disposable accounts only."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import base64
import tempfile
import threading
from datetime import datetime,timedelta,timezone
from wsgiref.simple_server import make_server
from verify_accounts import OUT,QuietHandler
from verify_refinements import TRACK,fixture
from playwright.sync_api import sync_playwright,expect
from webapp import Application
from serve import LocalServer
from scripts.verification_support import verification_source


def main():
    checks=[];errors=[]
    with tempfile.TemporaryDirectory() as directory:
        app=Application(verification_source(Path(directory)/'editing.sqlite3'),production=False)
        password='test-editing-password-123'
        a=app.db.register(dict(email='editing-a@example.com',username='edit_author',displayName='Ana Teste',password=password))
        b=app.db.register(dict(email='editing-b@example.com',username='edit_viewer',displayName='Beto Teste',password=password))
        app.db.save_entries(a,dict(version=0,value=[dict(id=key,track=TRACK,text='Uma palavra antiga.',visibility=visibility) for key,visibility in [('edited','public'),('private','private'),('untouched','public')]]))
        app.db.choose_weekly(a,dict(track=TRACK,text='Minha semana.'))
        app.db.choose_weekly(b,dict(track=TRACK,text='Outra semana.'))
        weekly_a=app.db.bootstrap(a)['weekly']['postId'];weekly_b=app.db.bootstrap(b)['weekly']['postId']
        old=(datetime.now(timezone.utc)-timedelta(hours=30)).isoformat()
        with app.db.transaction() as db:db.execute('UPDATE posts SET feed_published_at=? WHERE id=?',(old,'edited'))
        for kind in ('like','repost','saved'):
            app.db.action(b,kind,'edited',True);app.db.action(b,kind,'untouched',True)
        server=make_server('127.0.0.1',0,app,server_class=LocalServer,handler_class=QuietHandler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start();origin=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='chrome',headless=True)
                context=browser.new_context(viewport={'width':1440,'height':1000});context.route('**/api/**',fixture)
                page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                save_requests=[]
                page.on('request',lambda request:save_requests.append(request.post_data_json) if request.url.endswith('/api/action') and request.post_data_json.get('kind')=='saved' else None)
                page.goto(origin);page.locator('[name="identifier"]').fill('edit_author');page.locator('#auth-form [name="password"]').fill(password);page.locator('#auth-submit').click()
                expect(page.locator('#app-shell')).to_be_visible(timeout=15000)
                page.locator('[data-page="perfil"]').click()
                expect(page.locator('.profile-shortcut .profile-avatar')).to_have_text('AN')
                page.locator('#edit-profile').click()
                picture=page.evaluate('''()=>{const canvas=document.createElement('canvas');canvas.width=canvas.height=24;const ctx=canvas.getContext('2d');ctx.fillStyle='#999';ctx.fillRect(0,0,24,24);ctx.fillStyle='#ddd';ctx.fillRect(4,4,16,16);return canvas.toDataURL('image/png');}''')
                page.locator('#profile-photo').set_input_files(dict(name='test-avatar.png',mimeType='image/png',buffer=base64.b64decode(picture.split(',')[1])))
                expect(page.locator('#photo-preview img')).to_be_visible()
                page.locator('#profile-form [type="submit"]').click();expect(page.locator('#profile-editor')).to_be_hidden()
                own_photo=app.db.bootstrap(a)['profile']['photo']
                expect(page.locator('.profile-shortcut img')).to_have_attribute('src',own_photo)
                page.wait_for_function('()=>{const img=document.querySelector(".profile-shortcut img");return img?.complete&&img.naturalWidth>0;}')
                expect(page.locator('#profile-content h1')).to_have_text('Ana Teste')
                expect(page.locator('.profile-handle')).to_have_text('@edit_author')
                expect(page.locator('.profile-privacy')).to_have_count(0)
                expect(page.locator('.weekly-feature .author')).to_contain_text('@edit_author')
                own_menu=page.locator('.weekly-menu');own_menu.locator('summary').click();own_menu.locator('[data-read]').click()
                expect(page.locator('#reader')).to_be_visible();expect(own_menu.locator('.weekly-menu-panel')).to_be_hidden()
                page.locator('#reader [data-save]').click();expect(page.locator('#reader [data-save]')).to_have_attribute('aria-pressed','true')
                assert weekly_a in app.db.bootstrap(a)['saved'] and len(save_requests)==1
                page.keyboard.press('Escape');expect(own_menu.locator('summary')).to_be_focused()
                own_menu.locator('summary').click();own_menu.locator('[data-share]').click();expect(page.locator('#share-dialog')).to_be_visible()
                page.locator('[data-close="share-dialog"]').click();expect(own_menu.locator('summary')).to_be_focused()
                own_menu.locator('summary').click();page.locator('#profile-content h1').click();expect(own_menu.locator('.weekly-menu-panel')).to_be_hidden()
                page.locator('#profile-content [data-read="edited"]').click()
                expect(page.locator('#reader .author')).to_contain_text('@edit_author')
                page.locator('#reader [data-save]').click();expect(page.locator('#reader [data-save]')).to_have_attribute('aria-pressed','true')
                assert 'edited' in app.db.bootstrap(a)['saved'] and len(save_requests)==2
                page.locator('#reader [data-edit]').click();page.locator('#entry-form [name="reflection"]').fill('Novo sentimento.')
                page.locator('#entry-form [type="submit"]').click();expect(page.locator('#edit-publish-dialog')).to_be_visible()
                page.screenshot(path=str(OUT/'edit-publication-desktop.png'))
                page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(OUT/'edit-publication-mobile.png'))
                assert page.locator('#edit-publish-dialog').evaluate('element=>element.scrollWidth<=element.clientWidth')
                page.set_viewport_size({'width':1440,'height':1000})
                page.keyboard.press('Escape');expect(page.locator('#edit-publish-dialog')).to_be_hidden()
                expect(page.locator('#entry-form [name="reflection"]')).to_have_value('Novo sentimento.')
                assert app.db.shared_post(a,'edited')['text']=='Uma palavra antiga.'
                assert 'edited' in app.db.bootstrap(b)['social']['likes']
                page.locator('#entry-form [type="submit"]').click();page.locator('#edit-publish-only').click()
                expect(page.locator('#reader .reader-text')).to_have_text('Novo sentimento.')
                post=app.db.shared_post(a,'edited');assert post['publishedAt']==old
                state=app.db.bootstrap(b)
                for key in ('likes','reposts'):assert 'edited' not in state['social'][key] and 'untouched' in state['social'][key]
                assert 'edited' in state['saved'];assert app.db.interactions(a,'edited')==[]
                checks.append('cancel preserves the draft and existing reactions; save-only clears likes/reposts for the edited post and keeps saves and its original feed window')

                app.db.action(b,'like','edited',True);app.db.action(b,'repost','edited',True)
                page.locator('#reader [data-edit]').click();page.locator('#entry-form [type="submit"]').click()
                expect(page.locator('#reader')).to_be_visible();expect(page.locator('#edit-publish-dialog')).to_be_hidden()
                assert 'edited' in app.db.bootstrap(b)['social']['likes']
                page.locator('#reader [data-edit]').click();page.locator('#entry-form [name="reflection"]').fill('Outro sentimento.')
                page.locator('#entry-form [type="submit"]').click();page.locator('#edit-publish-again').click()
                expect(page.locator('#reader .reader-text')).to_have_text('Outro sentimento.')
                assert app.db.shared_post(a,'edited')['publishedAt']>old and app.db.shared_post(a,'edited')['createdAt']==post['createdAt']
                assert len(app.db.bootstrap(a)['entries'])==3 and 'edited' not in app.db.bootstrap(b)['social']['reposts']
                page.keyboard.press('Escape');page.locator('[data-page="foryou"]').click()
                expect(page.locator('.story[data-id="edited"]')).to_have_count(1)
                assert 'c0-1.7' in page.locator('#refresh-feed path').get_attribute('d')
                page.locator('#refresh-feed').screenshot(path=str(OUT/'refresh-spiral.png'))
                checks.append('unchanged save keeps reactions without prompting; save-and-republish renews the same post in For you without creating duplicates')

                page.locator('[data-page="diario"]').click();page.locator('#diary-entries [data-read="private"]').click()
                page.locator('#reader [data-save]').click();expect(page.locator('#reader [data-save]')).to_have_attribute('aria-pressed','true')
                page.locator('#reader [data-edit]').click();page.locator('#entry-form [name="reflection"]').fill('Meu segredo editado.')
                page.locator('#entry-form [type="submit"]').click();expect(page.locator('#reader .reader-text')).to_have_text('Meu segredo editado.')
                expect(page.locator('#edit-publish-dialog')).to_be_hidden();assert app.db.shared_post(a,'private')['visibility']=='private'
                page.keyboard.press('Escape');page.goto(origin+'/#pessoa/'+b)
                expect(page.locator('#profile-content h1')).to_have_text('Beto Teste');expect(page.locator('.profile-handle')).to_have_text('@edit_viewer')
                expect(page.locator('.profile-shortcut img')).to_have_attribute('src',own_photo)
                page.locator('.weekly-feature [data-save]').click();expect(page.locator('.weekly-feature [data-save]')).to_have_attribute('aria-pressed','true')
                assert weekly_b in app.db.bootstrap(a)['saved']
                page.locator('.weekly-title-open').click();expect(page.locator('#reader [data-save]')).to_have_attribute('aria-pressed','true')
                expect(page.locator('#reader .author')).to_contain_text('@edit_viewer')
                page.locator('#reader [data-save]').click();expect(page.locator('#reader [data-save]')).to_have_attribute('aria-pressed','false')
                page.keyboard.press('Escape');expect(page.locator('.weekly-feature [data-save]')).to_have_attribute('aria-pressed','false')
                checks.append('private edits stay private without republish prompts; reader and own/visited weekly bookmarks persist and stay synchronized with one request per click')
                page.reload();expect(page.locator('#profile-content h1')).to_have_text('Beto Teste');expect(page.locator('.weekly-feature [data-save]')).to_have_attribute('aria-pressed','false')
                expect(page.locator('.profile-shortcut img')).to_have_attribute('src',own_photo)
                for width in (1440,390,360):
                    page.set_viewport_size({'width':width,'height':900});page.wait_for_timeout(100)
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                page.screenshot(path=str(OUT/'editing-profile-mobile.png'))
                checks.append('name/handle positions, @authors, spiral refresh and bookmark layouts checked on desktop and mobile')
                page.goto(origin+'/#perfil');expect(page.locator('#profile-content h1')).to_have_text('Ana Teste')
                own_menu.locator('summary').click();own_menu.locator('[data-delete-weekly]').click();expect(page.locator('#confirm-dialog')).to_be_visible()
                page.locator('[data-close="confirm-dialog"]').click();expect(page.locator('.weekly-feature')).to_be_visible()
                own_menu.locator('summary').click();own_menu.locator('[data-delete-weekly]').click();page.locator('#confirm-action').click()
                expect(page.locator('.weekly-feature')).to_have_count(0)
                assert app.db.bootstrap(a)['weekly']['deletedAt']
                page.locator('[data-page="diario"]').click();expect(page.locator('#define-weekly')).to_be_disabled()
                checks.append('own weekly menu opens/reads/shares/deletes, closes on Escape/outside/action with focus restored, and deleting keeps the weekly lock')
                assert not errors,errors
                browser.close()
        finally:
            server.shutdown();server.server_close();worker.join(timeout=5)
    report=dict(result='PASS',checks=checks,javascript_errors=errors,real_accounts_changed=False)
    (OUT/'editing-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
