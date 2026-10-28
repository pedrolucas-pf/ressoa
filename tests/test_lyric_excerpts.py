import unittest
from test_accounts import Accounts,TRACK


class LyricExcerpts(Accounts):
    def test_excerpt_persists_and_weekly_is_independent(self):
        self.register()
        post=dict(id='excerpt-post',track=TRACK,text='Dor',visibility='public',lyricExcerpt='Um verso inventado para o teste.\nOutro verso original de teste.')
        result=self.save([post]);self.assertEqual(result['status'],200)
        self.assertEqual(result['data']['entries'][0]['lyricExcerpt'],post['lyricExcerpt'])
        weekly=self.call('/api/weekly','POST',dict(track=TRACK,lyricExcerpt='Um outro verso de teste.'))
        self.assertEqual(weekly['status'],200);self.assertEqual(weekly['data']['weekly']['item']['lyricExcerpt'],'Um outro verso de teste.')
        entry=self.call('/api/post?id=excerpt-post')['data']['post']
        self.assertEqual(entry['lyricExcerpt'],post['lyricExcerpt']);self.assertEqual(entry['text'],'Dor')
        self.assertEqual(self.call('/api/profile?user='+result['data']['user']['id'])['data']['entries'][0]['lyricExcerpt'],post['lyricExcerpt'])
        result=self.save([dict(post,lyricExcerpt='')],version=result['data']['versions']['entries'])
        self.assertEqual(result['status'],200);self.assertEqual(result['data']['entries'][0]['lyricExcerpt'],'')
        self.assertEqual(result['data']['weekly']['item']['lyricExcerpt'],'Um outro verso de teste.')

    def test_excerpt_length_lines_types_and_draft(self):
        self.register();post=dict(id='valid-excerpt',track=TRACK,text='A',visibility='public',lyricExcerpt='x'*120)
        result=self.save([post]);self.assertEqual(result['status'],200)
        version=result['data']['versions']['entries']
        for invalid in ('x'*121,'um\ndois\ntrês\nquatro',False,[],None):
            self.assertEqual(self.save([dict(post,lyricExcerpt=invalid)],version=version)['status'],400)
        self.assertEqual(self.call('/api/bootstrap')['data']['entries'][0]['lyricExcerpt'],'x'*120)
        result=self.call('/api/preference','PUT',dict(key='draft',value=dict(text='A',track=TRACK,lyricExcerpt='Trecho do rascunho.')))
        self.assertEqual(result['status'],200)
        self.assertEqual(self.call('/api/bootstrap')['data']['draft']['lyricExcerpt'],'Trecho do rascunho.')


def load_tests(loader,tests,pattern):
    return unittest.TestSuite(LyricExcerpts(name) for name in ('test_excerpt_persists_and_weekly_is_independent','test_excerpt_length_lines_types_and_draft'))
