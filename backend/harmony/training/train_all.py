"""Train the base harmony model on Bach chorales + Lakh pop vocal harmonies; test on unseen songs."""
import sys, pickle, time, os, numpy as np
from multiprocessing import Pool
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3]))
import os
S = os.environ.get("HARMONY_DATA", "data")

def build(piece):
    """Each song twice: with its band, and a cappella (band hidden, only chord guesses)."""
    from backend.harmony.corpus import piece_examples
    try:
        return piece.id, piece.source, (piece_examples(piece, max_examples=2, max_len=32, compact=True)
                                        + piece_examples(piece, max_examples=1, max_len=32, compact=True, acappella=True))
    except Exception as e:
        return piece.id, piece.source, []

if __name__ == "__main__":
    from backend.harmony import neural as NN
    from backend.harmony.corpus import bach_pieces
    lakh = pickle.load(open(f"{S}/lakh_pieces.pkl", "rb"))
    pieces = list(lakh.values()) + list(bach_pieces())
    t = time.time(); by_piece = {}
    with Pool(max(1, (os.cpu_count() or 4) - 1)) as pool:
        for pid, src, exs in pool.imap_unordered(build, pieces, chunksize=8):
            if exs:
                for e in exs: e.meta = {"piece": pid, "source": src}
                by_piece[pid] = exs
    print(f"built {sum(len(v) for v in by_piece.values())} examples / {sum(len(e.gold) for v in by_piece.values() for e in v)} notes from {len(by_piece)} songs in {time.time()-t:.0f}s", flush=True)
    ids = sorted(by_piece); rng = np.random.default_rng(0); rng.shuffle(ids)
    n = len(ids); test_ids, val_ids, train_ids = ids[: n // 8], ids[n // 8: n // 8 + n // 16], ids[n // 8 + n // 16:]
    get = lambda ids: [e for i in ids for e in by_piece[i]]
    train, val, test = get(train_ids), get(val_ids), get(test_ids)
    print(f"train {sum(len(e.gold) for e in train)} notes | val {sum(len(e.gold) for e in val)} | test {sum(len(e.gold) for e in test)} notes from {len(test_ids)} unseen songs", flush=True)
    t = time.time()
    net = NN.train(train, val, epochs=int(sys.argv[1]) if len(sys.argv) > 1 else 10, log=lambda m: print(m, flush=True))
    songs = {"lakh": sum(1 for i in train_ids if i.startswith("lakh")), "bach": sum(1 for i in train_ids if i.startswith("bach"))}
    sc = NN.NetScorer.from_torch(net, {"songs": songs["lakh"] + songs["bach"], "by_source": songs,
                                        "notes": sum(len(e.gold) for e in train)})
    print(f"trained in {time.time()-t:.0f}s")
    for src in ("lakh", "bach"):
        sub = [e for e in test if e.meta["source"] == src]
        if sub:
            print(f"held-out {src}: exact {NN.agreement(sub, sc):.1%}  note-name {NN.agreement(sub, sc, True):.1%}  ({sum(len(e.gold) for e in sub)} notes)")
    sc.save(f"{S}/harmony_net.npz"); print("saved model")
    pickle.dump({"test_ids": test_ids}, open(f"{S}/split.pkl", "wb"))
