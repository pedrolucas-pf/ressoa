"""Six favorite choices persist without truncation or replacing existing choices."""
import unittest
from test_accounts import Accounts,TRACK
from webapp import Application


class Favorites(Accounts):
    def test_six_favorites_persist_and_seventh_is_rejected(self):
        a=self.register();self.register('b')
        favorites=[dict(TRACK,catalogId=TRACK['catalogId'][:-1]+suffix,title=f'Favorita {index}') for index,suffix in enumerate('abcdef',1)]
        profile=dict(a['profile'],favorites=favorites)
        result=self.call('/api/profile','PUT',dict(version=0,value=profile))
        self.assertEqual(result['status'],200)
        self.assertEqual([track['catalogId'] for track in result['data']['profile']['favorites']],[track['catalogId'] for track in favorites])
        self.app=Application(self.app.db.source,production=False)
        self.assertEqual(len(self.call('/api/bootstrap')['data']['profile']['favorites']),6)
        self.assertEqual(len(self.call('/api/profile?user='+a['user']['id'],actor='b')['data']['profile']['favorites']),6)
        extra=dict(TRACK,catalogId=TRACK['catalogId'][:-1]+'g')
        result=self.call('/api/profile','PUT',dict(version=result['data']['versions']['profile'],value=dict(profile,favorites=[*favorites,extra])))
        self.assertEqual(result['status'],400)
        self.assertEqual(len(self.call('/api/bootstrap')['data']['profile']['favorites']),6)


def load_tests(loader,tests,pattern):
    return unittest.TestSuite([Favorites('test_six_favorites_persist_and_seventh_is_rejected')])
