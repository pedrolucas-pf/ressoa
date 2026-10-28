"""Editing resets reactions; optional feed republication commits in the same transaction."""
import unittest
from datetime import datetime,timedelta,timezone
from test_accounts import Accounts,TRACK


class Editing(Accounts):
    def seed(self):
        self.register();self.register('b');self.register('c')
        self.items=[dict(id=key,track=TRACK,text='Texto original.',visibility='public') for key in ('edited','untouched')]
        result=self.save(self.items)
        self.version=result['data']['versions']['entries']
        self.old=(datetime.now(timezone.utc)-timedelta(hours=30)).isoformat()
        with self.app.db.transaction() as db:
            db.execute('UPDATE posts SET feed_published_at=? WHERE id=?',(self.old,'edited'))
        for actor in ('b','c'):
            for key in ('edited','untouched'):
                for kind in ('like','repost','saved'):
                    self.assertEqual(self.call('/api/action','POST',dict(kind=kind,target=key,active=True),actor)['status'],200)

    def edit(self,**extra):
        return self.call('/api/entries','PUT',dict(value=[dict(self.items[0],text='Um novo sentido.'),self.items[1]],version=self.version,**extra))

    def assert_actions(self,edited):
        for actor in ('b','c'):
            state=self.call('/api/bootstrap',actor=actor)['data']
            for kind in ('likes','reposts'):
                self.assertEqual('edited' in state['social'][kind],edited)
                self.assertIn('untouched',state['social'][kind])
            self.assertIn('edited',state['saved'])

    def test_edit_without_republishing_clears_only_edited_reactions(self):
        self.seed();before=self.call('/api/post?id=edited')['data']['post']
        result=self.edit();self.assertEqual(result['status'],200)
        self.assert_actions(False)
        after=self.call('/api/post?id=edited')['data']['post']
        self.assertEqual(after['publishedAt'],self.old)
        self.assertEqual(after['createdAt'],before['createdAt'])
        self.assertEqual(after['text'],'Um novo sentido.')
        self.register('d')
        self.assertNotIn('edited',{post['id'] for post in self.call('/api/bootstrap',actor='d')['data']['publicPosts']})
        self.assertEqual(self.call('/api/interactions?post=edited')['data']['people'],[])

    def test_edit_and_republish_are_atomic_and_keep_identity(self):
        self.seed();before=self.call('/api/post?id=edited')['data']['post']
        result=self.edit(republish='edited');self.assertEqual(result['status'],200)
        self.assert_actions(False)
        after=self.call('/api/post?id=edited')['data']['post']
        self.assertEqual(after['id'],before['id']);self.assertEqual(after['createdAt'],before['createdAt'])
        self.assertGreater(after['publishedAt'],self.old);self.assertEqual(after['text'],'Um novo sentido.')
        self.assertIn('edited',{post['id'] for post in self.call('/api/bootstrap',actor='b')['data']['publicPosts']})
        self.assertEqual(len(result['data']['entries']),2)

    def test_unchanged_bulk_save_preserves_interactions(self):
        self.seed();self.assertEqual(self.save(self.items,version=self.version)['status'],200)
        self.assert_actions(True)
        self.assertEqual(self.call('/api/post?id=edited')['data']['post']['publishedAt'],self.old)

    def test_invalid_target_and_stale_version_roll_back_the_whole_edit(self):
        self.seed()
        for target in ('missing','untouched',True,{'id':'edited'}):
            self.assertEqual(self.edit(republish=target)['status'],400)
            self.assert_actions(True)
            state=self.call('/api/bootstrap')['data']
            self.assertEqual(state['versions']['entries'],self.version)
            self.assertEqual(next(post for post in state['entries'] if post['id']=='edited')['text'],'Texto original.')
        self.assertEqual(self.call('/api/entries','PUT',dict(value=self.items,version=-1,republish='edited'))['status'],409)
        self.assert_actions(True)

    def test_private_and_new_posts_cannot_be_republished_through_edit(self):
        self.seed()
        private=[dict(self.items[0],visibility='private'),self.items[1]]
        self.assertEqual(self.call('/api/entries','PUT',dict(value=private,version=self.version,republish='edited'))['status'],400)
        self.assert_actions(True)
        new=[*self.items,dict(id='brand-new',track=TRACK,text='Nova.',visibility='public')]
        self.assertEqual(self.call('/api/entries','PUT',dict(value=new,version=self.version,republish='brand-new'))['status'],400)
        self.assertEqual(self.call('/api/post?id=brand-new')['status'],404)


def load_tests(loader,tests,pattern):
    return unittest.TestSuite(Editing(name) for name in Editing.__dict__ if name.startswith('test_'))
