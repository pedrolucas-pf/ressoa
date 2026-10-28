"""Only authors can see the combined list of real likes and reposts."""
import unittest
from test_accounts import Accounts,TRACK


class Interactions(Accounts):
    def test_combined_people_are_unique_and_show_each_action(self):
        self.register()
        users={actor:self.register(actor)['user']['id'] for actor in ('b','c','d')}
        post=dict(id='combined-post',track=TRACK,text='Saudade',visibility='public')
        self.assertEqual(self.save([post])['status'],200)
        for actor,kind in (('b','like'),('b','repost'),('c','repost'),('d','like'),('c','saved')):
            self.assertEqual(self.call('/api/action','POST',dict(kind=kind,target=post['id'],active=True),actor)['status'],200)
        result=self.call('/api/interactions?post=combined-post')
        self.assertEqual(result['status'],200)
        people={person['id']:person for person in result['data']['people']}
        self.assertEqual(len(result['data']['people']),3)
        self.assertEqual((people[users['b']]['liked'],people[users['b']]['reposted']),(True,True))
        self.assertEqual((people[users['c']]['liked'],people[users['c']]['reposted']),(False,True))
        self.assertEqual((people[users['d']]['liked'],people[users['d']]['reposted']),(True,False))
        self.assertTrue(all(set(person)=={'id','displayName','handle','photo','liked','reposted'} for person in people.values()))
        self.call('/api/action','POST',dict(kind='repost',target=post['id'],active=False),'b')
        people={person['id']:person for person in self.call('/api/interactions?post=combined-post')['data']['people']}
        self.assertTrue(people[users['b']]['liked']);self.assertFalse(people[users['b']]['reposted'])
        self.call('/api/action','POST',dict(kind='like',target=post['id'],active=False),'b')
        self.assertEqual(len(self.call('/api/interactions?post=combined-post')['data']['people']),2)
        self.assertNotIn('likeCount',self.call('/api/bootstrap',actor='b')['data']['publicPosts'][0])

    def test_author_only_private_missing_and_deleted_posts(self):
        self.register();self.register('b')
        post=dict(id='protected-post',track=TRACK,text='Meu lugar',visibility='public')
        result=self.save([post]);self.assertEqual(result['status'],200)
        self.assertEqual(self.call('/api/interactions?post=protected-post',actor='anonymous')['status'],401)
        self.assertEqual(self.call('/api/interactions?post=protected-post',actor='b')['status'],403)
        self.assertEqual(self.call('/api/interactions?post=protected-post')['data']['people'],[])
        self.call('/api/action','POST',dict(kind='repost',target=post['id'],active=True),'b')
        result=self.save([dict(post,visibility='private')],version=result['data']['versions']['entries'])
        self.assertEqual(result['status'],200)
        self.assertEqual(self.call('/api/interactions?post=protected-post',actor='b')['status'],404)
        self.assertEqual(self.call('/api/interactions?post=protected-post')['data']['people'],[])
        result=self.save([],version=result['data']['versions']['entries']);self.assertEqual(result['status'],200)
        self.assertEqual(self.call('/api/interactions?post=protected-post')['status'],404)
        self.assertEqual(self.call('/api/interactions?post=missing')['status'],404)

    def test_weekly_interactions_follow_the_weekly_lifetime(self):
        self.register();self.register('b')
        result=self.call('/api/weekly','POST',dict(track=TRACK,text=''))
        identifier=result['data']['weekly']['postId']
        self.call('/api/action','POST',dict(kind='repost',target=identifier,active=True),'b')
        result=self.call('/api/interactions?post='+identifier);self.assertEqual(result['status'],200)
        self.assertEqual(len(result['data']['people']),1);self.assertTrue(result['data']['people'][0]['reposted'])
        self.call('/api/weekly','DELETE',{})
        self.assertEqual(self.call('/api/interactions?post='+identifier)['status'],404)


def load_tests(loader,tests,pattern):
    return unittest.TestSuite(Interactions(name) for name in (
        'test_combined_people_are_unique_and_show_each_action',
        'test_author_only_private_missing_and_deleted_posts',
        'test_weekly_interactions_follow_the_weekly_lifetime'))
