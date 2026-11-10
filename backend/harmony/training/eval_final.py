import sys, pickle, json, numpy as np
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3]))
from backend.harmony import neural as NN, harmonizer as H
from backend.harmony.corpus import piece_examples, bach_pieces
import os
D = os.environ.get("HARMONY_DATA", "data")
test_ids = set(pickle.load(open(f"{D}/split.pkl", "rb"))["test_ids"])
lakh = pickle.load(open(f"{D}/lakh_pieces.pkl", "rb"))
pieces = [p for p in list(lakh.values()) + list(bach_pieces()) if p.id in test_ids]
old = NN.NetScorer.load("backend/harmony/harmony_net.npz")
new = NN.NetScorer.load(f"{D}/harmony_net.npz")
F = {f: i for i, f in enumerate(H.NODE_FEATURES)}
def third(ex):
    out = []
    for i, c in enumerate(ex.lattice.cands):
        ok = np.flatnonzero(ex.lattice.node[i][:, F["diatonic_third"]] > 0)
        out.append(int(ok[0]) if len(ok) else 0)
    return out
def acc(fn, sub):
    hit = tot = 0
    for ex in sub:
        pr = fn(ex); c = ex.lattice.cands
        hit += sum(c[i][a] == c[i][b] for i, (a, b) in enumerate(zip(pr, ex.gold))); tot += len(ex.gold)
    return hit / max(tot, 1)
for mode in (False, True):
    exs = {"lakh": [], "bach": []}
    for p in pieces:
        exs[p.source] += piece_examples(p, max_examples=2, max_len=32, compact=True, acappella=mode)
    for src, sub in exs.items():
        print(f"{'voice only' if mode else 'with band':10} {src}: diatonic-3rd {acc(third, sub):5.1%}   old model {acc(lambda e: old.decode(e.lattice), sub):5.1%}   NEW model {acc(lambda e: new.decode(e.lattice), sub):5.1%}   ({sum(len(e.gold) for e in sub)} notes)")
from backend.harmony.playground.server import _examples_from_feedback
fb = json.load(open("listen/feedback-00000000-seed-until-i-found-you.json"))
ex = _examples_from_feedback(fb)
print(f"your take, base model only (never saw your fixes): old {NN.personal_agreement(ex, old, None):.0%}  NEW {NN.personal_agreement(ex, new, None):.0%}")
