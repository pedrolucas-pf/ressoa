import json
import unittest
from unittest.mock import patch
import services
from database import clean_track
from test_accounts import Accounts,TRACK


class MusicContext(unittest.TestCase):
    def setUp(self):
        services._CACHE.clear()

    def test_deezer_metadata_keeps_album_date_and_track_edition(self):
        item=dict(id=543138072,title='Azul Da Cor Do Mar',artist={'name':'Tim Maia'},album={'title':'Tim Maia 1970','release_date':'1970-01-05','cover_big':'https://cdn-images.dzcdn.net/images/cover/abc/500.jpg'},release_date='2018-09-28',duration=198,contributors=[{'name':'Tim Maia','role':'Main'}],bpm=126.05,isrc='BRMCA7000090',explicit_lyrics=False)
        with patch('services._json',return_value=item):
            track=services.get_track('deezer:543138072')
        clean=clean_track(track)
        self.assertEqual(clean['year'],'1970');self.assertEqual(clean['releaseDate'],'1970-01-05')
        self.assertEqual(clean['trackReleaseDate'],'2018-09-28');self.assertEqual(clean['contributors'],['Tim Maia'])
        self.assertEqual(clean['duration'],198);self.assertFalse(clean['explicit'])

    def test_login_artwork_is_unique_themed_and_available_without_external_requests(self):
        with patch('services._json',side_effect=AssertionError('Login must not depend on an external service')) as fetch:
            first=services.login_artwork();second=services.login_artwork()
        fetch.assert_not_called()
        artists={'Chico Buarque','Caetano Veloso','Gal Costa','Elis Regina','Gilberto Gil','Milton Nascimento','Djavan','Tim Maia','Legião Urbana','Titãs','Os Paralamas do Sucesso','Cazuza','Barão Vermelho','Rita Lee','Engenheiros do Hawaii','Nando Reis'}
        for payload in (first,second):
            self.assertEqual(len(payload['covers']),20)
            self.assertEqual(len({item['artwork'] for item in payload['covers']}),20)
            self.assertTrue(all(item['artist'] in artists for item in payload['covers']))


class AccountRefinements(Accounts):
    # Inherit the disposable API client, not the old test methods a second time.
    def test_duplicate_messages_identify_the_field(self):
        self.register()
        base=dict(email='new@example.com',username='new_user',displayName='Nova pessoa',password='test-password-123')
        result=self.call('/api/register','POST',dict(base,email='A@EXAMPLE.COM'))
        self.assertEqual(result['status'],409);self.assertIn('Esse e-mail já está em uso',result['data']['error'])
        result=self.call('/api/register','POST',dict(base,username='USER_A'))
        self.assertEqual(result['status'],409);self.assertIn('Esse nome de usuário já está em uso',result['data']['error'])
        result=self.call('/api/register','POST',dict(base,email='a@example.com',username='user_a'))
        self.assertEqual(result['status'],409);self.assertIn('e-mail e esse nome',result['data']['error'])

    def test_verified_track_context_survives_reloading(self):
        self.register()
        enriched=dict(TRACK,releaseDate='1972-01-01',trackReleaseDate='2010-01-01',contributors=['Milton Nascimento'],bpm=95,isrc='BRABC7200001',explicit=False)
        with patch('webapp.get_track',return_value=enriched):
            result=self.call('/api/track?id=spotify:6jVWIRz01vnJ1VE8LtWK6Q')
        self.assertEqual(result['status'],200)
        self.save([dict(id='context-post',track=TRACK,text='Um comentário para testar os metadados.',visibility='public')])
        post=self.call('/api/bootstrap')['data']['entries'][0]
        self.assertEqual(post['track']['contributors'],['Milton Nascimento'])
        self.assertEqual(post['track']['releaseDate'],'1972-01-01')
        # Weekly posts cannot be made private even by bypassing the UI.
        result=self.call('/api/weekly','POST',dict(track=TRACK,text='Um destaque que é sempre público.',visibility='private'))
        self.assertEqual(result['data']['weekly']['item']['visibility'],'public')


def load_tests(loader, tests, pattern):
    suite=unittest.TestSuite(loader.loadTestsFromTestCase(MusicContext))
    suite.addTest(AccountRefinements('test_duplicate_messages_identify_the_field'))
    suite.addTest(AccountRefinements('test_verified_track_context_survives_reloading'))
    return suite
