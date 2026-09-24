from roya.auth.service import _session_hash


def test_server_session_lookup_uses_hash_not_browser_secret():
    raw="browser-session-secret"
    digest=_session_hash(raw)
    assert digest!=raw
    assert len(digest)==64
    assert digest==_session_hash(raw)
