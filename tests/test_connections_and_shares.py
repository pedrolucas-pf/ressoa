"""Connection visibility and exclusion of sharing identities."""
import unittest
from test_accounts import Accounts,TRACK
from webapp import Application


class ConnectionsAndShares(Accounts):
    def private(self,actor):
        state=self.call('/api/bootstrap',actor=actor)['data']
        return self.call('/api/profile','PUT',dict(version=state['versions']['profile'],value=dict(state['profile'],isPrivate=True)),actor)

    def test_connections_require_following_a_public_profile(self):
        a=self.register()['user']['id'];b=self.register('b')['user']['id']
        query='/api/connections?user='+a+'&kind=followers'
        self.assertEqual(self.call(query,actor='anonymous')['status'],401)
        self.assertEqual(self.call(query,actor='b')['status'],403)
        self.assertEqual(self.call(query)['status'],200)
        self.call('/api/action','POST',dict(kind='follow',target=a,active=True),'b')
        self.assertEqual([person['id'] for person in self.call(query,actor='b')['data']['people']],[b])
        profile=self.call('/api/profile?user='+a,actor='b')['data'];self.assertTrue(profile['canViewRelations'])
        self.assertTrue(all(set(person)=={'id','displayName','handle','photo'} for person in self.call(query,actor='b')['data']['people']))
        self.private('a')
        profile=self.call('/api/profile?user='+a,actor='b')['data'];self.assertTrue(profile['canView']);self.assertFalse(profile['canViewRelations'])
        self.assertEqual(self.call(query,actor='b')['status'],403)
        self.assertEqual(self.call(query)['status'],200)
        self.assertEqual(self.call('/api/connections?user=missing&kind=followers')['status'],404)
        self.assertEqual(self.call('/api/connections?user='+a+'&kind=invalid')['status'],400)

    def test_private_connections_are_filtered_and_unfollow_revokes_access(self):
        a=self.register()['user']['id'];b=self.register('b')['user']['id'];c=self.register('c')['user']['id'];d=self.register('d')['user']['id']
        for target in (c,d):self.call('/api/action','POST',dict(kind='follow',target=target,active=True))
        self.private('c');self.call('/api/action','POST',dict(kind='follow',target=a,active=True),'b')
        query='/api/connections?user='+a+'&kind=following'
        self.assertEqual({person['id'] for person in self.call(query,actor='b')['data']['people']},{d})
        self.assertEqual({person['id'] for person in self.call(query)['data']['people']},{c,d})
        self.call('/api/action','POST',dict(kind='follow',target=c,active=True),'b')
        self.assertEqual({person['id'] for person in self.call(query,actor='b')['data']['people']},{d})
        self.call('/api/follow-request','POST',dict(requester=b,accept=True),'c')
        self.assertEqual({person['id'] for person in self.call(query,actor='b')['data']['people']},{c,d})
        self.call('/api/action','POST',dict(kind='follow',target=a,active=False),'b')
        self.assertEqual(self.call(query,actor='b')['status'],403)

    def test_only_likes_and_reposts_are_exposed_and_new_tracking_is_disabled(self):
        self.register();b=self.register('b')['user']['id'];c=self.register('c')['user']['id']
        result=self.save([dict(id='shared',track=TRACK,text='Saudade',visibility='public')])
        for kind in ('like','repost'):self.call('/api/action','POST',dict(kind=kind,target='shared',active=True),'b')
        # Legacy records remain archived, but must not reveal identities or flags.
        with self.app.db.transaction() as db:
            for user in (b,c):db.execute('INSERT INTO shares VALUES (?,?,?,?)',(user,'shared','link','2026-01-01T00:00:00+00:00'))
        people=self.call('/api/interactions?post=shared')['data']['people']
        self.assertEqual(len(people),1);self.assertEqual(people[0]['id'],b)
        self.assertTrue(people[0]['liked'] and people[0]['reposted']);self.assertNotIn('shared',people[0])
        self.assertEqual(self.call('/api/interactions?post=shared',actor='b')['status'],403)
        self.assertEqual(self.call('/api/share','POST',dict(post='shared',method='native'),actor='anonymous')['status'],401)
        for method in ('native','link','download','open','cancel',None):
            self.assertEqual(self.call('/api/share','POST',dict(post='shared',method=method),'b')['status'],404)
        result=self.save([dict(id='shared',track=TRACK,text='Mudou.',visibility='public')],version=result['data']['versions']['entries'])
        self.assertEqual(self.call('/api/interactions?post=shared')['data']['people'],[])

    def test_upgrade_preserves_posts_without_exposing_legacy_share_history(self):
        self.register();b=self.register('b')['user']['id']
        self.save([dict(id='kept',track=TRACK,text='Meu texto',visibility='public')])
        self.call('/api/action','POST',dict(kind='like',target='kept',active=True),'b')
        with self.app.db.transaction() as db:db.execute('DROP TABLE shares')
        self.app=Application(self.app.db.source,production=False)
        with self.app.db.transaction() as db:db.execute('INSERT INTO shares VALUES (?,?,?,?)',(b,'kept','link','2026-01-01T00:00:00+00:00'))
        self.app=Application(self.app.db.source,production=False)
        person=self.call('/api/interactions?post=kept')['data']['people'][0]
        self.assertTrue(person['liked']);self.assertNotIn('shared',person)
        self.assertEqual(self.call('/api/post?id=kept')['data']['post']['text'],'Meu texto')


def load_tests(loader,tests,pattern):
    return unittest.TestSuite(ConnectionsAndShares(name) for name in ConnectionsAndShares.__dict__ if name.startswith('test_'))
