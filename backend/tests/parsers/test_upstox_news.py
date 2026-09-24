"""News parser on the REAL 2026-09-24 Upstox response, plus mutations."""

from __future__ import annotations

import datetime as _dt
import json
import pathlib

import pytest

from app.contracts.provenance import AnomalyKind, AnomalySeverity
from app.parsers import upstox_news as P

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "upstox_news"
MAN = json.loads((FIX / "manifest.json").read_text())[0]
KEYS = MAN["keys"]
FETCHED = _dt.datetime.fromisoformat(MAN["fetched_at"])
RAW = (FIX / MAN["file"]).read_bytes()


def _parse(data=RAW, *, keys=KEYS, fetched=FETCHED, status=200):
    return P.parse_news(data, http_status=status, requested_keys=keys, fetched_at=fetched)


def _mut(fn) -> bytes:
    b = json.loads(RAW)
    fn(b)
    return json.dumps(b).encode()


def _kinds(p):
    return {(i.severity, i.kind) for i in p.issues}


def test_manifest_sha():
    import hashlib
    assert hashlib.sha256(RAW).hexdigest() == MAN["sha256"]


def test_real_response():
    p = _parse()
    assert not p.issues
    assert p.per_key == {"NSE_EQ|INE040A01034": 3, "NSE_EQ|INE467B01029": 8,
                         "NSE_EQ|INE002A01018": 1}
    # 12 listings, 11 distinct articles: one article is under two keys
    assert len(p.articles) == 11 == p.total_records
    assert len(p.links) == 12
    shared = [k for k in p.articles if sum(1 for a, _ in p.links if a == k) == 2]
    assert len(shared) == 1
    assert (p.page_number, p.total_pages) == (1, 1)


def test_article_fields_and_knowable():
    for a in _parse().articles.values():
        assert a.published_at.tzinfo is not None and a.published_at <= FETCHED
        assert a.knowable.at == a.published_at and a.knowable.verified
        assert a.url.startswith("https://upstox.com/news/")
        assert a.vendor_article_id and a.vendor_article_id.isdigit()
        assert a.vendor_payload["published_time"] == int(a.published_at.timestamp() * 1000) \
            or abs(a.vendor_payload["published_time"] - a.published_at.timestamp() * 1000) < 1


def test_publisher_is_never_invented():
    # Upstox sends no publisher; the parser has no field for one to fill
    assert not hasattr(next(iter(_parse().articles.values())), "publisher")


def test_empty_data_is_valid():
    p = _parse(b'{"status":"success","data":{},"metadata":{"page":{"page_number":1,'
               b'"page_size":100,"total_records":0,"total_pages":0}}}')
    assert not p.issues and not p.articles


def test_unrequested_key_is_schema_drift():
    p = _parse(keys=KEYS[:2])
    assert (AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT) in _kinds(p)


def test_unknown_article_field_is_schema_drift():
    d = _mut(lambda b: next(iter(b["data"].values()))[0].update(sentiment="positive"))
    assert (AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT) in _kinds(_parse(d))


@pytest.mark.parametrize("bad", ["1790148658507", 0, -5, True, None, 1.5])
def test_bad_published_time_is_rejected(bad):
    d = _mut(lambda b: next(iter(b["data"].values()))[0].update(published_time=bad))
    assert (AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT) in _kinds(_parse(d))


def test_published_after_fetch_is_clock_skew_and_uses_fetch_time():
    early = FETCHED - _dt.timedelta(days=3)
    p = _parse(fetched=early)
    skew = [i for i in p.issues if i.kind is AnomalyKind.CLOCK_SKEW]
    assert skew and all(i.severity is AnomalySeverity.WARN for i in skew)
    late = [a for a in p.articles.values() if a.published_at > early]
    assert late and all(a.knowable.at == early and not a.knowable.verified for a in late)


def test_conflicting_duplicate_in_one_response_keeps_first_and_warns():
    def dup(b):
        items = next(iter(b["data"].values()))
        items.append(dict(items[0], summary="edited"))
    p = _parse(_mut(dup))
    assert (AnomalySeverity.WARN, AnomalyKind.DUPLICATE_KEY) in _kinds(p)
    assert len(p.articles) == 11


def test_non_success_raises():
    with pytest.raises(P.NewsDecodeError):
        _parse(status=400)
    with pytest.raises(P.NewsDecodeError):
        _parse(b'{"status":"error","errors":[{"errorCode":"UDAPI1189"}]}')


def test_request_path_limits():
    assert P.request_path(["NSE_EQ|X"], 1).endswith(
        "instrument_keys=NSE_EQ%7CX&page_number=1&page_size=100")
    with pytest.raises(ValueError):
        P.request_path([f"k{i}" for i in range(31)], 1)
    with pytest.raises(ValueError):
        P.request_path(["k"], 101)
    with pytest.raises(ValueError):
        P.request_path([], 1)

