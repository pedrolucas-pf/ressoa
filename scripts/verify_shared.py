"""Disposable browser checks for shared links, optional comments and cover players."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import tempfile
import threading
from urllib.parse import urlparse
from wsgiref.simple_server import make_server
from verify_accounts import OUT,QuietHandler,create_post
from playwright.sync_api import sync_playwright,expect
from verify_refinements import TRACK
from scripts.verification_support import verification_source
from webapp import Application
from serve import LocalServer

SONG=dict(TRACK,previewUrl='https://cdnt-preview.dzcdn.net/ressoa-disposable-preview.mp3')
FULL='Uma lembrança inteira para abrir depois de entrar na conta. '*20
PASSWORD='test-shared-password-123'


def fixture(route):
    path=urlparse(route.request.url).path
    if path=='/api/search':route.fulfill(json={'results':[SONG],'provider':'deezer'})
    elif path=='/api/track':route.fulfill(json=SONG)
    elif path=='/api/lyrics':route.fulfill(json={'status':'not_found'})
    else:route.continue_()


def login(page,username):
    page.locator('[name="identifier"]').fill(username)
    page.locator('#auth-form [name="password"]').fill(PASSWORD)
    page.locator('#auth-submit').click()
    expect(page.locator('#app-shell')).to_be_visible(timeout=15000)


def main():
    errors=[];checks=[]
    with tempfile.TemporaryDirectory() as directory:
        app=Application(verification_source(Path(directory)/'shared.sqlite3'),production=False)
        owner=app.db.register(dict(email='owner@example.com',username='shared_owner',displayName='Autora original',password=PASSWORD))
        posts=[dict(id=f'older-{i:03}',track=SONG,text=FULL if i==0 else f'Lembrança {i}',visibility='public') for i in range(130)]
        posts.append(dict(id='private-link',track=SONG,text='Privado',visibility='private'))
        app.db.save_entries(owner,dict(version=0,value=posts))
        app.db.save_profile(owner,dict(version=0,value=dict(displayName='Autora original',handle='shared_owner',favorites=[SONG],pinned=[])))
        server=make_server('127.0.0.1',0,app,server_class=LocalServer,handler_class=QuietHandler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        origin=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='chrome',headless=True)
                context=browser.new_context(viewport={'width':1440,'height':1000})
                context.route('**/api/**',fixture)
                # Simulate media locally: exercise player events/state without fetching audio.
                context.add_init_script('''
                    let playing=null;
                    Object.defineProperty(HTMLMediaElement.prototype,'paused',{get(){return playing!==this;}});
                    HTMLMediaElement.prototype.play=function(){if(playing&&playing!==this)playing.pause();playing=this;window.testAudio=this;this.dispatchEvent(new Event('play'));return Promise.resolve();};
                    HTMLMediaElement.prototype.pause=function(){if(playing===this)playing=null;this.dispatchEvent(new Event('pause'));};
                ''')
                page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(origin+'/#ressoa/older-000');expect(page.locator('#auth-form')).to_be_visible()
                assert page.locator('#reader').is_hidden() and page.locator('#app-shell').is_hidden()
                page.locator('[data-auth-mode="register"]').click()
                page.locator('#auth-form [name="displayName"]').fill('Leitora de teste');page.locator('[name="email"]').fill('viewer@example.com')
                page.locator('[name="username"]').fill('shared_viewer');page.locator('#auth-form [name="password"]').fill(PASSWORD)
                page.locator('#auth-submit').click()
                expect(page.locator('#reader .reader-text')).to_have_text(FULL,timeout=15000)
                assert page.locator('.story[data-id="older-000"]').count()==0
                assert page.locator('#reader [data-edit]').count()==0
                page.screenshot(path=str(OUT/'shared-link-after-signup.png'),full_page=True)
                checks.append('anonymous shared link survives signup and loads an older Ressoa outside the feed without adding it to the feed')
                page.keyboard.press('Escape')
                create_post(page,'Dor');expect(page.locator('#diary-entries .reflection')).to_have_text('Dor')
                page.locator('#diary-entries [data-read]').click();page.locator('#reader [data-edit]').click()
                page.locator('#entry-form [name="reflection"]').fill('   ')
                page.locator('#entry-form [type="submit"]').click();page.locator('#edit-publish-only').click()
                expect(page.locator('#reader .reader-text')).to_be_hidden();page.keyboard.press('Escape')
                expect(page.locator('#diary-entries .reflection')).to_have_text('')
                page.locator('#define-weekly').click();page.locator('#weekly-track-picker input').fill('Tim Maia')
                page.locator('#weekly-track-picker .catalog-result').first.click()
                page.locator('#weekly-form [type="submit"]').click();expect(page.locator('#weekly-dialog')).to_be_hidden()
                expect(page.locator('#define-weekly')).to_be_disabled()
                card=page.locator('#diary-entries .cover-play');card.click();expect(card).to_have_attribute('aria-pressed','true')
                assert page.locator('#reader').is_hidden() and page.evaluate('window.testAudio.volume')==.5
                weekly=page.locator('#weekly-selection .cover-play');weekly.click()
                expect(weekly).to_have_attribute('aria-pressed','true');expect(card).to_have_attribute('aria-pressed','false')
                weekly.click();expect(weekly).to_have_attribute('aria-pressed','false')
                page.locator('[data-page="perfil"]').click();expect(page.locator('.weekly-reflection')).to_have_text('...')
                assert page.locator('#profile-content .cover-play').count()==2
                for width in (1440,390):
                    page.set_viewport_size({'width':width,'height':1000});page.wait_for_timeout(100)
                    for selector in ('#profile-content .diary-card','#profile-content .weekly-feature'):
                        container=page.locator(selector);button=container.locator('.cover-play');image=container.locator('.album-cover')
                        b=button.bounding_box();c=image.bounding_box()
                        assert c['x']<=b['x'] and c['y']<=b['y'] and b['x']+b['width']<=c['x']+c['width'] and b['y']+b['height']<=c['y']+c['height'],(width,selector,b,c)
                        button.click();expect(button).to_have_attribute('aria-pressed','true');button.click();expect(button).to_have_attribute('aria-pressed','false')
                    page.screenshot(path=str(OUT/f'cover-players-profile-{width}.png'),full_page=True)
                page.locator('#profile-content .diary-card-open').click();reader=page.locator('#reader .cover-play')
                reader.click();expect(reader).to_have_attribute('aria-pressed','true');page.keyboard.press('Escape')
                checks.append('comments can be removed by editing; week saves without text and locks; diary/profile/weekly/reader cover plays toggle and stop each other at 50% volume on desktop/mobile')
                page.goto(origin+'/#ressoa/older-000');expect(page.locator('#reader .reader-text')).to_have_text(FULL)
                context.clear_cookies();page.evaluate("window.dispatchEvent(new Event('sessionexpired'))")
                expect(page.locator('#auth-form')).to_be_visible();assert page.url.endswith('#ressoa/older-000')
                login(page,'shared_viewer');expect(page.locator('#reader .reader-text')).to_have_text(FULL)
                page.goto(origin+'/#ressoa/private-link');expect(page.locator('#reader-title')).to_have_text('Ressoa indisponível')
                assert 'Privado' not in page.locator('#reader-content').inner_text()
                page.goto(origin+'/#ressoa/missing-link');expect(page.locator('#reader-title')).to_have_text('Ressoa indisponível')
                checks.append('existing sessions and re-login resume the selected post; private/deleted links show an unavailable state')
                page.keyboard.press('Escape');page.locator('[data-page="diario"]').click()
                before=set(page.locator('#diary-entries .diary-card').evaluate_all('cards=>cards.map(card=>card.dataset.id)'))
                create_post(page,'')
                after=set(page.locator('#diary-entries .diary-card').evaluate_all('cards=>cards.map(card=>card.dataset.id)'))
                assert len(after-before)==1;identifier=(after-before).pop()
                page.locator(f'#diary-entries [data-read="{identifier}"]').click()
                expect(page.locator('#reader .reader-text')).to_be_hidden()
                page.locator('#reader [data-edit]').click();page.locator('[data-choose-excerpt="entry"]').click()
                verse='Um verso inventado para guardar sem comentário.'
                page.locator('#lyric-selection').fill(verse);page.locator('#use-lyric').click()
                page.locator('#entry-form [type="submit"]').click();page.locator('#edit-publish-only').click()
                expect(page.locator('#reader .lyric-text')).to_have_text(verse);expect(page.locator('#reader .reader-text')).to_be_hidden()
                page.goto(origin+'/#ressoa/'+identifier)
                expect(page.locator('#reader .lyric-text')).to_have_text(verse);expect(page.locator('#reader .reader-text')).to_be_hidden()
                page.locator('#reader [data-share]').click();expect(page.locator('#download-share')).to_be_enabled(timeout=20000)
                page.locator('[data-close="share-dialog"]').click()
                for width in (1440,390):
                    page.set_viewport_size({'width':width,'height':1000});page.wait_for_timeout(100)
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                    page.screenshot(path=str(OUT/f'optional-comment-reader-{width}.png'))
                checks.append('new posts accept no comment; lyrics-only art persists after reload and can be shared without empty quotation marks, on desktop/mobile')
                page.keyboard.press('Escape');page.locator('[data-page="perfil"]').click()
                expect(page.locator('#profile-content h1')).to_have_text('Leitora de teste')
                expect(page.locator('.profile-handle')).to_have_text('@shared_viewer')
                expect(page.locator(f'#profile-content [data-id="{identifier}"] .reflection')).to_have_text('...')
                expect(page.locator('.weekly-reflection')).to_have_text('...')
                page.locator('[data-page="foryou"]').click()
                story=page.locator(f'.story[data-id="{identifier}"]')
                expect(story.locator('.reflection')).to_have_text('...')
                assert story.locator('.reflection').evaluate('element=>getComputedStyle(element,"::before").content')=='none'
                assert story.locator('.reflection-wrap').evaluate('element=>getComputedStyle(element,"::before").content') in ('none','normal')
                assert 'vinyl-ambience.jpg' in page.locator('#for-you').evaluate('element=>getComputedStyle(element,"::before").backgroundImage')
                assert page.locator('#for-you').evaluate('element=>getComputedStyle(element,"::before").position')=='fixed'
                assert 'gradient' in page.locator('#for-you').evaluate('element=>getComputedStyle(element,"::before").maskImage')
                background=context.request.get(origin+'/assets/vinyl-ambience.jpg');assert background.status==200 and background.headers['content-type'].startswith('image/jpeg')
                expect(page.locator('.main-nav')).to_have_text('For you Meus sons',use_inner_text=True)
                expect(page.locator('.main-nav [data-page="perfil"]')).to_have_count(0)
                for width in (1440,1150,768,640,390,360,320):
                    page.set_viewport_size({'width':width,'height':1000});page.wait_for_timeout(100)
                    controls=page.locator('.header-controls')
                    assert controls.locator('.main-nav a').evaluate_all('links=>links.every(link=>{const range=document.createRange();range.selectNodeContents(link);return range.getClientRects().length===1;})')
                    assert controls.evaluate('root=>{const nodes=[root.querySelector("[data-page=foryou]"),root.querySelector("[data-page=diario]"),root.querySelector("#people-search"),root.querySelector("#follow-requests-button"),root.querySelector("[data-page=perfil]")];const boxes=nodes.map(node=>node.getBoundingClientRect());return boxes.every((box,index)=>index===0||box.x>=boxes[index-1].right-1);}')
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                    if width in (1440,390):page.screenshot(path=str(OUT/f'feed-vinyl-header-{width}.png'))
                with app.db.connect() as db:assert db.execute('SELECT text FROM posts WHERE id=?',(identifier,)).fetchone()[0]==''
                checks.append('empty comments display three dots only in feed/profile; profile restores name above @handle; header keeps For you, Meus sons, search, requests and profile in that order at 320–1440px')
                other=browser.new_context(viewport={'width':390,'height':1000});other.route('**/api/**',fixture)
                signed=other.new_page();signed.on('pageerror',lambda error:errors.append(str(error)))
                signed.goto(origin+'/#ressoa/older-000');expect(signed.locator('#auth-form')).to_be_visible()
                signed.locator('[name="identifier"]').fill('shared_owner');signed.locator('#auth-form [name="password"]').fill('wrong-password')
                signed.locator('#auth-submit').click();expect(signed.locator('#auth-error')).to_contain_text('senha',timeout=15000)
                assert signed.url.endswith('#ressoa/older-000')
                login(signed,'shared_owner');expect(signed.locator('#reader .reader-text')).to_have_text(FULL)
                signed.keyboard.press('Escape');signed.locator('[data-page="perfil"]').click()
                expect(signed.locator('.favorite-grid')).to_be_visible();assert signed.locator('.favorite-grid .cover-play').count()==0
                assert not errors,errors
                browser.close()
        finally:
            server.shutdown();server.server_close();worker.join(timeout=5)
    report=dict(result='PASS',checks=checks,javascript_errors=errors,database='temporary',audio='simulated; no audio files fetched')
    (OUT/'shared-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
