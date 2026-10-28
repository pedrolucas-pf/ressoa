import json
import unittest
from urllib.parse import quote
from test_accounts import Accounts,TRACK
from database import now_iso


class People(Accounts):
    def pair(self):
        a=self.register('a');b=self.register('b')
        info=dict(b['profile'],displayName='João da Silva',handle='joao_silva',bio='Música para guardar histórias.',favorites=[TRACK],background=TRACK)
        result=self.call('/api/profile','PUT',dict(value=info,version=0),'b')
        self.assertEqual(result['status'],200,result)
        return a,b

    def test_search_by_name_handle_and_accent_without_private_fields(self):
        a,b=self.pair()
        for query in ('joao','JOÃO','@joao_silva','silva'):
            result=self.call('/api/people?q='+quote(query))
            self.assertEqual(result['status'],200,result)
            self.assertEqual(result['data']['people'][0]['id'],b['user']['id'])
            self.assertEqual(set(result['data']['people'][0]),{'id','displayName','handle','photo'})
            self.assertNotIn('b@example.com',json.dumps(result['data']))
        self.assertEqual(self.call('/api/people?q=%25_')['data']['people'],[])
        self.assertEqual(self.call('/api/people?q=x')['status'],400)
        self.assertEqual(self.call('/api/people?q=joao',actor='anonymous')['status'],401)

    def test_public_profile_paginates_and_never_exposes_private_data(self):
        a,b=self.pair();identifier=b['user']['id']
        items=[dict(id=f'public-{i:02}',track=TRACK,text=f'Um comentário público sobre esta música, registro {i}.',visibility='public') for i in range(28)]
        items.append(dict(id='private-secret-id',track=TRACK,text='PRIVATE DIARY CONTENT SHOULD NEVER LEAK',visibility='private'))
        self.assertEqual(self.save(items,actor='b')['status'],200)
        with self.app.db.transaction() as db:
            db.execute('UPDATE users SET pinned=?,draft=? WHERE id=?',(json.dumps(['public-00','private-secret-id']),json.dumps({'text':'PRIVATE DRAFT SHOULD NEVER LEAK'}),identifier))
        self.call('/api/weekly','POST',dict(track=TRACK,text='O destaque público da semana de João.'),'b')
        result=self.call('/api/profile?user='+identifier)
        self.assertEqual(result['status'],200,result);data=result['data']
        self.assertEqual(data['profile']['handle'],'joao_silva');self.assertEqual(data['profile']['pinned'],['public-00'])
        self.assertEqual(data['entries'][0]['id'],'public-00');self.assertEqual(len(data['entries']),24)
        self.assertEqual(data['nextEntriesOffset'],24);self.assertEqual(data['weekly']['visibility'],'public')
        next_page=self.call('/api/profile?user='+identifier+'&offset=24')['data']
        self.assertEqual(len(next_page['entries']),4);self.assertIsNone(next_page['nextEntriesOffset'])
        self.assertEqual(len({post['id'] for post in data['entries']+next_page['entries']}),28)
        serialized=json.dumps(data)
        for secret in ('b@example.com','password_hash','sessions','PRIVATE','private-secret-id','draft','seen'):
            self.assertNotIn(secret,serialized)
        original=self.call('/api/bootstrap',actor='b')['data'];self.assertEqual(len(original['entries']),29)
        self.assertEqual(self.call('/api/profile?user='+identifier,actor='anonymous')['status'],401)

    def test_profile_reposts_filter_private_and_expired_weekly_posts(self):
        a,b=self.pair();c=self.register('c')
        source=[dict(id='public-original',track=TRACK,text='O comentário original público para repostar.',visibility='public'),dict(id='private-original',track=TRACK,text='Um comentário original privado e indisponível.',visibility='private')]
        self.save(source,actor='c')
        self.call('/api/action','POST',dict(kind='repost',target='public-original',active=True),'b')
        active=self.call('/api/weekly','POST',dict(track=TRACK,text='Um destaque ativo para repostar.'),actor='c')['data']['weekly']['postId']
        newer=[dict(id=f'newer-{index}',track=TRACK,text=f'Um registro mais recente {index}.',visibility='public') for index in range(130)]
        self.save(source+newer,version=1,actor='c')
        self.assertNotIn(active,{post['id'] for post in self.call('/api/bootstrap',actor='b')['data']['publicPosts']})
        self.call('/api/action','POST',dict(kind='repost',target=active,active=True),'b')
        self.assertIn(active,{post['id'] for post in self.call('/api/bootstrap',actor='b')['data']['publicPosts']})
        with self.app.db.transaction() as db:
            db.execute("INSERT INTO actions VALUES (?,?,'repost')",(b['user']['id'],'private-original'))
            db.execute("INSERT INTO posts (id,owner_id,track_id,text,visibility,kind,created_at,updated_at) VALUES (?,?,?,?,'public','weekly',?,?)",('old-weekly',c['user']['id'],TRACK['catalogId'],'Um destaque de uma semana que já terminou.',now_iso(),now_iso()))
            db.execute('INSERT INTO weekly VALUES (?,?,?,?,NULL)',(c['user']['id'],'2020-01-06','old-weekly',now_iso()))
            db.execute("INSERT INTO actions VALUES (?,?,'repost')",(b['user']['id'],'old-weekly'))
        result=self.call('/api/profile?user='+b['user']['id'])['data']
        self.assertEqual({post['id'] for post in result['reposts']},{'public-original',active})
        self.assertEqual(result['reposts'][0]['ownerId'],c['user']['id'])

    def test_missing_profile_and_unchanged_owner_permissions(self):
        a,b=self.pair();self.save([dict(id='other-post',track=TRACK,text='Um comentário que pertence somente à outra pessoa.',visibility='public')],actor='b')
        self.assertEqual(self.call('/api/profile?user=missing')['status'],404)
        self.assertEqual(self.call('/api/profile?user='+b['user']['id']+'&offset=-1')['status'],400)
        self.assertEqual(self.call('/api/profile?user='+b['user']['id']+'&offset=6000')['status'],400)
        self.assertEqual(self.save([dict(id='other-post',track=TRACK,text='Tentativa indevida de alterar outra pessoa.',visibility='public')])['status'],403)
        self.assertEqual(self.call('/api/likes?post=other-post')['status'],403)
        self.assertEqual(self.call('/api/bootstrap')['data']['profile']['handle'],'user_a')


def load_tests(loader,tests,pattern):
    return unittest.TestSuite(People(name) for name in (
        'test_search_by_name_handle_and_accent_without_private_fields','test_public_profile_paginates_and_never_exposes_private_data',
        'test_profile_reposts_filter_private_and_expired_weekly_posts','test_missing_profile_and_unchanged_owner_permissions'))
