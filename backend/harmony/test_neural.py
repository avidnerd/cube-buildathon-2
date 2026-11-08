import numpy as np

from backend.harmony import neural as NN
from backend.harmony.harmonizer import build_lattice
from backend.harmony.reharmonize import parse_chord


def _tiny_net(seed=0):
    rng = np.random.default_rng(seed)
    d = NN.input_dim()
    layers = [(rng.normal(0, 0.1, (d, 8)).astype(np.float32), np.zeros(8, np.float32)),
              (rng.normal(0, 0.1, (8, 1)).astype(np.float32), np.zeros(1, np.float32))]
    return NN.NetScorer(layers, np.zeros(6, np.float32), np.zeros(d, np.float32), np.ones(d, np.float32))


def _melody(ps, start=0.0):
    return [{"pitch": p, "t0": start + 0.5 * i, "t1": start + 0.5 * i + 0.45} for i, p in enumerate(ps)]


def test_song_fingerprint_is_transposition_invariant_and_distinct():
    a = NN.song_fingerprint(_melody([60, 62, 64, 65, 67]))
    assert a == NN.song_fingerprint(_melody([65, 67, 69, 70, 72]))   # same tune, other key
    assert a != NN.song_fingerprint(_melody([60, 64, 62, 65, 67]))


def test_learned_model_obeys_the_side_rule():
    net = _tiny_net()
    mel = _melody([60, 62, 64, 65, 67, 65, 64, 62])
    for side in (+1, -1):
        lat = build_lattice(mel, lambda t: parse_chord("C"), (0, "major"), (45, 84, 48, 80), side, 3.5, max_iv=14)
        path = net.decode(lat, bias=NN.personal_bias(lat, None))
        for n, opts, j in zip(mel, lat.cands, path):
            assert (opts[j] - n["pitch"]) * side >= 0


def test_numpy_scorer_matches_torch():
    import torch
    net = NN._torch_model(hidden=16)
    sc = NN.NetScorer.from_torch(net)
    lat = build_lattice(_melody([60, 64, 67, 65]), lambda t: parse_chord("C"), (0, "major"), (48, 80, 50, 78), +1, 3.5, max_iv=14)
    X = torch.from_numpy(NN.node_inputs(lat, 0))
    assert np.allclose(net.node_scores(X).detach().numpy(), sc.node_scores(lat, 0), atol=1e-4)


def test_personal_layer_only_for_its_song(tmp_path, monkeypatch):
    from backend.harmony.playground import server
    monkeypatch.setattr(server, "FEEDBACK_DIR", tmp_path)
    monkeypatch.setattr(NN, "base_model", lambda: _tiny_net())
    mine, other = _melody([60, 62, 64, 65, 67]), _melody([67, 64, 60, 62, 55])
    server._personal_path(NN.song_fingerprint(mine)).write_text('{"node": {}, "deg": {}}')
    assert server._song_personal(mine) is not None
    assert server._song_personal(other) is None
