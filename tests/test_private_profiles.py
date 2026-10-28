"""Private accounts protect every content route, including reposts and shared links."""
import unittest
from webapp import Application
from test_accounts import Accounts,TRACK


class PrivateProfiles(Accounts):
    def privacy(self,private,actor='a'):
        state=self.call('/api/bootstrap',actor=actor)['data']
        return self.call('/api/profile','PUT',dict(value=dict(state['profile'],isPrivate=private),version=state['versions']['profile']),actor)

    def follow(self,target,actor='b',active=True):
        return self.call('/api/action','POST',dict(kind='follow',target=target,active=active),actor)

    def test_requests_approval_rejection_cancel_and_removal(self):
        a=self.register();b=self.register('b');self.register('c')
        self.save([dict(id='private-owner-post',track=TRACK,text='Meu texto',visibility='public')])
        self.assertEqual(self.privacy(True)['status'],200)
        target=a['user']['id'];requester=b['user']['id']
        self.assertEqual(self.call('/api/bootstrap',actor='b')['data']['publicPosts'],[])
        locked=self.call('/api/profile?user='+target,actor='b')['data']
        self.assertFalse(locked['canView']);self.assertEqual(locked['entries'],[])
        self.assertEqual(self.call('/api/post?id=private-owner-post',actor='b')['status'],404)
        for action in ('like','repost','saved'):
            self.assertEqual(self.call('/api/action','POST',dict(kind=action,target='private-owner-post',active=True),'b')['status'],404)
        for _ in range(2):self.assertEqual(self.follow(target)['status'],200)
        state=self.call('/api/bootstrap',actor='b')['data']
        self.assertEqual(state['social']['requested'],[target]);self.assertEqual(state['social']['following'],[])
        self.assertEqual(len(self.call('/api/follow-requests')['data']['people']),1)
        self.assertEqual(self.call('/api/follow-request','POST',dict(requester=requester,accept=True),'c')['status'],404)
        self.assertEqual(self.call('/api/follow-request','POST',dict(requester=requester,accept='yes'))['status'],400)
        self.assertEqual(self.call('/api/follow-request','POST',dict(requester=requester,accept=False))['status'],200)
        self.assertEqual(self.call('/api/bootstrap',actor='b')['data']['social']['requested'],[])
        self.follow(target);self.follow(target,active=False)
        self.assertEqual(self.call('/api/follow-requests')['data']['people'],[])
        self.follow(target)
        self.assertEqual(self.call('/api/follow-request','POST',dict(requester=requester,accept=True))['status'],200)
        unlocked=self.call('/api/profile?user='+target,actor='b')['data']
        self.assertTrue(unlocked['canView']);self.assertEqual(len(unlocked['entries']),1)
        self.assertEqual(self.call('/api/post?id=private-owner-post',actor='b')['status'],200)
        self.assertEqual(len(self.call('/api/bootstrap',actor='b')['data']['publicPosts']),1)
        # Another account cannot remove A's approved follower.
        self.call('/api/follower','DELETE',dict(user=requester),'c')
        self.assertEqual(self.call('/api/post?id=private-owner-post',actor='b')['status'],200)
        self.call('/api/follower','DELETE',dict(user=requester))
        self.assertEqual(self.call('/api/post?id=private-owner-post',actor='b')['status'],404)
        self.assertEqual(self.call('/api/bootstrap',actor='b')['data']['publicPosts'],[])

    def test_reposts_weekly_saved_and_interactions_do_not_bypass_privacy(self):
        a=self.register();b=self.register('b');self.register('c')
        self.save([dict(id='source-private',track=TRACK,text='Texto protegido',visibility='public')])
        self.follow(a['user']['id'])
        self.call('/api/action','POST',dict(kind='repost',target='source-private',active=True),'b')
        self.call('/api/action','POST',dict(kind='saved',target='source-private',active=True),'b')
        self.privacy(True)
        target=b['user']['id']
        self.assertEqual(self.call('/api/profile?user='+target,actor='c')['data']['reposts'],[])
        self.assertEqual(len(self.call('/api/profile?user='+target,actor='a')['data']['reposts']),1)
        self.call('/api/follower','DELETE',dict(user=target))
        hidden=self.call('/api/bootstrap',actor='b')['data']
        self.assertEqual(hidden['saved'],[]);self.assertEqual(hidden['social']['reposts'],[])
        weekly=self.call('/api/weekly','POST',dict(track=TRACK))['data']['weekly']['postId']
        self.assertEqual(self.call('/api/post?id='+weekly,actor='b')['status'],404)
        # A private reposter is not revealed through the original author's list.
        self.save([dict(id='other-public',track=TRACK,text='Texto aberto',visibility='public')],actor='c')
        self.call('/api/action','POST',dict(kind='repost',target='other-public',active=True))
        self.assertEqual(self.call('/api/interactions?post=other-public',actor='c')['data']['people'],[])
        self.assertEqual(self.call('/api/profile?user='+a['user']['id'],actor='c')['data']['reposts'],[])

    def test_public_transition_preserves_followers_and_accepts_pending_requests(self):
        a=self.register();self.register('b');self.register('c');target=a['user']['id']
        self.follow(target)
        self.privacy(True);self.follow(target,actor='c')
        self.assertTrue(self.call('/api/profile?user='+target,actor='b')['data']['canView'])
        self.assertEqual(self.call('/api/profile?user='+target,actor='c')['data']['followState'],'requested')
        self.privacy(False)
        state=self.call('/api/bootstrap',actor='c')['data']
        self.assertIn(target,state['social']['following']);self.assertEqual(state['social']['requested'],[])
        self.assertEqual(self.call('/api/follow-requests')['data']['people'],[])
        state=self.call('/api/bootstrap')['data']
        result=self.call('/api/profile','PUT',dict(value=dict(state['profile'],isPrivate='true'),version=state['versions']['profile']))
        self.assertEqual(result['status'],400)

    def test_existing_database_migrates_without_losing_accounts_or_posts(self):
        state=self.register();self.save([dict(id='kept-post',track=TRACK,text='Preservado',visibility='public')])
        with self.app.db.transaction() as db:
            db.execute('DROP TABLE follow_requests')
            db.execute('ALTER TABLE posts DROP COLUMN lyric_excerpt')
            db.execute('ALTER TABLE users DROP COLUMN is_private')
        source=self.app.db.source;self.app=Application(source,production=False);self.app=Application(source,production=False)
        result=self.call('/api/bootstrap');self.assertEqual(result['status'],200)
        self.assertEqual(result['data']['user']['id'],state['user']['id'])
        self.assertFalse(result['data']['profile']['isPrivate']);self.assertEqual(result['data']['entries'][0]['id'],'kept-post')
        self.assertEqual(result['data']['entries'][0]['lyricExcerpt'],'')


def load_tests(loader,tests,pattern):
    return unittest.TestSuite(PrivateProfiles(name) for name in (
        'test_requests_approval_rejection_cancel_and_removal',
        'test_reposts_weekly_saved_and_interactions_do_not_bypass_privacy',
        'test_public_transition_preserves_followers_and_accepts_pending_requests',
        'test_existing_database_migrates_without_losing_accounts_or_posts'))
