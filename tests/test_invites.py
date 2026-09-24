from roya.auth.schemas import LoginInput,RegisterInput
from roya.organizations.invites import _normalize_email,_token_hash


def test_invite_token_hash_is_deterministic_and_not_raw():
    raw="sample-one-time-invite-token-1234567890"
    digest=_token_hash(raw)
    assert digest!=raw
    assert len(digest)==64
    assert digest==_token_hash(raw)


def test_invite_email_normalization():
    assert _normalize_email("  Staff+Desk@Example.COM ")=="staff+desk@example.com"


def test_auth_schemas_accept_invite_token():
    token="x"*32
    register=RegisterInput(name="Hotel Staff",email="staff@example.com",password="password123",account_type="guest",invite_token=token)
    login=LoginInput(email="staff@example.com",password="password123",invite_token=token)
    assert register.invite_token==token
    assert login.invite_token==token
