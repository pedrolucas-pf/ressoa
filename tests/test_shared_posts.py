"""Shared links keep the same account/privacy rules as the rest of Ressoa."""
import unittest
from test_accounts import Accounts,TRACK


class SharedPosts(Accounts):
    def test_comments_optional_for_entries_and_weekly(self):
        self.register()
        post=dict(id='one-word',track=TRACK,text='Saudade',visibility='public')
        result=self.save([post]);self.assertEqual(result['status'],200)
        version=result['data']['versions']['entries']
        for message in ('','   ','\n\t'):
            result=self.save([dict(post,text=message)],version=version)
            self.assertEqual(result['status'],200);self.assertEqual(result['data']['entries'][0]['text'],'')
            version=result['data']['versions']['entries']
        for message in (None,123,[],{},'x'*2401):
            self.assertEqual(self.save([dict(post,text=message)],version=version)['status'],400)
        result=self.save([dict(post,text='💔')],version=version);self.assertEqual(result['status'],200)
        version=result['data']['versions']['entries']
        excerpt_only=dict(post,lyricExcerpt='Um verso inventado, apenas para este teste.')
        del excerpt_only['text']
        result=self.save([excerpt_only],version=version);self.assertEqual(result['status'],200)
        persisted=self.call('/api/post?id=one-word')['data']['post']
        self.assertEqual(persisted['text'],'');self.assertEqual(persisted['lyricExcerpt'],excerpt_only['lyricExcerpt'])
        weekly=self.call('/api/weekly','POST',dict(track=TRACK))
        self.assertEqual(weekly['status'],200);self.assertEqual(weekly['data']['weekly']['item']['text'],'')
        self.assertEqual(weekly['data']['weekly']['item']['visibility'],'public')
        self.assertEqual(self.call('/api/weekly','DELETE',{})['status'],200)
        self.assertEqual(self.call('/api/weekly','POST',dict(track=TRACK,text=''))['status'],409)

    def test_shared_link_loads_older_posts_but_requires_auth_and_privacy(self):
        self.register();self.register('b')
        items=[dict(id=f'older-{i:03}',track=TRACK,text=f'Lembrança número {i}',visibility='public') for i in range(130)]
        items.append(dict(id='only-me',track=TRACK,text='Íntimo',visibility='private'))
        result=self.save(items);self.assertEqual(result['status'],200)
        self.assertNotIn('older-000',{post['id'] for post in self.call('/api/bootstrap',actor='b')['data']['publicPosts']})
        self.assertEqual(self.call('/api/post?id=older-000',actor='anonymous')['status'],401)
        shared=self.call('/api/post?id=older-000',actor='b')
        self.assertEqual(shared['status'],200);self.assertEqual(shared['data']['post']['text'],items[0]['text'])
        self.assertEqual(shared['data']['post']['track']['catalogId'],TRACK['catalogId'])
        self.assertNotIn('email',shared['data']['post'])
        self.assertEqual(self.call('/api/post?id=only-me',actor='b')['status'],404)
        self.assertEqual(self.call('/api/post?id=only-me')['status'],200)
        self.assertEqual(self.call('/api/post?id=missing',actor='b')['status'],404)
        items=items[1:];result=self.save(items,version=result['data']['versions']['entries'])
        self.assertEqual(result['status'],200)
        self.assertEqual(self.call('/api/post?id=older-000',actor='b')['status'],404)

    def test_deleted_or_expired_weekly_links_are_unavailable(self):
        owner=self.register();self.register('b')
        result=self.call('/api/weekly','POST',dict(track=TRACK,text=''))
        identifier=result['data']['weekly']['postId']
        self.assertEqual(self.call('/api/post?id='+identifier,actor='b')['status'],200)
        with self.app.db.transaction() as db:
            db.execute('UPDATE weekly SET week_key=? WHERE user_id=?',('2000-W01',owner['user']['id']))
        self.assertEqual(self.call('/api/post?id='+identifier,actor='b')['status'],404)


def load_tests(loader,tests,pattern):
    return unittest.TestSuite(SharedPosts(name) for name in (
        'test_comments_optional_for_entries_and_weekly',
        'test_shared_link_loads_older_posts_but_requires_auth_and_privacy',
        'test_deleted_or_expired_weekly_links_are_unavailable'))
