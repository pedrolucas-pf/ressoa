"""Package production source only, without local accounts, examples or secrets."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
NAMES=('Dockerfile','.dockerignore','render.yaml','requirements.txt','gunicorn.conf.py',
       'database.py','postgres_storage.py','webapp.py','services.py','README.md',
       'docs/DEPLOY.md','.env.example')


def package(destination=None):
    destination=Path(destination or ROOT/'verification'/'ressoa-release.zip')
    destination.parent.mkdir(parents=True,exist_ok=True)
    files=[*(ROOT/name for name in NAMES),*(file for file in (ROOT/'web').rglob('*') if file.is_file())]
    for file in files:
        if not file.is_file() or file.is_symlink():raise RuntimeError('Invalid release source: '+file.name)
    with ZipFile(destination,'w',ZIP_DEFLATED) as archive:
        for file in sorted(files):archive.write(file,file.relative_to(ROOT).as_posix())
    with ZipFile(destination) as archive:
        if archive.testzip() is not None:raise RuntimeError('Invalid release archive.')
        for name in archive.namelist():
            if name.startswith(('storage/','.tools/','.git/','local_archive/','verification/')) or name.endswith(('.sqlite3','.sqlite3-wal','.sqlite3-shm')) or name=='.env':
                raise RuntimeError('Private file in release archive.')
    return destination


if __name__=='__main__':print(package())
