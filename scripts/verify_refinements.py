"""UI acceptance checks for profile/feed/login/share/music refinements."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import io
import json
import struct
import tempfile
import threading
from urllib.parse import parse_qs,urlparse
from wsgiref.simple_server import make_server
from verify_accounts import ROOT,OUT,QuietHandler
from webapp import Application
from serve import LocalServer
from playwright.sync_api import sync_playwright,expect
from scripts.verification_support import verification_source

TRACK=dict(catalogId='deezer:543138072',provider='deezer',title='Azul Da Cor Do Mar',artist='Tim Maia',album='Tim Maia 1970',year='1970',duration=198,artwork='https://cdn-images.dzcdn.net/images/cover/6fff1800943f08605efa4580b9006da3/500x500-000000-80-0-0.jpg',previewUrl='',releaseDate='1970-01-05',trackReleaseDate='2018-09-28',contributors=['Tim Maia'],bpm=126.05,explicit=False)
OTHER=dict(TRACK,catalogId='deezer:111111',title='Outra favorita',artist='Artista de teste',album='Um álbum escolhido pela busca')
LONG=('Uma música pode guardar uma lembrança inteira. ' * 50).strip()


def fixture(route):
    url=urlparse(route.request.url)
    if url.path=='/api/search':route.fulfill(json={'results':[OTHER if 'outra' in parse_qs(url.query).get('q',[''])[0].lower() else TRACK],'provider':'deezer'})
    elif url.path=='/api/track':route.fulfill(json=OTHER if '111111' in url.query else TRACK)
    elif url.path=='/api/lyrics':route.fulfill(json={'status':'not_found'})
    elif url.path=='/api/login-artwork':route.fulfill(status=503,json={'error':'Offline fallback test'})
    else:route.continue_()


def step(page,post_id):
    index=page.locator(f'.story[data-id="{post_id}"]').evaluate('e=>[...e.parentNode.children].indexOf(e)')
    page.locator('.progress-step').nth(index).click()


def main():
    checks=[];errors=[]
    with tempfile.TemporaryDirectory() as directory:
        app=Application(verification_source(Path(directory)/'ux.sqlite3'),production=False)
        user=app.db.register(dict(email='ux@example.com',username='ux_person',displayName='Pessoa de teste',password='test-ux-password-123'))
        entries=[dict(id='short',track=TRACK,text='Essa música me faz lembrar de casa.',visibility='public'),dict(id='long',track=TRACK,text=LONG,visibility='public'),dict(id='other',track=OTHER,text='Mais uma lembrança guardada.',visibility='public')]
        app.db.save_entries(user,dict(version=0,value=entries))
        app.db.choose_weekly(user,dict(track=TRACK,text=LONG,visibility='private'))
        favorites=[TRACK,*[dict(TRACK,catalogId=f'deezer:{identifier}',title=f'Favorita de teste {index}') for index,identifier in enumerate((222222,333333,444444,555555,666666),2)]]
        app.db.save_profile(user,dict(version=0,value=dict(displayName='Pessoa de teste',handle='ux_person',favorites=favorites)))
        server=make_server('127.0.0.1',0,app,server_class=LocalServer,handler_class=QuietHandler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        origin=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='chrome',headless=True)
                context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
                context.route('**/api/**',fixture)
                context.add_init_script("localStorage.setItem('ressoa.theme',JSON.stringify('light'))")
                page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                share_requests=[];page.on('request',lambda request:share_requests.append(request.url) if request.url.endswith('/api/share') else None)
                page.goto(origin);page.locator('#auth-form').wait_for(state='visible');page.evaluate('document.fonts.ready')
                expect(page.locator('.auth-intro h1')).to_have_text('Escreva o que pensa, sente, o que quiser.')
                assert page.locator('html').get_attribute('data-theme')=='dark'
                assert page.locator('#auth-theme,#theme-toggle').count()==0
                assert 'Hanken' in page.locator('.brand').first.evaluate('e=>getComputedStyle(e).fontFamily')
                expect(page.locator('.auth-eyebrow')).to_have_count(0)
                expect(page.locator('.auth-covers img')).to_have_count(20)
                covers=page.locator('.auth-covers img').evaluate_all('images=>images.map(img=>img.src)')
                assert len(covers)==len(set(covers))==20
                before={key:page.locator(selector).bounding_box() for key,selector in [('headline','.auth-intro'),('wall','.auth-covers'),('panel','.auth-panel'),('header','.auth-header')]}
                page.screenshot(path=str(OUT/'refined-login-desktop.png'),full_page=True)
                page.locator('[data-auth-mode="register"]').click()
                page.wait_for_function('document.querySelector("#auth-form").getAnimations().every(animation=>animation.playState==="finished")')
                after={key:page.locator(selector).bounding_box() for key,selector in [('headline','.auth-intro'),('wall','.auth-covers'),('panel','.auth-panel'),('header','.auth-header')]}
                for key in ('headline','wall','header'):
                    assert all(abs(before[key][value]-after[key][value])<1 for value in ('x','y','width','height')),(key,before[key],after[key])
                assert abs(before['panel']['y']-after['panel']['y'])<1 and after['panel']['height']>before['panel']['height']+100
                page.screenshot(path=str(OUT/'refined-register-desktop.png'),full_page=True)
                page.locator('#signup-fields [name="displayName"]').fill('Outra pessoa')
                page.locator('[name="email"]').fill('ux@example.com');page.locator('[name="username"]').fill('new_person')
                page.locator('#auth-form [name="password"]').fill('test-ux-password-123');page.locator('#auth-submit').click()
                expect(page.locator('#auth-error')).to_contain_text('Esse e-mail já está em uso',timeout=15000)
                page.locator('[name="email"]').fill('other@example.com');page.locator('[name="username"]').fill('ux_person');page.locator('#auth-submit').click()
                expect(page.locator('#auth-error')).to_contain_text('Esse nome de usuário já está em uso',timeout=15000)
                page.locator('[data-auth-mode="login"]').click()
                page.locator('[name="identifier"]').fill('ux_person');page.locator('#auth-submit').click()
                expect(page.locator('#app-shell')).to_be_visible()
                checks.append('20 distinct themed covers, no extra login phrase, stable signup layout and precise duplicate-email/username messages')

                step(page,'short')
                short=page.locator('.story[aria-hidden="false"]')
                expect(short.locator('.read-more')).to_be_hidden()
                assert short.locator('.reflection').evaluate('e=>getComputedStyle(e).textAlign')=='center'
                assert short.locator('.reflection').evaluate('e=>[getComputedStyle(e,"::before").content,getComputedStyle(e,"::after").content]')==['"“"','"”"']
                for width in (1440,768,390,360):
                    page.set_viewport_size({'width':width,'height':1000});page.wait_for_timeout(100)
                    bounds=short.evaluate('''story=>{
                        const box=selector=>story.querySelector(selector).getBoundingClientRect();
                        const cover=box('.cover-stage'),wrap=box('.reflection-wrap'),text=box('.reflection'),style=getComputedStyle(story.querySelector('.reflection-wrap'));
                        const actions=box('.story-actions'),title=box('.track-title'),more=story.querySelector('.read-more');
                        const top=wrap.top+parseFloat(style.paddingTop),bottom=wrap.bottom-parseFloat(style.paddingBottom);
                        return {actual:text.top+text.height/2,target:Math.max(top+text.height/2,Math.min(bottom-text.height/2,cover.top+cover.height/2)),textTop:text.top,textBottom:text.bottom,top,bottom,long:story.classList.contains('long-reflection'),coverBottom:cover.bottom,wrapBottom:wrap.bottom,moreBottom:more.hidden?0:more.getBoundingClientRect().bottom,actionsCenter:actions.top+actions.height/2,titleCenter:title.top+parseFloat(getComputedStyle(story.querySelector('.track-title')).lineHeight)/2};
                    }''')
                    if not bounds['long']:assert abs(bounds['actual']-bounds['target'])<2,(width,bounds)
                    assert bounds['textTop']>=bounds['top']-1 and bounds['textBottom']<=bounds['bottom']+1,(width,bounds)
                    assert abs(bounds['wrapBottom']-bounds['coverBottom'])<2 and bounds['moreBottom']<=bounds['coverBottom']+1,(width,bounds)
                    assert abs(bounds['actionsCenter']-bounds['titleCenter'])<2,(width,bounds)
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                    if width in (1440,390):page.screenshot(path=str(OUT/f'cover-aligned-feed-{width}.png'),full_page=True,animations='disabled')
                    step(page,'long');expect(page.locator('.story[aria-hidden="false"] .read-more')).to_be_visible()
                    step(page,'short')
                page.set_viewport_size({'width':1440,'height':1000});page.wait_for_timeout(100)
                step(page,'long');long=page.locator('.story[aria-hidden="false"]')
                expect(long.locator('.read-more')).to_be_visible()
                assert 'long-reflection' in long.get_attribute('class')
                assert long.locator('.reflection').inner_text().endswith('...')
                page.screenshot(path=str(OUT/'refined-feed-long-desktop.png'),full_page=True,animations='disabled')
                long.locator('.read-more').click();expect(page.locator('#reader .reader-text')).to_have_text(LONG)
                assert page.locator('.reader-card').count()==0
                cover=page.locator('#reader .reader-cover').bounding_box();copy=page.locator('#reader .reader-text').bounding_box()
                assert copy['y']>cover['y']+cover['height']
                assert page.locator('.reader-text').evaluate('e=>e.scrollHeight<=e.clientHeight+1')
                assert page.locator('#reader').evaluate('e=>e.scrollHeight>e.clientHeight')
                page.screenshot(path=str(OUT/'restored-reader-desktop.png'),full_page=True);page.keyboard.press('Escape')
                featured=page.locator('.featured-step').first
                assert featured.evaluate('e=>getComputedStyle(e,"::before").content') in ('none','normal')
                assert float(featured.evaluate('e=>getComputedStyle(e,"::after").height').replace('px',''))>2
                featured.click();weekly_story=page.locator('.story.featured')
                for width in (1440,768,390,360):
                    page.set_viewport_size({'width':width,'height':1000});page.wait_for_timeout(100)
                    bounds=weekly_story.evaluate('''story=>{
                        const box=selector=>story.querySelector(selector).getBoundingClientRect();
                        const cover=box('.cover-stage'),actions=box('.story-actions'),title=box('.track-title'),wrap=box('.reflection-wrap'),more=box('.read-more');
                        return {coverBottom:cover.bottom,wrapBottom:wrap.bottom,moreBottom:more.bottom,actionsCenter:actions.top+actions.height/2,titleCenter:title.top+parseFloat(getComputedStyle(story.querySelector('.track-title')).lineHeight)/2};
                    }''')
                    assert abs(bounds['actionsCenter']-bounds['titleCenter'])<2,(width,bounds)
                    assert abs(bounds['wrapBottom']-bounds['coverBottom'])<2 and bounds['moreBottom']<=bounds['coverBottom']+1,(width,bounds)
                    expect(weekly_story.locator('.read-more')).to_be_visible()
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                    if width in (1440,390):page.screenshot(path=str(OUT/f'weekly-feed-aligned-{width}.png'),full_page=True)
                checks.append('short comments aligned to the cover center on desktop/mobile without overlapping author/actions; long previews retain Read more; vertical reader and stronger weekly bar preserved')

                page.locator('[data-page="diario"]').click()
                for width in (1440,768,390,360):
                    page.set_viewport_size({'width':width,'height':1000});page.wait_for_timeout(100)
                    cards=page.locator('#diary-entries .diary-card')
                    heights=cards.evaluate_all('cards=>cards.map(card=>card.getBoundingClientRect().height)')
                    assert max(heights)-min(heights)<1,(width,heights)
                    sizes=cards.locator('.album-cover').evaluate_all('images=>images.map(image=>{const box=image.getBoundingClientRect();return [box.width,box.height,getComputedStyle(image).objectFit]})')
                    assert all(abs(w-h)<1 and fit=='cover' for w,h,fit in sizes),(width,sizes)
                    assert max(h for w,h,fit in sizes)-min(h for w,h,fit in sizes)<1,(width,sizes)
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                page.screenshot(path=str(OUT/'uniform-diary-mobile.png'),full_page=True)
                checks.append('diary covers are equal squares and cards keep equal heights at desktop/tablet/mobile sizes')
                page.locator('[data-page="perfil"]').click()
                for width in (1440,768,390,360):
                    page.set_viewport_size({'width':width,'height':1000})
                    page.wait_for_timeout(100)
                    cards=page.locator('#profile-content .diary-card')
                    heights=cards.evaluate_all('cards=>cards.map(card=>card.getBoundingClientRect().height)')
                    assert max(heights)-min(heights)<1,(width,heights)
                    assert cards.locator('.album-cover').evaluate_all('images=>images.every(image=>{const box=image.getBoundingClientRect();return Math.abs(box.width-box.height)<1&&getComputedStyle(image).objectFit==="cover";})')
                    expect(page.locator('#profile-content')).not_to_contain_text('Ressoas públicas')
                    weekly=page.locator('#profile-content .weekly-feature')
                    assert weekly.bounding_box()['height']==(300 if width<=640 else 350)
                    expect(weekly.locator('.post-commands,.weekly-social')).to_have_count(0)
                    trigger=weekly.locator('.weekly-menu summary');trigger.click()
                    expect(weekly.locator('.weekly-menu-panel button')).to_have_text(['Abrir','Compartilhar','Apagar'])
                    commands=weekly.locator('.weekly-menu-panel').bounding_box();box=weekly.bounding_box()
                    assert commands['x']>=box['x'] and commands['x']+commands['width']<=box['x']+box['width']-5,(width,commands,box)
                    assert commands['y']+commands['height']<=box['y']+box['height']-5,(width,commands,box)
                    if width in (1440,390):weekly.screenshot(path=str(OUT/f'own-weekly-menu-{width}.png'))
                    page.keyboard.press('Escape');expect(trigger).to_be_focused();expect(weekly.locator('.weekly-menu-panel')).to_be_hidden()
                    preview=page.locator('#profile-content .diary-card[data-id="long"] .reflection')
                    assert preview.inner_text().endswith('...'),preview.inner_text()
                    assert preview.evaluate('e=>e.scrollHeight<=e.clientHeight+1')
                    assert cards.evaluate_all('cards=>cards.every(card=>{const footer=card.querySelector(".privacy").getBoundingClientRect();return footer.bottom<=card.getBoundingClientRect().bottom-6;})')
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                page.screenshot(path=str(OUT/'restored-profile-mobile.png'),full_page=True)
                page.set_viewport_size({'width':1440,'height':1000});page.locator('#edit-profile').click()
                page.locator('#favorite-picker-0 input').fill('outra favorita')
                page.locator('#favorite-picker-0 .catalog-result').click()
                page.locator('#profile-form [type="submit"]').click();expect(page.locator('#profile-editor')).to_be_hidden()
                expect(page.locator('.favorite-grid')).to_contain_text('Outra favorita')
                expect(page.locator('.favorite-grid>div')).to_have_count(6)
                expect(page.locator('.favorite-picker')).to_have_count(6)
                expect(page.locator('#toast')).to_be_hidden(timeout=6000)
                for width in (1440,768,390,360):
                    page.set_viewport_size({'width':width,'height':1000});page.wait_for_timeout(100)
                    assert page.locator('.favorite-grid').evaluate('grid=>{const box=grid.getBoundingClientRect(),cells=[...grid.children].map(node=>node.getBoundingClientRect()),firstRow=cells.filter(cell=>Math.abs(cell.top-cells[0].top)<1),gap=parseFloat(getComputedStyle(grid).columnGap);return Math.abs(firstRow[0].left-box.left)<1&&Math.abs(firstRow.at(-1).right-box.right)<1&&cells.every(cell=>Math.abs(cell.width-cells[0].width)<1)&&firstRow.every((cell,i)=>i===0||Math.abs(cell.left-firstRow[i-1].right-gap)<1);}')
                    assert page.locator('.favorite-grid .album-cover').evaluate_all('images=>images.every(image=>image.getBoundingClientRect().width<=150.5)')
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                    if width in (1440,390):page.locator('.profile-favorites').screenshot(path=str(OUT/f'full-width-favorites-{width}.png'))
                page.set_viewport_size({'width':1440,'height':1000})
                page.reload();expect(page.locator('.favorite-grid')).to_contain_text('Outra favorita')
                page.screenshot(path=str(OUT/'restored-profile-desktop.png'),full_page=True)
                checks.append('profile covers fill square thumbnails; cards keep equal heights and ellipses; weekly own menu works; six compact searchable favorites stay together and persist on desktop/mobile')

                page.locator('#profile-content [data-read="long"]').click()
                page.evaluate('''()=>{
                    const draw=CanvasRenderingContext2D.prototype.fillText;window.sharedLines=[];
                    CanvasRenderingContext2D.prototype.fillText=function(text,...args){window.sharedLines.push(text);return draw.call(this,text,...args);};
                }''')
                page.locator('#reader [data-share]').click()
                expect(page.locator('#share-preview img')).to_be_visible(timeout=20000)
                expect(page.locator('#download-share')).to_be_enabled(timeout=20000)
                with page.expect_download() as downloading:page.locator('#download-share').click()
                output=OUT/'share-reader-long.png';downloading.value.save_as(str(output))
                dimensions=struct.unpack('>II',output.read_bytes()[16:24]);assert dimensions==(1080,1350),dimensions
                assert any(text.startswith('“') for text in page.evaluate('window.sharedLines'))
                assert any(text.endswith('...”') for text in page.evaluate('window.sharedLines'))
                page.keyboard.press('Escape');page.keyboard.press('Escape')
                page.locator('#profile-content [data-read="short"]').click();page.locator('#reader [data-share]').click()
                expect(page.locator('#share-dialog .dialog-actions button')).to_have_text(['Baixar ressoa','Copiar link'])
                expect(page.locator('#native-share,#device-share,#share-options,[data-share-network]')).to_have_count(0)
                expect(page.locator('#copy-share-link')).to_be_enabled()
                page.evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.testCopied=text}}})")
                page.locator('#copy-share-link').click();assert page.evaluate('window.testCopied')==origin+'/#ressoa/short'
                expect(page.locator('#download-share')).to_be_enabled(timeout=20000)
                with page.expect_download() as downloading:page.locator('#download-share').click()
                output=OUT/'share-reader-short.png';downloading.value.save_as(str(output))
                assert struct.unpack('>II',output.read_bytes()[16:24])==dimensions
                for width in (1440,390,320):
                    page.set_viewport_size({'width':width,'height':1000});page.wait_for_timeout(100)
                    assert page.locator('#share-dialog').evaluate('element=>element.scrollWidth<=element.clientWidth')
                    if width in (1440,390):page.screenshot(path=str(OUT/f'share-simple-{width}.png'))
                assert app.db.interactions(user,'short')==[];assert share_requests==[]
                page.set_viewport_size({'width':1440,'height':1000});page.keyboard.press('Escape');page.keyboard.press('Escape')
                # Copy link remains available even when the image cannot be generated.
                page.evaluate('()=>{window.savedToBlob=HTMLCanvasElement.prototype.toBlob;HTMLCanvasElement.prototype.toBlob=function(callback){callback(null)};}')
                page.locator('#profile-content [data-read="other"]').click();page.locator('#reader [data-share]').click()
                expect(page.locator('#share-status')).to_contain_text('copiar o link')
                expect(page.locator('#download-share')).to_be_disabled();expect(page.locator('#copy-share-link')).to_be_enabled()
                page.locator('#copy-share-link').click();assert page.evaluate('window.testCopied')==origin+'/#ressoa/other'
                page.evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw new Error('denied')}}})")
                page.locator('#copy-share-link').click();expect(page.locator('#toast')).to_contain_text('copiar o link')
                page.evaluate('()=>{HTMLCanvasElement.prototype.toBlob=window.savedToBlob;}')
                page.keyboard.press('Escape');page.keyboard.press('Escape')
                liker=app.db.register(dict(email='only-likes@example.com',username='only_likes',displayName='Pessoa que curtiu',password='test-only-likes-123'))
                for kind in ('like','repost'):app.db.action(liker,kind,'short',True)
                page.locator('#profile-content [data-read="short"]').click();page.locator('#reader [data-interactions]').click()
                expect(page.locator('#people-title')).to_have_text('Curtidas e reposts')
                expect(page.locator('#people-content')).to_contain_text('Curtiu');expect(page.locator('#people-content')).to_contain_text('Repostou');expect(page.locator('#people-content')).not_to_contain_text('Compartilhou')
                page.screenshot(path=str(OUT/'interactions-with-shares.png'));page.keyboard.press('Escape');page.keyboard.press('Escape')
                checks.append('share icon opens the image preview with only Download ressoa and Copy link; PNG remains 1080x1350; copy works if image generation fails and clipboard denial is shown; no network/native sharing or tracking')

                page.locator('[data-page="foryou"]').click();step(page,'short')
                page.locator('.story[aria-hidden="false"] .cover-open').click()
                expect(page.locator('#track-context')).to_contain_text('Tim Maia 1970')
                expect(page.locator('#track-context')).to_contain_text('05/01/1970')
                expect(page.locator('#track-context')).to_contain_text('28/09/2018')
                expect(page.locator('#track-context')).to_contain_text('3:18')
                expect(page.locator('#track-context')).to_contain_text('Participantes')
                assert page.locator('.native-preview audio').evaluate('audio=>audio.volume')==.5
                page.screenshot(path=str(OUT/'refined-deezer-context.png'),full_page=True)
                checks.append('Deezer context reaches the detail view/player and native audio starts at 50% volume')
                assert not errors,errors
                browser.close()
        finally:
            server.shutdown();server.server_close();worker.join(timeout=5)
    report=dict(result='PASS',checks=checks,javascript_errors=errors,database='temporary')
    (OUT/'refinements-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
