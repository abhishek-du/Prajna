"""Upstox news -> raw archive -> parse -> news_article + news_instrument.

    for each batch of <=30 instrument keys:
        IngestRunner.open                one run per batch, BEFORE the requests
        pages 1..total_pages             every page archived BEFORE parsing
        parse_news                       pure
        articles  -> news_article        identity (heading sha256, published_at,
                                         source); identical = no-op; a different
                                         stored version is kept and the
                                         difference is a WARN (never overwritten)
        links     -> news_instrument     the vendor's grouping, ON CONFLICT no-op
        finalize(outcome=...)            per-key counts, pages, totals

Only the last 7 days are served, so this job must run at least weekly (daily
in practice) or news is lost for good. A batch that cannot collect every
record the vendor reports (total_records) records COVERAGE_DROP (WARN) with
the numbers; a rerun picks the rest up, and duplicates are no-ops.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.knowable import for_snapshot_download
from app.contracts.provenance import AnomalyKind, AnomalySeverity, RunStatus, Source
from app.core.clock import IST
from app.core.errors import IngestCheckFailed, RateLimited, VendorAuthError, VendorError
from app.db.models import NewsArticle, NewsInstrument
from app.ingest.runner import IngestRunner
from app.parsers import upstox_news as P
from app.storage.payload_store import PayloadStore
from app.vendor.upstox.rest import UpstoxRestClient

SOURCE = Source.UPSTOX_REST_V2.value
STREAM = "news.instrument_keys"


def batches(keys: list[str], size: int = P.MAX_KEYS) -> list[list[str]]:
    ks = sorted(set(keys))
    return [ks[i:i + size] for i in range(0, len(ks), size)]


@dataclass(slots=True)
class BatchResult:
    keys: list[str]
    status: str                        # COMPLETE / FAILED / ABORTED / NOT_ATTEMPTED
    run_id: uuid.UUID | None = None
    pages: int = 0
    articles: int = 0
    inserted: int = 0
    already_present: int = 0
    links_inserted: int = 0
    outcome: dict[str, Any] | None = None
    error: str | None = None


@dataclass(slots=True)
class NewsReport:
    committed: bool
    results: list[BatchResult] = field(default_factory=list)
    stopped: str | None = None

    def count(self, s: str) -> int:
        return sum(1 for r in self.results if r.status == s)

    def summary(self) -> dict[str, Any]:
        return {"committed": self.committed, "batches": len(self.results),
                "pages": sum(r.pages for r in self.results),
                "articles_seen": sum(r.articles for r in self.results),
                "inserted": sum(r.inserted for r in self.results),
                "already_present": sum(r.already_present for r in self.results),
                "links_inserted": sum(r.links_inserted for r in self.results),
                "stopped": self.stopped,
                **{s.lower(): self.count(s) for s in ("COMPLETE", "FAILED", "ABORTED",
                                                       "NOT_ATTEMPTED")}}


class NewsIngestor:
    def __init__(self, session: AsyncSession, rest: UpstoxRestClient, store: PayloadStore, *,
                 commit: bool, token: str | None, operator: str = "cli"):
        self.s, self.rest, self.store = session, rest, store
        self.commit, self.token, self.operator = commit, token, operator

    async def run(self, keys: list[str]) -> NewsReport:
        rep = NewsReport(committed=self.commit)
        for b in batches(keys):
            if rep.stopped:
                rep.results.append(BatchResult(b, "NOT_ATTEMPTED", error=rep.stopped))
                continue
            res = await self._one(b)
            rep.results.append(res)
            if res.status == "ABORTED":
                rep.stopped = res.error
        return rep

    async def _one(self, keys: list[str]) -> BatchResult:
        runner = IngestRunner(
            self.s, source=SOURCE, stream=STREAM, vendor_endpoint="/v2/news",
            request_params={"category": "instrument_keys", "instrument_keys": keys,
                            "page_size": P.MAX_PAGE_SIZE},
            operator=self.operator)
        ctx = await runner.open(commit=self.commit, token=self.token)
        res = BatchResult(keys, "RUNNING", run_id=ctx.run_id)
        checks = ctx.checks
        merged = P.ParsedNews()
        payload_of: dict[tuple, tuple[str, _dt.datetime]] = {}    # article key -> (sha, fetched)
        link_payload: dict[tuple, tuple[str, _dt.datetime]] = {}
        shas: list[str] = []
        try:
            page, total_pages, first_total = 1, 1, None
            while page <= total_pages:
                path = P.request_path(keys, page)
                try:
                    r = await self.rest.get(path)
                except (RateLimited, VendorAuthError) as e:
                    await runner.fail(str(e), status=RunStatus.ABORTED)
                    res.status, res.error = "ABORTED", f"{type(e).__name__}: {e}"
                    return res
                except VendorError as e:
                    checks.add(AnomalySeverity.FAIL, AnomalyKind.VENDOR_ERROR, STREAM,
                               error=str(e)[:300])
                    raise IngestCheckFailed(str(e)) from None
                stored = self.store.put(r.data, source=SOURCE, fetched_at=r.fetched_at, ext="json")
                shas.append(stored.sha256)
                if self.commit:
                    await runner.record_payload(stored, http_status=r.status, vendor_endpoint=r.url)
                if r.status != 200:
                    checks.add(AnomalySeverity.FAIL, AnomalyKind.VENDOR_ERROR, STREAM,
                               http_status=r.status, codes=r.error_codes, page=page,
                               payload_sha256=stored.sha256)
                    raise IngestCheckFailed(f"HTTP {r.status} {r.error_codes}")
                try:
                    pn = P.parse_news(r.data, http_status=r.status, requested_keys=keys,
                                      fetched_at=r.fetched_at)
                except P.NewsDecodeError as e:
                    checks.add(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, STREAM,
                               error=str(e)[:300], payload_sha256=stored.sha256)
                    raise IngestCheckFailed(str(e)) from None
                for i in pn.issues:
                    checks.add(i.severity, i.kind, i.subject, **i.detail,
                               payload_sha256=stored.sha256)
                checks.raise_if_failed()
                for k, a in pn.articles.items():
                    if k not in merged.articles:
                        merged.articles[k] = a
                        payload_of[k] = (stored.sha256, r.fetched_at)
                for ln in pn.links:
                    if ln not in merged.links:
                        merged.links.add(ln)
                        link_payload[ln] = (stored.sha256, r.fetched_at)
                for ik, n in pn.per_key.items():
                    merged.per_key[ik] = merged.per_key.get(ik, 0) + n
                if first_total is None:
                    first_total = pn.total_records
                total_pages = min(max(total_pages, pn.total_pages or 1), P.MAX_PAGES)
                if (pn.total_pages or 1) > P.MAX_PAGES:
                    checks.add(AnomalySeverity.FAIL, AnomalyKind.COVERAGE_CAP, STREAM,
                               reason="more pages than the documented maximum",
                               total_pages=pn.total_pages)
                    raise IngestCheckFailed("news pages exceed the documented maximum")
                last_total = pn.total_records
                page += 1
            res.pages = page - 1
            res.articles = len(merged.articles)
            res.outcome = {"pages": res.pages, "total_records_first": first_total,
                           "total_records_last": last_total, "distinct_articles": res.articles,
                           "links": len(merged.links), "keys_with_news": len(merged.per_key),
                           "payload_sha256": shas}
            if last_total is not None and res.articles < last_total:
                checks.add(AnomalySeverity.WARN, AnomalyKind.COVERAGE_DROP, STREAM,
                           reason="fewer distinct articles collected than total_records "
                                  "(pages shifted while paging); a rerun collects the rest",
                           collected=res.articles, total_records=last_total)
            ins, present, lnk = await self._write(merged, payload_of, link_payload, ctx.run_id,
                                                  checks)
            res.inserted, res.already_present, res.links_inserted = ins, present, lnk
            checks.raise_if_failed()
            ctx.logical_date = max(f for _, f in payload_of.values()).astimezone(IST).date() \
                if payload_of else None
            await runner.finalize(rows_written=ins + lnk, outcome=res.outcome)
            res.status = "COMPLETE"
            return res
        except IngestCheckFailed as e:
            await runner.fail(str(e), outcome=res.outcome)
            res.status, res.error = "FAILED", str(e)[:500]
            res.inserted = res.links_inserted = 0
            return res
        except BaseException as e:
            await runner.fail(f"{type(e).__name__}: {e}", outcome=res.outcome)
            raise

    async def _write(self, pn: P.ParsedNews, payload_of, link_payload, run_id,
                     checks) -> tuple[int, int, int]:
        if not pn.articles:
            return 0, 0, 0
        keys = list(pn.articles)
        existing = {(e.headline_sha256, e.published_at): e for e in (await self.s.execute(
            select(NewsArticle).where(
                tuple_(NewsArticle.headline_sha256, NewsArticle.published_at).in_(keys),
                NewsArticle.source == SOURCE))).scalars()}
        ids: dict[tuple, int] = {}
        new_rows, present = [], 0
        for k, a in pn.articles.items():
            e = existing.get(k)
            if e is not None:
                ids[k] = e.id
                if (e.url, e.body, e.vendor_article_id) == (a.url, a.body, a.vendor_article_id):
                    present += 1
                else:
                    checks.add(AnomalySeverity.WARN, AnomalyKind.DUPLICATE_KEY, "news",
                               reason="stored article differs from the new observation; the "
                                      "stored version is kept (append-only; raw is archived)",
                               heading=a.headline[:120], stored_payload_sha256=e.payload_sha256)
                    present += 1
                continue
            sha, fetched = payload_of[k]
            new_rows.append({
                "headline": a.headline, "body": a.body, "url": a.url, "publisher": None,
                "published_at": a.published_at, "headline_sha256": a.headline_sha256,
                "vendor_article_id": a.vendor_article_id, "vendor_payload": a.vendor_payload,
                "source": SOURCE, "run_id": run_id, "payload_sha256": sha, "fetched_at": fetched,
                "knowable_at": a.knowable.at, "knowable_at_verified": a.knowable.verified,
                "knowable_at_basis": a.knowable.basis[:200]})
        if not self.commit:
            return 0, present, 0
        for i in range(0, len(new_rows), 500):
            got = await self.s.execute(
                pg_insert(NewsArticle).values(new_rows[i:i + 500]).returning(
                    NewsArticle.id, NewsArticle.headline_sha256, NewsArticle.published_at))
            for nid, hs, pub in got.all():
                ids[(hs, pub)] = nid
        links = []
        for (akey, ikey) in pn.links:
            sha, fetched = link_payload[(akey, ikey)]
            kn = for_snapshot_download(fetched)
            links.append({"news_id": ids[akey], "instrument_key": ikey, "source": SOURCE,
                          "run_id": run_id, "payload_sha256": sha, "fetched_at": fetched,
                          "knowable_at": kn.at, "knowable_at_verified": kn.verified,
                          "knowable_at_basis": ("vendor news grouping; tagging time not "
                                                "supplied, fetched_at used")})
        n_links = 0
        for i in range(0, len(links), 1000):
            got = await self.s.execute(
                pg_insert(NewsInstrument).values(links[i:i + 1000]).on_conflict_do_nothing()
                .returning(NewsInstrument.id))
            n_links += len(got.all())
        return len(new_rows), present, n_links
