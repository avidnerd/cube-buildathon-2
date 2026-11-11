"""Exact optimisers shared by the arrangers.

Every arrangement is "the best one" only relative to a stated cost, so each
arranger writes its musical rules as a cost and hands it to one of these, which
return the *global* minimum (not a greedy, note-by-note guess):

    chain(node, edge)            one voice, a candidate per step: Viterbi (exact)
    pair_chain(...)              two voices on the same steps, chosen together
    two_voice(events, ...)       two voices on *different* rhythms (riff + bass):
                                 exact joint Viterbi over the merged timeline

The tests check each against brute-force enumeration on small cases.
"""

from __future__ import annotations

from typing import Callable, Sequence

import numpy as np


def chain(node: Sequence[np.ndarray], edge: Callable[[int], np.ndarray]) -> tuple[list[int], float]:
    """argmin over paths of sum node[i][x_i] + sum edge(i)[x_{i-1}, x_i]. Returns (path, cost)."""
    acc = np.asarray(node[0], dtype=float)
    back = []
    for i in range(1, len(node)):
        tot = acc[:, None] + edge(i)
        back.append(tot.argmin(axis=0))
        acc = tot.min(axis=0) + node[i]
    j = int(acc.argmin())
    cost = float(acc[j])
    path = [j]
    for b in reversed(back):
        j = int(b[j])
        path.append(j)
    return path[::-1], cost


def pair_chain(node_a, node_b, pair, edge_a, edge_b) -> tuple[list[int], list[int], float]:
    """Two voices, one choice each per step, minimising
        sum_i node_a[i][a_i] + node_b[i][b_i] + pair[i][a_i, b_i]
        + sum_i edge_a(i)[a_{i-1}, a_i] + edge_b(i)[b_{i-1}, b_i].
    The edge terms are separable, so the min over the previous (a, b) is done one
    voice at a time: O(A^2 B + A B^2) per step instead of O(A^2 B^2), still exact.
    """
    acc = node_a[0][:, None] + node_b[0][None, :] + pair[0]
    backs = []
    for i in range(1, len(node_a)):
        ea, eb = edge_a(i), edge_b(i)                       # (A_prev, A), (B_prev, B)
        # step 1: move a, keep b at its previous value:  m1[a, b_prev]
        t1 = acc[:, None, :] + ea[:, :, None]               # (A_prev, A, B_prev)
        ia = t1.argmin(axis=0)
        m1 = t1.min(axis=0)
        # step 2: move b:  m2[a, b]
        t2 = m1[:, :, None] + eb[None, :, :]                # (A, B_prev, B)
        ib = t2.argmin(axis=1)
        acc = t2.min(axis=1) + node_a[i][:, None] + node_b[i][None, :] + pair[i]
        backs.append((ia, ib))
    a, b = np.unravel_index(int(acc.argmin()), acc.shape)
    cost = float(acc[a, b])
    pa, pb = [int(a)], [int(b)]
    for ia, ib in reversed(backs):
        b_prev = int(ib[a, b])
        a_prev = int(ia[a, b_prev])
        a, b = a_prev, b_prev
        pa.append(a)
        pb.append(b)
    return pa[::-1], pb[::-1], cost


def two_voice(events: Sequence[tuple[int, int]], node: Sequence[Sequence[np.ndarray]],
              edge: Callable[[int, int], np.ndarray], pair: Callable[[int, int], np.ndarray | None]
              ) -> tuple[list[list[int]], float]:
    """Two monophonic voices with their own rhythms, chosen jointly.

    events: (voice, note index) in onset order; each voice's notes appear in order.
    node[v][k]: cost per candidate of voice v's note k.
    edge(v, k): (C_prev, C) cost from voice v's note k-1 to note k (k >= 1).
    pair(k0, k1): (C0, C1) cost between voice 0's note k0 and voice 1's note k1, or
        None if they never sound together. Two notes that overlap are both
        current when the later of them starts, so every overlapping pair is
        charged exactly once, at that event: the sum is the full objective.
    Returns (choice index per note, per voice) and the minimum cost.
    """
    acc = np.zeros((1, 1))
    cur = [-1, -1]              # current note index of each voice (-1: not started)
    backs = []
    for v, k in events:
        assert k == cur[v] + 1, "events must list each voice's notes in order"
        e = edge(v, k) if k > 0 else np.zeros((1, len(node[v][k])))
        a = acc if v == 0 else acc.T                         # (mine_prev, other)
        t = a[:, None, :] + e[:, :, None]                    # (mine_prev, mine, other)
        bk = t.argmin(axis=0)
        new = t.min(axis=0) + np.asarray(node[v][k], dtype=float)[:, None]
        o = cur[1 - v]
        if o >= 0:
            p = pair(k, o) if v == 0 else pair(o, k)
            if p is not None:
                new = new + (p if v == 0 else p.T)
        acc = new if v == 0 else new.T
        backs.append((v, bk))
        cur[v] = k
    idx = list(np.unravel_index(int(acc.argmin()), acc.shape))
    cost = float(acc[idx[0], idx[1]])
    out: list[list[int]] = [[0] * (cur[0] + 1), [0] * (cur[1] + 1)]
    for (v, k), (_, bk) in zip(reversed(events), reversed(backs)):
        out[v][k] = int(idx[v])
        idx[v] = int(bk[idx[v], idx[1 - v]])
    return out, cost
