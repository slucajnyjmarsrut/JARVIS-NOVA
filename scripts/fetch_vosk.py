"""Download official Vosk small Russian model as wake-word baseline at BUILD TIME only."""
from pathlib import Path
import urllib.request,zipfile,tempfile,shutil
ROOT=Path(__file__).resolve().parent.parent
URL='https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip'
DEST=ROOT/'assets'/'models'/'vosk'
def main():
    if DEST.exists():raise RuntimeError('Refuse replacing existing Vosk model')
    with tempfile.TemporaryDirectory() as temp:
        archive=Path(temp)/'vosk.zip'
        urllib.request.urlretrieve(URL,archive)
        if archive.stat().st_size<10_000_000:raise RuntimeError('Downloaded Vosk ZIP unexpectedly small')
        with zipfile.ZipFile(archive) as z:
            members=z.infolist()
            if sum(i.file_size for i in members)>150_000_000:raise RuntimeError('Vosk archive too large')
            for i in members:
                path=Path(i.filename)
                if path.is_absolute() or '..' in path.parts: raise RuntimeError('Unsafe ZIP member')
            z.extractall(temp)
        origin=Path(temp)/'vosk-model-small-ru-0.22'
        for rel in ('am/final.mdl','graph/HCLr.fst','graph/Gr.fst','LICENSE'):
            if not (origin/rel).is_file():raise RuntimeError('Model missing: '+rel)
        DEST.parent.mkdir(parents=True,exist_ok=True)
        shutil.copytree(origin,DEST)
    print('Vosk archive acquired; final runtime checks happen in verify_models.py')
if __name__=='__main__':main()
