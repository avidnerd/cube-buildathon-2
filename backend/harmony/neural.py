"""A learned harmony scorer: small neural network + CRF over the note lattice.

The hand-built feature model (harmonizer.NODE_FEATURES) can only re-weight
rules someone wrote down. This model is trained on thousands of real
arrangements (corpus.py) and learns the rules itself from raw musical context:
for every candidate harmony note it sees the interval to the lead, the key-
relative pitch classes, what the band is playing *relative to that candidate*,
the melody's contour, the note's length and its place in the phrase. A CRF on
top scores whole lines (with learned motion costs), so it's trained on and
decodes complete, singable parts rather than isolated notes.

    train(examples) -> HarmonyNet          (torch; offline)
    NetScorer.load(path).decode(lattice)   (numpy; used by the studio)

The hand-built features are fed in too, so the network starts from what the
rule model knows and only has to learn what it misses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import numpy as np

from backend.harmony.harmonizer import DEGREE_PAIRS, EDGE_FEATURES, NODE_FEATURES, RAW_FEATURES, Lattice

MODEL_PATH = Path(__file__).with_name("harmony_net.npz")
N_DEG = len(DEGREE_PAIRS)


def node_inputs(lat: Lattice, i: int) -> np.ndarray:
    """(C, D): raw context + hand features + degree-pair one-hot (compressed to lead/cand degree)."""
    C = len(lat.cands[i])
    deg = lat.deg[i]
    # Degree pairs as lead degree (7) + candidate degree (7) + above/below (1): the net learns the pairs.
    dd = np.zeros((C, 15), dtype=np.float32)
    ok = deg >= 0
    if ok.any():
        d = deg[ok].astype(int)
        up = d < 49
        r = d % 49
        dd[np.flatnonzero(ok), r // 7] = 1.0
        dd[np.flatnonzero(ok), 7 + r % 7] = 1.0
        dd[np.flatnonzero(ok), 14] = up
    return np.concatenate([lat.raw[i].astype(np.float32), lat.node[i], dd], axis=1)


def input_dim() -> int:
    return len(RAW_FEATURES) + len(NODE_FEATURES) + 15


# ---------------------------------------------------------------------------
# Training (torch)
# ---------------------------------------------------------------------------

def _torch_model(hidden: int = 96):
    import torch
    from torch import nn

    class HarmonyNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.node = nn.Sequential(
                nn.Linear(input_dim(), hidden), nn.ReLU(),
                nn.Linear(hidden, hidden // 2), nn.ReLU(),
                nn.Linear(hidden // 2, 1),
            )
            self.edge = nn.Linear(len(EDGE_FEATURES), 1, bias=False)
            self.register_buffer("mu", torch.zeros(input_dim()))
            self.register_buffer("sd", torch.ones(input_dim()))

        def node_scores(self, X):
            return self.node((X - self.mu) / self.sd).squeeze(-1)

    return HarmonyNet()


def _example_tensors(ex):
    import torch

    lat = ex.lattice
    X = [torch.from_numpy(node_inputs(lat, i)) for i in range(len(lat.cands))]
    E = [torch.from_numpy(e).float() for e in lat.edge]
    return X, E, ex.gold


def _crf_loss(net, X, E, gold):
    """-log P(gold line | lead) under the CRF."""
    import torch

    S = [net.node_scores(x) for x in X]
    W = [net.edge(e).squeeze(-1) for e in E]  # (Cp, C)
    alpha = S[0]
    gold_score = S[0][gold[0]]
    for i in range(1, len(S)):
        alpha = torch.logsumexp(alpha[:, None] + W[i - 1], dim=0) + S[i]
        gold_score = gold_score + W[i - 1][gold[i - 1], gold[i]] + S[i][gold[i]]
    return torch.logsumexp(alpha, dim=0) - gold_score


def train(examples: Sequence, valid: Sequence = (), epochs: int = 12, lr: float = 2e-3,
          weight_decay: float = 1e-4, seed: int = 0, log=print):
    import torch

    torch.manual_seed(seed)
    net = _torch_model()
    data = [_example_tensors(ex) for ex in examples]
    allx = torch.cat([x for X, _, _ in data for x in X])
    net.mu.copy_(allx.mean(0))
    net.sd.copy_(allx.std(0).clamp_min(1e-3))
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=weight_decay)
    rng = np.random.default_rng(seed)
    best, best_state = -1.0, None
    for ep in range(epochs):
        net.train()
        order = rng.permutation(len(data))
        tot, n = 0.0, 0
        for k in range(0, len(order), 16):
            opt.zero_grad()
            loss = sum(_crf_loss(net, *data[j]) for j in order[k:k + 16])
            notes = sum(len(data[j][2]) for j in order[k:k + 16])
            (loss / notes).backward()
            opt.step()
            tot += float(loss)
            n += notes
        msg = f"epoch {ep + 1}: loss/note {tot / n:.3f}"
        if valid:
            acc = agreement(valid, NetScorer.from_torch(net))
            msg += f"  held-out agreement {acc:.1%}"
            if acc > best:
                best, best_state = acc, {k: v.clone() for k, v in net.state_dict().items()}
        log(msg)
    if best_state is not None:
        net.load_state_dict(best_state)
    return net


# ---------------------------------------------------------------------------
# Inference (numpy only)
# ---------------------------------------------------------------------------

class NetScorer:
    """The trained network in plain numpy, for the studio."""

    def __init__(self, layers: list[tuple[np.ndarray, np.ndarray]], edge_w: np.ndarray, mu: np.ndarray, sd: np.ndarray,
                 meta: dict | None = None):
        self.layers, self.edge_w, self.mu, self.sd = layers, edge_w, mu, sd
        self.meta = meta or {}

    @classmethod
    def from_torch(cls, net, meta: dict | None = None) -> "NetScorer":
        lin = [m for m in net.node if hasattr(m, "weight")]
        layers = [(m.weight.detach().numpy().T.astype(np.float32), m.bias.detach().numpy().astype(np.float32)) for m in lin]
        return cls(layers, net.edge.weight.detach().numpy()[0].astype(np.float32),
                   net.mu.numpy().astype(np.float32), net.sd.numpy().astype(np.float32), meta)

    def save(self, path: Path = MODEL_PATH) -> None:
        arrays = {"edge_w": self.edge_w, "mu": self.mu, "sd": self.sd}
        for k, (W, b) in enumerate(self.layers):
            arrays[f"W{k}"], arrays[f"b{k}"] = W, b
        np.savez_compressed(path, meta=np.array(json.dumps(self.meta)), **arrays)

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> "NetScorer | None":
        if not Path(path).exists():
            return None
        z = np.load(path, allow_pickle=False)
        k, layers = 0, []
        while f"W{k}" in z:
            layers.append((z[f"W{k}"], z[f"b{k}"]))
            k += 1
        if not layers or z["mu"].shape[0] != input_dim():
            return None  # trained on a different feature set
        return cls(layers, z["edge_w"], z["mu"], z["sd"], json.loads(str(z["meta"])))

    def node_scores(self, lat: Lattice, i: int) -> np.ndarray:
        h = (node_inputs(lat, i) - self.mu) / self.sd
        for k, (W, b) in enumerate(self.layers):
            h = h @ W + b
            if k < len(self.layers) - 1:
                h = np.maximum(h, 0.0)
        return h[:, 0]

    def decode(self, lat: Lattice, bias=None) -> list[int]:
        """Best line (max score). bias(i) -> (C,) optional extra score per candidate."""
        def node(i):
            s = self.node_scores(lat, i)
            return s + bias(i) if bias is not None else s

        acc = node(0)
        back = []
        for i in range(1, len(lat.cands)):
            total = acc[:, None] + lat.edge[i - 1].astype(np.float32) @ self.edge_w
            back.append(np.argmax(total, axis=0))
            acc = total.max(axis=0) + node(i)
        j = int(np.argmax(acc))
        path = [j]
        for b in reversed(back):
            j = int(b[j])
            path.append(j)
        return path[::-1]


def agreement(examples: Sequence, scorer: NetScorer, pitch_class: bool = False) -> float:
    hit = tot = 0
    for ex in examples:
        pred = scorer.decode(ex.lattice)
        c = ex.lattice.cands
        for i, (a, b) in enumerate(zip(pred, ex.gold)):
            hit += (c[i][a] % 12 == c[i][b] % 12) if pitch_class else (c[i][a] == c[i][b])
        tot += len(ex.gold)
    return hit / max(tot, 1)


# ---------------------------------------------------------------------------
# Personal adjustment: a small correction on top of the base model
# ---------------------------------------------------------------------------

PERSONAL_PATH = Path(__file__).with_name("personal_style.json")  # legacy global layer (unused by the studio)


def song_fingerprint(notes) -> str:
    """Identify a song by its melody (same tune re-recorded -> same id), for per-song adjustments."""
    import hashlib

    seq = [int(n["pitch"]) for n in notes[:48]]
    rel = [b - a for a, b in zip(seq, seq[1:])]  # transposition-invariant
    return hashlib.md5(json.dumps(rel).encode()).hexdigest()[:12]


_WRONG_SIDE = NODE_FEATURES.index("wrong_side")


def side_rule(lat: Lattice):
    """Upper parts never below the lead, lower parts never above it (a rule, not a preference)."""
    return lambda i: np.where(lat.node[i][:, _WRONG_SIDE] > 0, -1e6, 0.0)


def _bias_fn(lat: Lattice, wn: np.ndarray, wd: np.ndarray):
    """Score bias from linear weights over the hand features (positive weight = penalty), plus the side rule."""
    side = side_rule(lat)
    return lambda i: side(i) - (lat.node[i] @ wn + wd[lat.deg[i]])


def fit_personal(examples: Sequence, scorer: NetScorer, epochs: int = 60, lr: float = 0.05, l2: float = 0.02) -> dict:
    """Learn the user's corrections as a delta on top of the base model.

    Structured perceptron where the prediction is base score + bias; L2 keeps
    the delta small so a few fixes adjust the style without erasing what the
    base model learned from thousands of songs.
    """
    wn = np.zeros(len(NODE_FEATURES))
    wd = np.zeros(N_DEG + 1)
    sn, sd, count = np.zeros_like(wn), np.zeros_like(wd), 0
    rng = np.random.default_rng(0)
    for _ in range(epochs):
        for k in rng.permutation(len(examples)):
            ex = examples[k]
            lat = ex.lattice
            pred = scorer.decode(lat, bias=_bias_fn(lat, wn, wd))
            if pred != ex.gold:
                for path, sign in ((ex.gold, -1.0), (pred, 1.0)):  # make gold cheaper, prediction dearer
                    for i, j in enumerate(path):
                        wn += sign * lr * lat.node[i][j]
                        if lat.deg[i][j] >= 0:
                            wd[lat.deg[i][j]] += sign * lr
            wn -= lr * l2 * wn
            wd -= lr * l2 * wd
            wd[-1] = 0.0
            sn += wn
            sd += wd
            count += 1
    wn, wd = sn / max(count, 1), sd / max(count, 1)
    return {"node": dict(zip(NODE_FEATURES, map(float, wn))), "deg": dict(zip(DEGREE_PAIRS, map(float, wd[:-1])))}


def personal_bias(lat: Lattice, personal: dict | None):
    if not personal:
        return side_rule(lat)
    wn = np.array([personal["node"].get(f, 0.0) for f in NODE_FEATURES])
    wd = np.array([personal["deg"].get(f, 0.0) for f in DEGREE_PAIRS] + [0.0])
    return _bias_fn(lat, wn, wd)


def personal_agreement(examples: Sequence, scorer: NetScorer, personal: dict | None) -> float:
    hit = tot = 0
    for ex in examples:
        pred = scorer.decode(ex.lattice, bias=personal_bias(ex.lattice, personal))
        hit += sum(int(ex.lattice.cands[i][a] == ex.lattice.cands[i][b]) for i, (a, b) in enumerate(zip(pred, ex.gold)))
        tot += len(ex.gold)
    return hit / max(tot, 1)


def load_personal() -> dict | None:
    if PERSONAL_PATH.exists():
        try:
            return json.loads(PERSONAL_PATH.read_text())
        except ValueError:
            return None
    return None


_cached: dict = {}


def base_model() -> NetScorer | None:
    """The trained base model, loaded once (None if not trained yet)."""
    key = (str(MODEL_PATH), MODEL_PATH.stat().st_mtime if MODEL_PATH.exists() else None)
    if _cached.get("key") != key:
        _cached["key"], _cached["net"] = key, NetScorer.load(MODEL_PATH)
    return _cached["net"]
