"""Feed expiry archives posts; republishing never duplicates or exposes private content."""
import unittest
from datetime import datetime,timedelta,timezone
from webapp import Application
from test_accounts import Accounts,TRACK


class FeedLifetime(Accounts):
    def age(self,identifier,hours=25):
        old=(datetime.now(timezone.utc)-timedelta(hours=hours)).isoformat()
        with self.app.db.transaction() as db:
            db.execute('UPDATE posts SET created_at=?,updated_at=?,feed_published_at=? WHERE id=?',(old,old,old,identifier))
        return old

    def test_older_posts_leave_feed_but_remain_on_profile_and_links(self):
        a=self.register();self.register('b')
        entries=[dict(id=identifier,track=TRACK,text='Um texto guardado.',visibility='public') for identifier in ('old-entry','recent-entry')]
        self.save(entries);old=self.age('old-entry')
        state=self.call('/api/bootstrap',actor='b')['data']
        self.assertEqual([post['id'] for post in state['publicPosts']],['recent-entry'])
        self.assertEqual(len(self.call('/api/profile?user='+a['user']['id'],actor='b')['data']['entries']),2)
        self.assertEqual(self.call('/api/post?id=old-entry',actor='b')['status'],200)
        # An offset must not make an old instant appear newer than the UTC cutoff.
        offset=datetime.fromisoformat(old).astimezone(timezone(timedelta(hours=14))).isoformat()
        with self.app.db.transaction() as db:db.execute('UPDATE posts SET feed_published_at=? WHERE id=?',(offset,'old-entry'))
        self.assertEqual([post['id'] for post in self.call('/api/bootstrap',actor='b')['data']['publicPosts']],['recent-entry'])
        self.call('/api/action','POST',dict(kind='saved',target='old-entry',active=True),'b')
        self.assertIn('old-entry',self.call('/api/bootstrap',actor='b')['data']['saved'])
        weekly=self.call('/api/weekly','POST',dict(track=TRACK,text=''))['data']['weekly']['postId']
        self.age(weekly,48)
        self.assertIn(weekly,{post['id'] for post in self.call('/api/bootstrap',actor='b')['data']['publicPosts']})

    def test_republication_requires_an_actual_edit(self):
        self.register();self.register('b')
        entry=dict(id='same-post',track=TRACK,text='Saudade',visibility='public')
        result=self.save([entry]);self.age('same-post')
        for kind in ('like','repost','saved'):self.call('/api/action','POST',dict(kind=kind,target='same-post',active=True),'b')
        before=self.call('/api/post?id=same-post')['data']['post']
        for actor in ('a','b'):
            self.assertEqual(self.call('/api/republish','POST',dict(post='same-post'),actor=actor)['status'],404)
        noop=self.call('/api/entries','PUT',dict(value=[entry],version=result['data']['versions']['entries'],republish='same-post'))
        self.assertEqual(noop['status'],400)
        self.assertEqual(self.call('/api/post?id=same-post')['data']['post'],before)
        state=self.call('/api/bootstrap',actor='b')['data']
        self.assertIn('same-post',state['social']['reposts']);self.assertIn('same-post',state['social']['likes']);self.assertIn('same-post',state['saved'])

    def test_editing_does_not_renew_and_publication_time_cannot_be_forged(self):
        self.register();entry=dict(id='edited-post',track=TRACK,text='Texto inicial',visibility='public')
        result=self.save([entry]);old=self.age('edited-post')
        result=self.save([dict(entry,text='Texto editado',publishedAt='2099-01-01T00:00:00+00:00')],version=result['data']['versions']['entries'])
        self.assertEqual(result['status'],200);self.assertEqual(result['data']['entries'][0]['publishedAt'],old)
        result=self.save([dict(entry,visibility='private')],version=result['data']['versions']['entries'])
        self.assertEqual(self.call('/api/republish','POST',dict(post='edited-post'))['status'],404)
        result=self.save([entry],version=result['data']['versions']['entries'])
        self.assertGreater(result['data']['entries'][0]['publishedAt'],old)
        weekly=self.call('/api/weekly','POST',dict(track=TRACK,text=''))['data']['weekly']['postId']
        self.assertEqual(self.call('/api/republish','POST',dict(post=weekly))['status'],404)
        self.assertEqual(self.call('/api/republish','POST',dict(post='missing'))['status'],404)

    def test_upgrade_does_not_reset_old_posts_to_today(self):
        self.register();self.register('b')
        self.save([dict(id='kept-old',track=TRACK,text='Lembrança antiga',visibility='public')]);old=self.age('kept-old',48)
        with self.app.db.transaction() as db:db.execute('ALTER TABLE posts DROP COLUMN feed_published_at')
        self.app=Application(self.app.db.source,production=False)
        state=self.call('/api/bootstrap')['data']
        self.assertEqual(state['entries'][0]['publishedAt'],old)
        self.assertEqual(self.call('/api/bootstrap',actor='b')['data']['publicPosts'],[])
        self.assertEqual(self.call('/api/post?id=kept-old')['status'],200)


def load_tests(loader,tests,pattern):
    return unittest.TestSuite(FeedLifetime(name) for name in (
        'test_older_posts_leave_feed_but_remain_on_profile_and_links',
        'test_republication_requires_an_actual_edit',
        'test_editing_does_not_renew_and_publication_time_cannot_be_forged',
        'test_upgrade_does_not_reset_old_posts_to_today'))
