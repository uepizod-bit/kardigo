"""Fetch large upstream assets excluded from Git. Verify against imported release hashes."""
import argparse, hashlib, json, shutil, urllib.request, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def download(url, path, sha):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==sha:return
    temp=path.with_suffix(path.suffix+'.download')
    try:
        with urllib.request.urlopen(url,timeout=180) as src, temp.open('wb') as dst:shutil.copyfileobj(src,dst)
        if hashlib.sha256(temp.read_bytes()).hexdigest()!=sha:raise RuntimeError('SHA256 mismatch: '+str(path))
        temp.replace(path)
    finally:temp.unlink(missing_ok=True)
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--all',action='store_true');args=parser.parse_args()
    manifest=json.loads((ROOT/'ci/large_assets.json').read_text())
    for row in manifest['whisper']:
        download(row['url'],ROOT/row['path'],row['sha256'])
    if args.all:
        cache=ROOT/'.downloads';cache.mkdir(exist_ok=True)
        for row in manifest['archives']:
            path=cache/row['name'];download(row['url'],path,row['sha256'])
            if row.get('kind')=='zip':
                with zipfile.ZipFile(path) as archive:
                    for name in archive.namelist():
                        rel=name.removeprefix(row.get('strip',''))
                        if not rel or name.endswith('/'):continue
                        destination=(ROOT/row['destination']/rel).resolve()
                        destination.relative_to((ROOT/row['destination']).resolve())
                        destination.parent.mkdir(parents=True,exist_ok=True)
                        destination.write_bytes(archive.read(name))
            else:
                dst=ROOT/row['destination'];dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dst)
if __name__=='__main__':main()
