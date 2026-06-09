from token_bucket import TokenBucket


def test_starts_full_and_allows():
    b = TokenBucket(capacity=5, refill_rate=1)
    assert b.allow() is True


def test_denies_when_empty():
    b = TokenBucket(capacity=1, refill_rate=0)
    assert b.allow() is True
    assert b.allow() is False


def test_tokens_capped_at_capacity():
    b = TokenBucket(capacity=2, refill_rate=10)
    assert b.tokens <= 2
