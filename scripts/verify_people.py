"""Search and public-profile UI checks with real API and disposable accounts."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import tempfile
import threading
from wsgiref.simple_server import make_server
from verify_accounts import ROOT,OUT,QuietHandler,music_fixture,TRACK
from webapp import Application
from serve import LocalServer
from playwright.sync_api import sync_playwright,expect
from scripts.verification_support import verification_source


def main():
    checks=[];errors=[]
    with tempfile.TemporaryDirectory() as directory:
        app=Application(verification_source(Path(directory)/'people.sqlite3'),production=False)
        def person(username,name):
            return app.db.register(dict(email=username+'@example.com',username=username,displayName=name,password='test-people-password-123'))
        viewer=person('me_viewer','Minha conta');joao=person('joao_silva','João da Silva');clara=person('clara_music','Clara Lima')
        publications=[dict(id=f'joao-{index:02}',track=TRACK,text=f'Um comentário público para guardar a música, número {index}.',visibility='public') for index in range(28)]
        publications.append(dict(id='joao-private',track=TRACK,text='ESTE TEXTO PRIVADO NÃO PODE APARECER NO PERFIL.',visibility='private'))
        app.db.save_entries(joao,dict(version=0,value=publications))
        app.db.save_profile(joao,dict(version=0,value=dict(displayName='João da Silva',handle='joao_silva',bio='A minha história passa por uma música.',photo='',favorites=[TRACK],background=TRACK,pinned=['joao-00'])))
        app.db.choose_weekly(joao,dict(track=TRACK,text='Uma lembrança independente para esta semana.'))
        app.db.save_entries(clara,dict(version=0,value=[dict(id=f'clara-{i:03}',track=TRACK,text=f'Um comentário público de outra pessoa, número {i}.',visibility='public') for i in range(130)]))
        app.db.action(joao,'repost','clara-000',True)
        app.db.action(joao,'follow',clara,True)
        server=make_server('127.0.0.1',0,app,server_class=LocalServer,handler_class=QuietHandler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        origin=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='chrome',headless=True)
                context=browser.new_context(viewport={'width':1440,'height':1000})
                context.route('**/api/**',music_fixture)
                page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(origin);page.locator('#auth-form').wait_for(state='visible')
                page.locator('[name="identifier"]').fill('me_viewer');page.locator('#auth-form [name="password"]').fill('test-people-password-123');page.locator('#auth-submit').click()
                expect(page.locator('#app-shell')).to_be_visible(timeout=15000)
                feed_before=set(page.locator('.story').evaluate_all('stories=>stories.map(story=>story.dataset.id)'))
                assert all(identifier.startswith('clara-') for identifier in feed_before)
                page.locator('.story[aria-hidden="false"] .author').click()
                expect(page.locator('#profile-content h1')).to_have_text('Clara Lima')
                expect(page.locator('#edit-profile')).to_be_hidden();expect(page.locator('#logout')).to_be_hidden()
                expect(page.locator('#back-my-profile')).to_be_visible()
                page.locator('#back-my-profile').click();expect(page.locator('#profile-content h1')).to_have_text('Minha conta')
                expect(page.locator('#edit-profile')).to_be_visible()
                checks.append('author name/avatar opens that person; other profile has no edit/logout controls and My profile returns to the owner')

                search=page.locator('#people-query');search.fill('@joao_silva')
                expect(page.locator('#people-results .people-result')).to_have_count(1)
                expect(page.locator('#people-results')).to_contain_text('João da Silva')
                page.screenshot(path=str(OUT/'people-search-desktop.png'),full_page=True)
                search.press('ArrowDown');search.press('Enter')
                expect(page.locator('#profile-content h1')).to_have_text('João da Silva')
                expect(page.locator('#profile-content')).to_contain_text('A minha história passa por uma música.')
                expect(page.locator('.weekly-feature')).to_contain_text('Uma lembrança independente')
                weekly=page.locator('.weekly-feature')
                expect(weekly.locator('.author')).to_have_count(0)
                expect(weekly.locator('.weekly-menu')).to_have_count(0)
                expect(weekly.locator('.weekly-social .icon-button')).to_have_count(4)
                expect(weekly.locator('.post-commands')).to_have_count(0)
                assert weekly.locator('[data-share]').inner_text()==''
                weekly.locator('[data-like]').click();expect(weekly.locator('[data-like]')).to_have_attribute('aria-pressed','true')
                weekly.locator('[data-like]').click();expect(weekly.locator('[data-like]')).to_have_attribute('aria-pressed','false')
                weekly.locator('[data-repost]').click();expect(weekly.locator('[data-repost]')).to_have_attribute('aria-pressed','true')
                weekly.locator('[data-repost]').click();expect(weekly.locator('[data-repost]')).to_have_attribute('aria-pressed','false')
                weekly.locator('[data-share]').click();expect(page.locator('#share-dialog')).to_be_visible();page.locator('[data-close="share-dialog"]').click()
                weekly.locator('.weekly-title-open').click();expect(page.locator('#reader .reader-text')).to_contain_text('Uma lembrança independente');page.keyboard.press('Escape')
                for width in (1440,390):
                    page.set_viewport_size({'width':width,'height':1000});page.wait_for_timeout(100)
                    box=weekly.bounding_box();actions=weekly.locator('.weekly-social').bounding_box()
                    assert actions['y']+actions['height']<=box['y']+box['height']-10,(width,box,actions)
                    assert weekly.locator('.weekly-social svg').evaluate_all('nodes=>nodes.every(node=>node.getBoundingClientRect().width===18)')
                    weekly.screenshot(path=str(OUT/f'visited-weekly-actions-{width}.png'))
                page.set_viewport_size({'width':1440,'height':1000})
                expect(page.locator('.favorite-grid')).to_contain_text(TRACK['title'])
                expect(page.locator('#profile-content .pin-label')).to_have_count(1)
                assert 'PRIVADO' not in page.locator('#profile-content').inner_text()
                assert page.locator('#profile-content [data-delete-weekly]').count()==0
                assert page.locator('body').evaluate('e=>e.classList.contains("profile-background")')
                first_grid=page.locator('#profile-content .profile-posts').first
                expect(page.locator('#profile-content .profile-posts')).to_have_count(1)
                expect(first_grid.locator('.diary-card')).to_have_count(25)
                expect(first_grid.locator('.repost-badge')).to_have_count(1)
                expect(first_grid.locator('.repost-badge')).to_have_attribute('aria-label','Repost de @clara_music')
                assert first_grid.locator('.diary-card').first.get_attribute('data-id')=='joao-00'
                first_grid.locator('[data-more-profile="entries"]').click();expect(first_grid.locator('.diary-card')).to_have_count(29)
                first_grid.locator('.repost-badge').click();expect(page.locator('#profile-content h1')).to_have_text('Clara Lima')
                search.fill('joao_silva');expect(page.locator('#people-results')).to_contain_text('João da Silva');search.press('ArrowDown');search.press('Enter')
                expect(page.locator('#profile-content h1')).to_have_text('João da Silva')
                first_grid.locator('[data-more-profile="entries"]').click();expect(first_grid.locator('.diary-card')).to_have_count(29)
                page.screenshot(path=str(OUT/'unified-profile-reposts.png'),full_page=True)
                first_grid.locator('[data-read="joao-01"]').click()
                expect(page.locator('#reader .reader-text')).to_contain_text('número 1.')
                assert page.locator('#reader [data-edit],#reader [data-delete],#reader [data-interactions],#reader [data-reader-pin]').count()==0
                page.locator('#reader [data-like]').click();expect(page.locator('#reader [data-like]')).to_have_attribute('aria-pressed','true')
                page.keyboard.press('Escape')
                checks.append('search by @username and keyboard opens real public bio/favorites/week/pins/reposts; load more and reading older posts work without exposing private entries or owner controls')

                page.locator('[data-page="foryou"]').click()
                feed_after=set(page.locator('.story').evaluate_all('stories=>stories.map(story=>story.dataset.id)'))
                assert feed_after==feed_before,(feed_before,feed_after)
                search.fill('JOÃO');expect(page.locator('#people-results')).to_contain_text('João da Silva');search.press('Enter')
                expect(page.locator('#profile-content h1')).to_have_text('João da Silva')
                expect(page.locator('.profile-menu')).to_have_count(0)
                page.locator('.profile-follow').click();expect(page.locator('.profile-follow')).to_have_attribute('aria-pressed','true')
                page.locator('.profile-menu summary').click();page.locator('[data-followers-list]').click()
                expect(page.locator('#people-content')).to_contain_text('Minha conta')
                expect(page.locator('#people-content [data-remove-follower],#people-content [data-follow]')).to_have_count(0)
                page.keyboard.press('Escape')
                page.locator('.profile-menu summary').click();page.locator('[data-following-list]').click()
                expect(page.locator('#people-content')).to_contain_text('Clara Lima');page.keyboard.press('Escape')
                page.set_viewport_size({'width':390,'height':844});page.locator('.profile-menu summary').click()
                page.screenshot(path=str(OUT/'followed-profile-options-mobile.png'));page.keyboard.press('Escape')
                page.set_viewport_size({'width':1440,'height':1000})
                page.reload();expect(page.locator('#profile-content h1')).to_have_text('João da Silva')
                expect(page.locator('.profile-follow')).to_have_attribute('aria-pressed','true')
                page.screenshot(path=str(OUT/'public-profile-desktop.png'))
                page.locator('#back-my-profile').click();page.locator('.profile-menu summary').click();page.locator('[data-following-list]').click()
                expect(page.locator('#people-content')).to_contain_text('João da Silva')
                page.locator('#people-content [data-person]').click();expect(page.locator('#people-dialog')).to_be_hidden()
                expect(page.locator('#profile-content h1')).to_have_text('João da Silva')
                page.locator('.profile-follow').click();expect(page.locator('.profile-follow')).to_have_attribute('aria-pressed','false')
                expect(page.locator('.profile-menu')).to_have_count(0)
                assert app.db.bootstrap(viewer)['profile']['handle']=='me_viewer'
                checks.append('visited history does not accumulate in the feed; follow/unfollow persist and Following links open public profiles without changing the own profile')

                for width in (390,360,768):
                    page.set_viewport_size({'width':width,'height':844});page.wait_for_timeout(100)
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'),width
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(OUT/'public-profile-mobile.png'))
                page.locator('#toggle-people-search').click()
                search.fill('nobody_found');expect(page.locator('#people-search-status')).to_have_text('Nenhuma pessoa encontrada.')
                page.locator('#clear-people-search').click();expect(page.locator('#people-search-panel')).to_be_hidden()
                page.route('**/api/people?*',lambda route:route.fulfill(status=503,json={'error':'Temporary search failure'}),times=1)
                search.fill('clara');expect(page.locator('#people-search-status')).to_contain_text('Não foi possível buscar')
                page.locator('#people-search-status button').click();expect(page.locator('#people-results')).to_contain_text('Clara Lima')
                search.press('Escape');expect(page.locator('#people-search-panel')).to_be_hidden()
                page.goto(origin+'/#pessoa/missing');expect(page.locator('#profile-content')).to_contain_text('Esse perfil não foi encontrado.')
                page.locator('#back-my-profile').click();expect(page.locator('#profile-content h1')).to_have_text('Minha conta')
                checks.append('mobile layout, empty search, clear/Escape, failed search retry and missing-profile recovery work')

                # A profile link remains the destination when arriving before login.
                anonymous=browser.new_context(viewport={'width':390,'height':844});anonymous.route('**/api/**',music_fixture)
                linked=anonymous.new_page();linked.on('pageerror',lambda e:errors.append(str(e)));linked.goto(origin+'/#pessoa/'+joao)
                linked.locator('#auth-form').wait_for(state='visible')
                linked.locator('[name="identifier"]').fill('me_viewer');linked.locator('#auth-form [name="password"]').fill('test-people-password-123');linked.locator('#auth-submit').click()
                expect(linked.locator('#profile-content h1')).to_have_text('João da Silva')
                anonymous.close();checks.append('direct public-profile hash survives sign-in on a new browser context')
                assert not errors,errors
                browser.close()
        finally:
            server.shutdown();server.server_close();worker.join(timeout=5)
    report=dict(result='PASS',checks=checks,javascript_errors=errors,database='temporary; no real accounts changed')
    (OUT/'people-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
