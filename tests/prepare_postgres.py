"""Download official portable PostgreSQL test tools; never install a Windows service."""
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile
import shutil

ROOT=Path(__file__).resolve().parents[1]
TOOLS=ROOT/'.tools'/'postgres'
URL='https://get.enterprisedb.com/postgresql/postgresql-17.11-3-windows-x64-binaries.zip'


def prepare():
    binary=TOOLS/'pgsql'/'bin'/'postgres.exe'
    if binary.is_file():
        print('Portable PostgreSQL already available.');return
    TOOLS.mkdir(parents=True,exist_ok=True)
    archive=TOOLS/'postgresql-official.zip'
    with urlopen(URL,timeout=60) as response,archive.open('wb') as output:
        shutil.copyfileobj(response,output)
    count=0
    with ZipFile(archive) as package:
        for entry in package.infolist():
            parts=Path(entry.filename).parts
            if len(parts)<3 or parts[0]!='pgsql' or parts[1] not in ('bin','lib','share') or entry.filename.endswith(('.pdb','.debug')):
                continue
            destination=(TOOLS/entry.filename).resolve()
            if not destination.is_relative_to(TOOLS.resolve()):
                raise RuntimeError('Invalid archive path.')
            if entry.is_dir():
                destination.mkdir(parents=True,exist_ok=True);continue
            destination.parent.mkdir(parents=True,exist_ok=True)
            with package.open(entry) as source,destination.open('wb') as output:
                shutil.copyfileobj(source,output)
            count+=1
    if not binary.is_file():raise RuntimeError('PostgreSQL executable missing.')
    archive.unlink()
    print(f'Portable PostgreSQL ready: {count} runtime files. No service installed.')


if __name__=='__main__':prepare()
