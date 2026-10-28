"""Private follow requests and lyric artwork, using disposable accounts and invented verses."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import struct
import tempfile
import threading
from urllib.parse import parse_qs,urlparse
from wsgiref.simple_server import make_server
from verify_accounts import OUT,QuietHandler,register
from verify_refinements import TRACK,OTHER
from playwright.sync_api import sync_playwright,expect
from webapp import Application
from serve import LocalServer
from scripts.verification_support import verification_source

VERSES=['Primeiro verso escrito só para teste.','Outro verso inventado para a prévia.','Um terceiro verso também de teste.','Mais uma linha de exemplo original.']
PASSWORD='test-private-owner-123'


def fixture(route):
    url=urlparse(route.request.url);params=parse_qs(url.query)
    if url.path=='/api/search':route.fulfill(json={'results':[OTHER if 'outra' in params.get('q',[''])[0].lower() else TRACK],'provider':'deezer'})
    elif url.path=='/api/track':route.fulfill(json=OTHER if '111111' in url.query else TRACK)
    elif url.path=='/api/lyrics':route.fulfill(json={'status':'not_found'} if params.get('title')==[OTHER['title']] else {'status':'found','text':'\n'.join(VERSES),'source':'LRCLIB'})
    else:route.continue_()


def choose_excerpt(page,scope,lines=(0,1)):
    page.locator(f'[data-choose-excerpt="{scope}"]').click()
    expect(page.locator('#lyric-lines .lyric-line')).to_have_count(4)
    for index in lines:page.locator('#lyric-lines .lyric-line').nth(index).click()
    expect(page.locator('#use-lyric')).to_be_enabled()
    page.locator('#use-lyric').click();expect(page.locator('#lyric-picker')).to_be_hidden()


def main():
    checks=[];errors=[]
    with tempfile.TemporaryDirectory() as directory:
        app=Application(verification_source(Path(directory)/'privacy.sqlite3'),production=False)
        owner=app.db.register(dict(email='private-owner@example.com',username='private_owner',displayName='Dona do perfil',password=PASSWORD))
        other=app.db.register(dict(email='source@example.com',username='public_source',displayName='Outra pessoa',password=PASSWORD))
        app.db.save_entries(owner,dict(version=0,value=[dict(id='owner-post',track=TRACK,text='Um comentário de teste.',visibility='public')]))
        app.db.save_entries(other,dict(version=0,value=[dict(id='source-post',track=TRACK,text='Um registro público de outra pessoa.',visibility='public')]))
        app.db.action(owner,'repost','source-post',True)
        app.db.save_profile(owner,dict(version=0,value=dict(displayName='Dona do perfil',handle='private_owner',favorites=[TRACK],background=TRACK,pinned=['owner-post'])))
        server=make_server('127.0.0.1',0,app,server_class=LocalServer,handler_class=QuietHandler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start();origin=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='chrome',headless=True)
                a=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True);a.route('**/api/**',fixture)
                page=a.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(origin);expect(page.locator('#auth-form')).to_be_visible()
                page.locator('[name="identifier"]').fill('private_owner');page.locator('#auth-form [name="password"]').fill(PASSWORD);page.locator('#auth-submit').click()
                page.locator('[data-page="perfil"]').click();page.locator('#profile-content [data-read="owner-post"]').click();page.locator('#reader [data-edit]').click()
                choose_excerpt(page,'entry')
                expected='\n'.join(VERSES[:2]);expect(page.locator('#entry-excerpt-choice .lyric-text')).to_have_text(expected)
                page.locator('#entry-form [name="reflection"]').fill('Mar');page.locator('#entry-form [type="submit"]').click();page.locator('#edit-publish-only').click()
                expect(page.locator('#reader .lyric-text')).to_have_text(expected)
                page.locator('#reader [data-feature]').click();expect(page.locator('[data-choose-excerpt="weekly"]')).to_be_enabled()
                choose_excerpt(page,'weekly',(2,))
                page.locator('#weekly-form [type="submit"]').click();expect(page.locator('#weekly-dialog')).to_be_hidden()
                page.locator('[data-page="foryou"]').click()
                bars=page.locator('.progress-step').evaluate_all('nodes=>nodes.map(node=>node.getBoundingClientRect().width)');assert max(bars)-min(bars)<1,bars
                assert float(page.locator('.featured-step').evaluate('e=>getComputedStyle(e,"::after").height').replace('px',''))>2
                page.locator('[data-page="perfil"]').click();page.locator('#edit-profile').click()
                page.locator('#profile-form [name="isPrivate"]').check();page.locator('#profile-form [type="submit"]').click();expect(page.locator('#profile-editor')).to_be_hidden(timeout=15000)
                expect(page.locator('#follow-requests-button')).to_be_visible()
                for width in (1440,390):
                    page.set_viewport_size({'width':width,'height':1000});page.wait_for_timeout(150)
                    expect(page.locator('#profile-content .diary-card[data-id="owner-post"] .lyric-text')).to_have_text(expected)
                    assert page.locator('#profile-content .lyric-text').evaluate_all('nodes=>nodes.every(node=>node.scrollHeight<=node.clientHeight+1)')
                    assert page.locator('#profile-content .lyric-art>.album-cover').evaluate_all('nodes=>nodes.every(node=>getComputedStyle(node).opacity==="0.22")')
                    assert page.locator('.favorite-grid .lyric-art,.favorite-grid [data-play]').count()==0
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                    page.screenshot(path=str(OUT/f'private-profile-lyrics-{width}.png'),full_page=True)
                page.set_viewport_size({'width':1440,'height':1000})
                checks.append('chosen verses persist in normal/week posts, render over faded covers without overflow on desktop/mobile, favorites stay unchanged, and weekly progress has equal width with stronger height')
                b=browser.new_context(viewport={'width':390,'height':900});b.route('**/api/**',fixture)
                viewer=b.new_page();viewer.on('pageerror',lambda error:errors.append(str(error)));register(viewer,origin,'private_viewer')
                assert viewer.locator('.story[data-id="owner-post"]').count()==0
                url=origin+'/#pessoa/'+owner;viewer.goto(url);expect(viewer.locator('.locked-profile')).to_be_visible()
                assert viewer.locator('#profile-content .diary-card,.favorite-grid,.profile-weekly').count()==0
                follow=viewer.locator('.profile-follow');expect(follow).to_have_text('Solicitar seguir');follow.click();expect(follow).to_have_text('Solicitado')
                page.locator('#follow-requests-button').click();expect(page.locator('[data-decline-request]')).to_have_count(1)
                page.locator('[data-decline-request]').click();expect(page.locator('#people-content')).to_contain_text('Nenhuma solicitação')
                page.locator('[data-close="people-dialog"]').click()
                viewer.reload();expect(follow).to_have_text('Solicitar seguir');follow.click();expect(follow).to_have_text('Solicitado')
                page.locator('#follow-requests-button').click();page.locator('[data-accept-request]').click();expect(page.locator('#people-content')).to_contain_text('Nenhuma solicitação')
                page.locator('[data-close="people-dialog"]').click()
                viewer.reload();expect(viewer.locator('#profile-content .diary-card')).to_have_count(2)
                expect(follow).to_have_text('Seguindo');expect(viewer.locator('.favorite-grid')).to_be_visible()
                viewer.goto(origin+'/#ressoa/owner-post');expect(viewer.locator('#reader .reader-text')).to_have_text('Mar')
                expect(viewer.locator('#reader .lyric-text')).to_have_text(expected)
                page.locator('.profile-menu summary').click();page.locator('[data-followers-list]').click();page.locator('[data-remove-follower]').click();expect(page.locator('#people-content')).to_contain_text('Nenhum seguidor')
                page.locator('[data-close="people-dialog"]').click();viewer.reload();expect(viewer.locator('#reader-title')).to_have_text('Ressoa indisponível')
                viewer.goto(url);expect(viewer.locator('.locked-profile')).to_be_visible()
                viewer.screenshot(path=str(OUT/'locked-private-profile-mobile.png'),full_page=True)
                checks.append('non-followers cannot see posts/reposts/favorites/week or shared links; requests can be declined/accepted; approval unlocks content; removing follower revokes access')
                page.locator('#edit-profile').click();page.locator('#profile-form [name="isPrivate"]').uncheck();page.locator('#profile-form [type="submit"]').click();expect(page.locator('#profile-editor')).to_be_hidden(timeout=15000)
                viewer.reload();expect(viewer.locator('#profile-content .diary-card')).to_have_count(2);expect(follow).to_have_text('Seguir')
                follow.click();expect(follow).to_have_text('Seguindo')
                page.locator('#profile-content [data-read="owner-post"]').click();page.locator('#reader [data-edit]').click()
                expect(page.locator('#entry-form [name="lyricExcerpt"]')).to_have_value(expected)
                page.locator('#composer-track-picker input').fill('outra');page.locator('#composer-track-picker .catalog-result').click()
                expect(page.locator('#entry-form [name="lyricExcerpt"]')).to_have_value('')
                page.locator('[data-choose-excerpt="entry"]').click();expect(page.locator('#lyric-status')).to_contain_text('Letra não encontrada')
                page.locator('#lyric-selection').fill('um\ndois\ntrês\nquatro');expect(page.locator('#use-lyric')).to_be_disabled()
                page.locator('#lyric-selection').fill('Um trecho informado pela própria pessoa.');expect(page.locator('#use-lyric')).to_be_enabled()
                page.locator('#use-lyric').click();page.locator('[data-close="composer"]').click()
                page.locator('#profile-content [data-read="owner-post"]').click()
                page.evaluate('''()=>{const draw=CanvasRenderingContext2D.prototype.drawImage,fill=CanvasRenderingContext2D.prototype.fillText;window.drawAlphas=[];window.drawnVerses=[];
                    CanvasRenderingContext2D.prototype.drawImage=function(...args){window.drawAlphas.push(this.globalAlpha);return draw.apply(this,args);};
                    CanvasRenderingContext2D.prototype.fillText=function(text,...args){window.drawnVerses.push(text);return fill.call(this,text,...args);};}''')
                page.locator('#reader [data-share]').click();expect(page.locator('#download-share')).to_be_enabled(timeout=20000)
                with page.expect_download() as downloading:page.locator('#download-share').click()
                output=OUT/'lyric-excerpt-share.png';downloading.value.save_as(str(output));assert struct.unpack('>II',output.read_bytes()[16:24])==(1080,1350)
                assert any(abs(alpha-.22)<.001 for alpha in page.evaluate('window.drawAlphas'))
                assert 'Primeiro verso' in ' '.join(page.evaluate('window.drawnVerses'))
                checks.append('public profiles follow immediately, changing music clears a previous excerpt, missing lyrics allow manual selection, limits are enforced, and shared PNG includes faded art with selected verses')
                assert not errors,errors;browser.close()
        finally:
            server.shutdown();server.server_close();worker.join(timeout=5)
    report=dict(result='PASS',checks=checks,javascript_errors=errors,database='temporary',lyrics='invented test verses; no full lyrics saved')
    (OUT/'privacy-lyrics-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
