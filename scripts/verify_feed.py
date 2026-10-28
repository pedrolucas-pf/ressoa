"""Daily feed, republishing and centered share artwork with disposable data."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import struct
import tempfile
import threading
from datetime import datetime,timedelta,timezone
from wsgiref.simple_server import make_server
from verify_accounts import OUT,QuietHandler
from verify_refinements import TRACK,fixture,step
from playwright.sync_api import sync_playwright,expect
from webapp import Application
from serve import LocalServer
from scripts.verification_support import verification_source

PASSWORD='test-feed-window-123'
MESSAGE='Meu Ressoa antigo continua guardado.'


def sign_in(page,origin,username):
    page.goto(origin);expect(page.locator('#auth-form')).to_be_visible()
    page.locator('[name="identifier"]').fill(username);page.locator('#auth-form [name="password"]').fill(PASSWORD)
    page.locator('#auth-submit').click();expect(page.locator('#app-shell')).to_be_visible(timeout=15000)


def main():
    errors=[];checks=[]
    with tempfile.TemporaryDirectory() as directory:
        app=Application(verification_source(Path(directory)/'feed.sqlite3'),production=False)
        a=app.db.register(dict(email='feed-a@example.com',username='feed_owner',displayName='Pessoa dona',password=PASSWORD))
        b=app.db.register(dict(email='feed-b@example.com',username='feed_viewer',displayName='Pessoa leitora',password=PASSWORD))
        app.db.save_entries(a,dict(version=0,value=[dict(id='archived',track=TRACK,text=MESSAGE,visibility='public',lyricExcerpt='Verso original de teste.'),dict(id='own-new',track=TRACK,text='Uma nova lembrança.',visibility='public')]))
        app.db.save_entries(b,dict(version=0,value=[dict(id='other-new',track=TRACK,text='Outra lembrança recente.',visibility='public')]))
        weekly=app.db.choose_weekly(a,dict(track=TRACK,text=''))
        weekly_id=app.db.bootstrap(a)['weekly']['postId']
        old=(datetime.now(timezone.utc)-timedelta(hours=25)).isoformat()
        with app.db.transaction() as db:
            db.execute('UPDATE posts SET created_at=?,updated_at=?,feed_published_at=? WHERE id IN (?,?)',(old,old,old,'archived',weekly_id))
        for kind in ('like','repost','saved'):app.db.action(b,kind,'archived',True)
        before=app.db.shared_post(a,'archived')
        server=make_server('127.0.0.1',0,app,server_class=LocalServer,handler_class=QuietHandler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start();origin=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='chrome',headless=True)
                context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True);context.route('**/api/**',fixture)
                context.add_init_script('''
                    window.feedMinuteTasks=[];const nativeInterval=window.setInterval;
                    window.setInterval=function(task,delay,...args){if(delay===60000&&typeof task==='function')window.feedMinuteTasks.push(task);return nativeInterval(task,delay,...args);};
                ''')
                page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)));sign_in(page,origin,'feed_owner')
                expect(page.locator('.story[data-id="archived"]')).to_have_count(0)
                expect(page.locator(f'.story[data-id="{weekly_id}"]')).to_have_count(1)
                refresh=page.locator('#refresh-feed');assert refresh.inner_text()=='' and refresh.locator('svg').count()==1
                step(page,'own-new')
                page.evaluate('''()=>{window.keptStory=document.querySelector('.story[aria-hidden="false"]');window.keptOrder=[...document.querySelectorAll('.story')].map(node=>node.dataset.id);}''')
                refresh.click();expect(refresh).to_be_enabled()
                assert page.evaluate('document.querySelector(".story[aria-hidden=\\"false\\"]")===window.keptStory')
                assert page.evaluate('[...document.querySelectorAll(".story")].map(node=>node.dataset.id)')==page.evaluate('window.keptOrder')
                assert refresh.inner_text()=='' and refresh.locator('svg').count()==1
                checks.append('25-hour posts are absent from feed while the weekly highlight stays; refresh is icon-only and a no-news refresh keeps the exact active DOM node and order')
                page.locator('[data-page="perfil"]').click();expect(page.locator('#profile-content .diary-card')).to_have_count(2)
                expect(page.locator('#profile-content [data-requests-list]')).to_have_count(0)
                page.locator('#profile-content [data-read="archived"]').click();expect(page.locator('#reader .reader-text')).to_have_text(MESSAGE)
                expect(page.locator('#reader [data-republish]')).to_have_count(0)
                page.locator('#reader [data-edit]').click();page.locator('#entry-form [name="reflection"]').fill(MESSAGE+' Novo sentido.')
                page.locator('#entry-form [type="submit"]').click();page.locator('#edit-publish-again').click()
                expect(page.locator('#reader .reader-text')).to_have_text(MESSAGE+' Novo sentido.')
                after=app.db.shared_post(a,'archived')
                assert all(before[key]==after[key] for key in ('id','lyricExcerpt','createdAt','track'))
                assert after['publishedAt']!=before['publishedAt'] and len(app.db.bootstrap(a)['entries'])==2
                social=app.db.bootstrap(b);assert 'archived' not in social['social']['likes'] and 'archived' not in social['social']['reposts'] and 'archived' in social['saved']
                page.keyboard.press('Escape');page.locator('[data-page="foryou"]').click();expect(page.locator('.story[data-id="archived"]')).to_have_count(1)
                other=browser.new_context(viewport={'width':390,'height':900});other.route('**/api/**',fixture)
                viewer=other.new_page();viewer.on('pageerror',lambda error:errors.append(str(error)));sign_in(viewer,origin,'feed_viewer')
                expect(viewer.locator('.story[data-id="archived"]')).to_have_count(1)
                viewer.goto(origin+'/#ressoa/archived');expect(viewer.locator('#reader [data-republish]')).to_have_count(0)
                checks.append('republication is offered only after an edit, renewing the same ID and preserving creation/verses/saves while clearing previous reactions')
                page.locator('[data-page="perfil"]').click();page.locator('#profile-content [data-read="archived"]').click()
                page.evaluate('''()=>{const draw=CanvasRenderingContext2D.prototype.drawImage,fill=CanvasRenderingContext2D.prototype.fillText;window.coverDraws=[];window.commentDraws=[];
                    CanvasRenderingContext2D.prototype.drawImage=function(...args){if(args.length===9)window.coverDraws.push({x:args[5],y:args[6],width:args[7],height:args[8]});return draw.apply(this,args);};
                    CanvasRenderingContext2D.prototype.fillText=function(text,x,y,...args){window.commentDraws.push({text,x,y});return fill.call(this,text,x,y,...args);};}''')
                page.locator('#reader [data-share]').click();expect(page.locator('#download-share')).to_be_enabled(timeout=20000)
                assert page.locator('#copy-share').count()==0;expect(page.locator('#copy-share-link')).to_be_visible()
                draws=page.evaluate('window.coverDraws');cover=draws[0]
                assert cover['width']>=220 and abs(cover['x']+cover['width']/2-245)<1,draws
                comments=[draw for draw in page.evaluate('window.commentDraws') if draw['text'].startswith('“Meu Ressoa')]
                assert comments and comments[0]['y']>cover['y']+cover['height'] and comments[0]['x']==245
                with page.expect_download() as downloading:page.locator('#download-share').click()
                output=OUT/'centered-cover-share.png';downloading.value.save_as(str(output));assert struct.unpack('>II',output.read_bytes()[16:24])==(1080,1350)
                page.keyboard.press('Escape');page.keyboard.press('Escape')
                page.locator('#edit-profile').click();page.locator('#profile-form [name="isPrivate"]').check();page.locator('#profile-form [type="submit"]').click();expect(page.locator('#profile-editor')).to_be_hidden(timeout=15000)
                expect(page.locator('#follow-requests-button')).to_be_visible();expect(page.locator('#profile-content [data-requests-list]')).to_have_count(0)
                page.locator('[data-page="diario"]').click();page.locator('#write-entry').click()
                expect(page.locator('#entry-form [value="public"]')).to_have_text('Seguidores');page.locator('[data-close="composer"]').click()
                page.locator('[data-page="foryou"]').click()
                page.evaluate('''()=>{const original=Date.now;const future=Math.max(...[...document.querySelectorAll('.story')].filter(node=>!node.classList.contains('featured')).map(()=>original()))+25*3600000;
                    Date.now=()=>future;try{window.feedMinuteTasks.forEach(task=>task());}finally{Date.now=original;}}''')
                expect(page.locator('.story:not(.featured)')).to_have_count(0);expect(page.locator('.story.featured')).to_have_count(1)
                page.locator('[data-page="perfil"]').click();expect(page.locator('#profile-content .diary-card')).to_have_count(2)
                checks.append('share image has a larger centered cover with comment below and no Copy text; private visibility says Seguidores; requests stay only in header; minute pruning removes expired ordinary cards without deleting profile history')
                assert not errors,errors;browser.close()
        finally:
            server.shutdown();server.server_close();worker.join(timeout=5)
    report=dict(result='PASS',checks=checks,javascript_errors=errors,database='temporary',sharing='download only; no social message sent')
    (OUT/'feed-lifetime-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
