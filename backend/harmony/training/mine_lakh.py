"""Mine Lakh MIDI for songs with a lead vocal + a harmony vocal that moves with it."""
import sys, re, pickle, time, os
from pathlib import Path
from multiprocessing import Pool
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3]))
ROOT = Path(sys.argv[1]); OUT = sys.argv[2]
HARM_B = re.compile(rb"(?i)harm|backing|back ?vo|bgv|\bbvs?\b|choir|vocals? ?2|vox ?2|voice ?2|2nd vo|second vo")
VOX_B = re.compile(rb"(?i)vocal|vox|voice|melody|sing")

def work(path):
    try:
        b = path.read_bytes()
    except OSError:
        return None
    if not (HARM_B.search(b) and VOX_B.search(b)):
        return None
    from backend.harmony.corpus import lakh_pieces
    return list(lakh_pieces([path])) or None   # just the notes; training data is built later, in memory

if __name__ == "__main__":
    files = sorted(ROOT.rglob("*.mid"))
    print(f"{len(files)} files", flush=True)
    t = time.time(); found = {}; seen = 0
    with Pool(max(1, (os.cpu_count() or 4) - 1)) as pool:
        for res in pool.imap_unordered(work, files, chunksize=64):
            seen += 1
            if res:
                for piece in res:
                    found[piece.id] = piece
            if seen % 20000 == 0:
                print(f"  {seen} scanned, {len(found)} songs with harmony, {time.time()-t:.0f}s", flush=True)
    pickle.dump(found, open(OUT, "wb"))
    print(f"done: {len(found)} songs, {sum(len(p.lead) for p in found.values())} lead notes in {time.time()-t:.0f}s")
