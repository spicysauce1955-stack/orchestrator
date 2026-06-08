from ttl_cache import TtlCache


def test_set_and_get():
    c = TtlCache(capacity=2)
    c.set("a", 1)
    assert c.get("a") == 1


def test_missing_key_returns_none():
    c = TtlCache(capacity=2)
    assert c.get("nope") is None


def test_len_and_overwrite():
    c = TtlCache(capacity=2)
    c.set("a", 1)
    c.set("a", 2)
    assert c.get("a") == 2
    assert len(c) == 1
