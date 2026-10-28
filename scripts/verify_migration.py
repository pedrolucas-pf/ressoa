"""Migration/rollback/parameter tests against the loopback-only test PostgreSQL."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import tempfile
from unittest.mock import patch
from database import Database
from scripts.verification_support import verification_source
from migrate_to_neon import migrate
from postgres_storage import PostgresConnection

TRACK=dict(catalogId='deezer:543138072',provider='deezer',title='Azul Da Cor Do Mar',artist='Tim Maia',album='Tim Maia 1970',duration=198)


def main():
    checks=[]
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'original.sqlite3';source=Database(path)
        a=source.register(dict(email='a@example.com',username='person_a',displayName='Pessoa A',password='test-password-123'))
        b=source.register(dict(email='b@example.com',username='person_b',displayName='Pessoa B',password='test-password-123'))
        source.save_entries(a,dict(version=0,value=[dict(id='post-'+str(index),track=TRACK,text='Meu comentário com acentos, saudade e música. '+str(index),visibility='private' if index==0 else 'public',lyricExcerpt='Verso inventado para testar a migração.' if index==1 else '') for index in range(120)]))
        source.save_profile(a,dict(version=0,value=dict(displayName='Pessoa A',handle='person_a',bio='Uma bio que será preservada.',photo='',favorites=[TRACK],background=TRACK,pinned=['post-1'])))
        source.choose_weekly(a,dict(track=TRACK,text='Um destaque independente do diário.'))
        source.delete_weekly(a)
        source.preference(a,dict(key='draft',value=dict(text='Um rascunho não publicado.',track=TRACK,visibility='private')))
        source.action(b,'follow',a,True)
        state=source.bootstrap(a)
        source.save_entries(a,dict(version=state['versions']['entries'],value=[dict(post,text=post['text']+'!') if post['id']=='post-1' else post for post in state['entries']],republish='post-1'))
        for kind in ('like','repost','saved'):source.action(b,kind,'post-1',True)
        with source.transaction() as db:db.execute('INSERT INTO shares VALUES (?,?,?,?)',(b,'post-1','link','2026-01-01T00:00:00+00:00'))
        state=source.bootstrap(a);source.save_profile(a,dict(version=state['versions']['profile'],value=dict(state['profile'],isPrivate=True)))
        # B remains approved; A's request to private B stays pending during migration.
        state=source.bootstrap(b);source.save_profile(b,dict(version=state['versions']['profile'],value=dict(state['profile'],isPrivate=True)))
        source.action(a,'follow',b,True)
        source.create_session(a,True)
        before_a=source.bootstrap(a);before_b=source.bootstrap(b)
        target=Database(verification_source(Path(directory)/'unused.sqlite3'))
        if not target.is_postgres:raise RuntimeError('Use python scripts/verify_postgres.py --migration-only; never run against a remote database.')
        result=migrate(path,target)
        assert result['mode']=='check' and result['can_apply']
        with target.connect() as db:assert db.execute('SELECT count(*) FROM users').fetchone()[0]==0
        result=migrate(path,target,True)
        assert result['mode']=='applied' and result['source_unchanged']
        assert target.bootstrap(a)==before_a and target.bootstrap(b)==before_b
        assert target.interactions(a,'post-1')==source.interactions(a,'post-1')
        assert 'shared' not in target.interactions(a,'post-1')[0]
        with target.connect() as db:assert db.execute('SELECT count(*) FROM shares').fetchone()[0]==1
        assert source.bootstrap(a)==before_a
        assert target.login(dict(identifier='person_a',password='test-password-123'))==a
        with target.connect() as db:assert db.execute('SELECT count(*) FROM sessions').fetchone()[0]==0
        checks.append('dry-run copies no records; apply preserves account IDs, password login, privacy, comments, profile, draft, deleted-week lock and social relations; source unchanged; sessions omitted')
        try:migrate(path,target,True)
        except ValueError:pass
        else:raise AssertionError('A populated destination must never be overwritten.')
        assert target.bootstrap(a)==before_a
        checks.append('migration refuses a populated destination without changing its records')
        broken=Database(verification_source(Path(directory)/'unused2.sqlite3'))
        with broken.connect() as db:db.execute('ALTER TABLE posts ADD COLUMN unexpected TEXT')
        try:migrate(path,broken,True)
        except ValueError:pass
        else:raise AssertionError('Incompatible schema should roll back the migration.')
        with broken.connect() as db:
            assert db.execute('SELECT count(*) FROM users').fetchone()[0]==0
            assert db.execute('SELECT count(*) FROM tracks').fetchone()[0]==0
        checks.append('incompatible target schema rolls back previously copied rows atomically')
        with target.connect() as db:
            value="a?%'; DROP TABLE users; --"
            row=db.execute("SELECT '?%' AS literal, ? AS value",(value,)).fetchone()
            assert row['literal']=='?%' and row['value']==value
            assert db.execute('SELECT count(*) FROM users').fetchone()[0]==2
        checks.append('question marks and percent signs remain parameterized safely, including quoted SQL literals')
        count=0;original=PostgresConnection.execute
        def counted(self,*args,**kwargs):
            nonlocal count
            count+=1;return original(self,*args,**kwargs)
        with patch.object(PostgresConnection,'execute',counted):target.bootstrap(b)
        assert count<=25,count
        checks.append('bootstrap batches authors/tracks instead of making a query for every post')
    report=dict(result='PASS',checks=checks,bootstrap_queries=count,source='synthetic SQLite',target='disposable loopback PostgreSQL')
    root=Path(__file__).resolve().parents[1]
    (root/'verification'/'migration-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
