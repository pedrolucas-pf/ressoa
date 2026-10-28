"""The deployed source starts empty and never includes local accounts or diaries."""
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from test_accounts import Accounts
from scripts.package_release import package
from webapp import Application


class Release(Accounts):
    def test_new_database_starts_without_accounts_or_posts(self):
        with self.app.db.connect() as db:
            for table in ('users','posts','actions','follows','weekly','shares'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0,table)
        state=self.register()
        for key in ('entries','publicPosts','saved','followingPeople','followersPeople','followRequests'):
            self.assertEqual(state[key],[],key)
        self.assertIsNone(state['weekly'])
        self.assertEqual(self.call('/lyric-picker.js')['status'],200)
        self.assertEqual(self.call('/assets/vinyl-ambience.jpg')['status'],200)

    def test_release_contains_runtime_without_local_data(self):
        archive=package(Path(self.directory.name)/'release.zip')
        with ZipFile(archive) as release:
            names=set(release.namelist())
            self.assertTrue({'web/index.html','web/app.js','web/post-art.js','web/lyric-picker.js','web/assets/login-artwork.json','web/assets/vinyl-ambience.jpg','Dockerfile','webapp.py'}<=names)
            self.assertFalse(any(name.startswith(('storage/','scripts/','tests/','local_archive/','verification/','.git/')) for name in names))
            self.assertNotIn('CHECKPOINT.md',names)
            self.assertNotIn('export const posts',release.read('web/data.js').decode())

    def test_production_refuses_ephemeral_sqlite_fallback(self):
        with patch.dict(os.environ,{'APP_ORIGIN':'https://ressoa.example','DATABASE_URL':'','DATABASE_PATH':str(Path(self.directory.name)/'unused.sqlite3')}):
            with self.assertRaisesRegex(RuntimeError,'DATABASE_URL'):
                Application(production=True)


def load_tests(loader,tests,pattern):
    return unittest.TestSuite(Release(name) for name in Release.__dict__ if name.startswith('test_'))
