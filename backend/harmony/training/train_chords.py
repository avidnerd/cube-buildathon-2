"""Train chord_hmm.npz from corpus Pieces.

    HARMONY_DATA=<folder with lakh_pieces.pkl, split.pkl> python -m backend.harmony.training.train_chords
"""

from __future__ import annotations

import os
import pickle
from pathlib import Path

import numpy as np

from backend.harmony.corpus import BandIndex, bach_pieces
from backend.harmony.melody_chords import MODEL_PATH, N_STATES, length_class, state_of
from backend.harmony.reharmonize import estimate_key


def main() -> None:
    data = Path(os.environ["HARMONY_DATA"])
    with open(data / "lakh_pieces.pkl", "rb") as f:
        lakh = pickle.load(f)
    with open(data / "split.pkl", "rb") as f:
        test = set(pickle.load(f)["test_ids"])
    counts = {m: {"E": np.full((4, 3, 12), 0.3), "R": np.full((12, 4), 0.3), "T": np.full((N_STATES, N_STATES), 0.05),
                  "X": np.ones((N_STATES, 3, 2))} for m in ("major", "minor")}
    for piece in [*lakh.values(), *bach_pieces()]:
        if piece.id in test:
            continue
        prof = np.zeros(12)
        for p, a, b in piece.lead:
            prof[p % 12] += b - a
        tonic, mode = estimate_key(prof)
        band, c, prev = BandIndex(piece.band), counts[mode], None
        for p, a, b in piece.lead:
            ch = band.chord(a, b)
            if ch is None:
                prev = None
                continue
            s, ln = state_of(ch, tonic), length_class(b - a)
            c["E"][s % 4, ln, (p - tonic - s // 4) % 12] += 1
            c["R"][s // 4, s % 4] += 1
            if prev is not None:
                c["X"][prev, ln, int(prev != s)] += 1
                if prev != s:
                    c["T"][prev, s] += 1
            prev = s
    out = {}
    for mode, c in counts.items():
        out[f"{mode}_E"] = np.log(c["E"] / c["E"].sum(2, keepdims=True))
        out[f"{mode}_T"] = np.log(c["T"] / c["T"].sum(1, keepdims=True))
        out[f"{mode}_X"] = np.log(c["X"] / c["X"].sum(2, keepdims=True))
        out[f"{mode}_R"] = np.log(c["R"] / c["R"].sum())
    np.savez_compressed(MODEL_PATH, **{k: v.astype(np.float32) for k, v in out.items()})


if __name__ == "__main__":
    main()
