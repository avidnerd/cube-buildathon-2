import engine_gateway as g


def test_only_the_sites_calls_are_routed():
    assert g.upstream_for("POST", "/api/analyze") == g.ENGINE
    assert g.upstream_for("POST", "/api/render") == g.ENGINE
    assert g.upstream_for("POST", "/api/counter") == g.COUNTER
    assert g.upstream_for("GET", "/api/job/abc123def456") == g.ENGINE
    assert g.upstream_for("GET", "/api/job/abc123def456/audio/vocals.wav") == g.ENGINE


def test_everything_else_is_closed():
    assert g.upstream_for("POST", "/api/feedback") is None
    assert g.upstream_for("POST", "/api/style/reset") is None
    assert g.upstream_for("GET", "/") is None
    assert g.upstream_for("GET", "/api/style") is None
    assert g.upstream_for("GET", "/api/job/../../etc/passwd") is None
    assert g.upstream_for("GET", "/api/job/abc123def456/audio/secret.wav") is None
    assert g.upstream_for("GET", "/api/analyze") is None


def test_analysis_rate_limit_resets_after_an_hour():
    who = "test-visitor"
    assert all(g.allow_analysis(who, 0.0) for _ in range(g.ANALYSES_PER_HOUR))
    assert not g.allow_analysis(who, 1.0)
    assert g.allow_analysis(who, 3700.0)
