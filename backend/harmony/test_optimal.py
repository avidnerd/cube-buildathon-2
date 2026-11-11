"""The optimisers find the true minimum: checked against brute force."""

import itertools

import numpy as np
import pytest

from backend.harmony.optimal import chain, pair_chain, two_voice


@pytest.mark.parametrize("seed", range(20))
def test_chain_is_the_brute_force_minimum(seed):
    r = np.random.default_rng(seed)
    sizes = r.integers(1, 4, size=5)
    node = [r.normal(size=s) for s in sizes]
    E = [None] + [r.normal(size=(sizes[i - 1], sizes[i])) for i in range(1, 5)]
    path, cost = chain(node, lambda i: E[i])
    f = lambda p: sum(node[i][x] for i, x in enumerate(p)) + sum(E[i][p[i - 1], p[i]] for i in range(1, 5))
    best = min(itertools.product(*[range(s) for s in sizes]), key=f)
    assert np.isclose(cost, f(best)) and np.isclose(f(path), f(best))


@pytest.mark.parametrize("seed", range(20))
def test_pair_chain_is_the_brute_force_minimum(seed):
    r = np.random.default_rng(seed)
    n = 4
    A, B = r.integers(1, 4, size=n), r.integers(1, 4, size=n)
    na, nb = [r.normal(size=s) for s in A], [r.normal(size=s) for s in B]
    P = [r.normal(size=(A[i], B[i])) for i in range(n)]
    Ea = [None] + [r.normal(size=(A[i - 1], A[i])) for i in range(1, n)]
    Eb = [None] + [r.normal(size=(B[i - 1], B[i])) for i in range(1, n)]
    pa, pb, cost = pair_chain(na, nb, P, lambda i: Ea[i], lambda i: Eb[i])

    def f(a, b):
        return (sum(na[i][a[i]] + nb[i][b[i]] + P[i][a[i], b[i]] for i in range(n))
                + sum(Ea[i][a[i - 1], a[i]] + Eb[i][b[i - 1], b[i]] for i in range(1, n)))
    best = min(f(a, b) for a in itertools.product(*[range(s) for s in A]) for b in itertools.product(*[range(s) for s in B]))
    assert np.isclose(cost, best) and np.isclose(f(pa, pb), best)


@pytest.mark.parametrize("seed", range(20))
def test_two_voice_is_the_brute_force_minimum(seed):
    r = np.random.default_rng(seed)
    n0, n1 = int(r.integers(1, 5)), int(r.integers(1, 4))
    # random onsets / lengths for two monophonic voices
    def voice(n):
        t, out = 0.0, []
        for _ in range(n):
            t += float(r.uniform(0, 1))
            d = float(r.uniform(0.2, 1.5))
            out.append((t, t + d))
            t += d
        return out
    T = [voice(n0), voice(n1)]
    C = [[int(r.integers(1, 4)) for _ in T[0]], [int(r.integers(1, 4)) for _ in T[1]]]
    node = [[r.normal(size=c) for c in C[v]] for v in range(2)]
    E = {(v, k): r.normal(size=(C[v][k - 1], C[v][k])) for v in range(2) for k in range(1, len(C[v]))}
    PW = {(i, j): r.normal(size=(C[0][i], C[1][j])) for i in range(n0) for j in range(n1)}
    overl = lambda i, j: min(T[0][i][1], T[1][j][1]) > max(T[0][i][0], T[1][j][0])  # noqa: E731
    pair = lambda i, j: PW[i, j] if overl(i, j) else None  # noqa: E731
    events = sorted([(T[v][k][0], v, k) for v in range(2) for k in range(len(T[v]))])
    (c0, c1), cost = two_voice([(v, k) for _, v, k in events], node, lambda v, k: E[v, k], pair)

    def f(a, b):
        s = sum(node[0][k][x] for k, x in enumerate(a)) + sum(node[1][k][x] for k, x in enumerate(b))
        s += sum(E[0, k][a[k - 1], a[k]] for k in range(1, n0)) + sum(E[1, k][b[k - 1], b[k]] for k in range(1, n1))
        s += sum(PW[i, j][a[i], b[j]] for i in range(n0) for j in range(n1) if overl(i, j))
        return s
    best = min(f(a, b) for a in itertools.product(*[range(c) for c in C[0]]) for b in itertools.product(*[range(c) for c in C[1]]))
    assert np.isclose(cost, best) and np.isclose(f(c0, c1), best)
