"""Dedup decisions dedup-v1: the matrix of docs/NEWS_DEDUP_SPEC.md (pure), and
their storage (test database): every stored article and material edit gets
exactly one decision, a duplicate is marked and still stored, nothing deleted."""

from __future__ import annotations

import datetime as _dt

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import clock
from app.news import dedup as DD
from app.news.store import poll_shadow
from tests.news.test_pilot import BODY, T0
from tests.news.test_store import KEY, TOKEN, unlocked  # noqa: F401 - fixture

T = _dt.datetime(2026, 9, 29, 10, 0, tzinfo=_dt.UTC)


def prior(i=1, url="https://x/a", title="h1", content="c1", ago_h=1):
    return DD.Prior(i, url, title, content, T - _dt.timedelta(hours=ago_h))


def new(priors=(), url="https://x/b", title_hash="h2", content="c2", title="Headline",
        exchange=False, story=None, evidence=None):
    return DD.decide_new(canonical_url=url, title_norm_hash=title_hash, content_sha256=content,
                         title=title, discovered_at=T, priors=list(priors), exchange=exchange,
                         story_method=story, story_evidence=evidence)


class TestNewArticle:
    def test_first_seen(self):
        d = new()
        assert (d.decision, d.rule, d.version) == ("NEW_ARTICLE", "FIRST_SEEN", "dedup-v3")

    def test_founder_of_a_story_is_new(self):
        assert new(story="FOUNDER").decision == "NEW_ARTICLE"

    @pytest.mark.parametrize("kw,rule", [
        ({"url": "https://x/a"}, "SAME_SOURCE_URL"),          # republished under a new id
        ({"content": "c1"}, "SAME_SOURCE_CONTENT"),
        ({"title_hash": "h1"}, "SAME_SOURCE_TITLE"),
    ])
    def test_same_source_duplicates(self, kw, rule):
        d = new([prior()], **kw)
        assert (d.decision, d.rule, d.related_item_id) == ("DUPLICATE_ARTICLE", rule, 1)
        assert d.evidence["duplicate_of"] == 1

    def test_exchange_titles_are_the_filer_name_not_a_duplicate(self):
        # NSE: "Reliance Industries Limited" titles many different filings
        assert new([prior()], title_hash="h1", exchange=True).decision == "NEW_ARTICLE"
        # dedup-v2: a separate filing (another document link) with identical boilerplate
        # text is not a duplicate - it joins the same story instead
        assert new([prior()], content="c1", exchange=True).decision == "NEW_ARTICLE"
        assert new([prior()], content="c1", exchange=True, story="SAME_TITLE").decision == \
            "STORY_RELATED"
        # ...the same document link still is one
        assert new([prior()], url="https://x/a", exchange=True).decision == "DUPLICATE_ARTICLE"

    def test_outside_the_24h_window_is_not_a_duplicate(self):
        assert new([prior(ago_h=25)], url="https://x/a").decision == "NEW_ARTICLE"

    def test_a_later_prior_is_never_the_original(self):
        later = DD.Prior(9, "https://x/a", "h1", "c1", T + _dt.timedelta(minutes=1))
        assert new([later], url="https://x/a").decision == "NEW_ARTICLE"

    def test_the_earliest_match_is_the_original(self):
        d = new([prior(i=2, ago_h=1), prior(i=1, ago_h=3)], url="https://x/a")
        assert d.related_item_id == 1

    @pytest.mark.parametrize("method", ["SAME_URL", "SAME_TITLE", "SIMILAR"])
    def test_joining_a_story_is_related(self, method):
        d = new(story=method, evidence={"score": 0.8})
        assert (d.decision, d.rule) == ("STORY_RELATED", f"STORY_{method}")
        assert d.evidence == {"score": 0.8}

    def test_a_correction_joining_a_story(self):
        d = new(story="SIMILAR", title="Correction: Rupee closes at 96.13, not 96.31")
        assert (d.decision, d.rule) == ("STORY_CORRECTION", "CORRECTION_MARKER")
        assert d.evidence["marker"].lower() == "correction"

    def test_a_correction_marker_alone_founds_nothing_special(self):
        assert new(title="Company issues clarification on news item").decision == "NEW_ARTICLE"

    def test_duplicate_wins_over_story(self):
        assert new([prior()], url="https://x/a", story="SAME_URL").decision == \
            "DUPLICATE_ARTICLE"


class TestEdit:
    def test_title_or_summary_or_time_change_is_an_update(self):
        for ch in (["title"], ["summary"], ["published_at"], ["summary", "source_updated_at"]):
            d = DD.decide_edit(ch, old_title="A", new_title="A2")
            assert (d.decision, d.rule) == ("STORY_UPDATE", "MATERIAL_EDIT")

    def test_only_source_updated_at_is_not_material(self):
        assert DD.decide_edit(["source_updated_at"], old_title="A", new_title="A") is None

    def test_title_gaining_a_marker_is_a_correction(self):
        d = DD.decide_edit(["title"], old_title="Rupee at 96.31",
                           new_title="Rupee at 96.13 (corrected)")
        assert d.decision == "STORY_CORRECTION"

    def test_marker_already_there_is_an_update(self):
        d = DD.decide_edit(["title"], old_title="Clarification on X",
                           new_title="Clarification on X and Y")
        assert d.decision == "STORY_UPDATE"


# ── storage (test database) ──────────────────────────────────────────────────
def feed(body=BODY):
    return httpx.MockTransport(lambda req: httpx.Response(200, content=body))


async def q(s, sql, **kw):
    return (await s.execute(text(sql), kw)).all()


@pytest.mark.db
@pytest.mark.integration
class TestStored:
    async def test_every_stored_article_has_one_decision(self, db_session, unlocked):  # noqa: F811
        r = await poll_shadow(db_session, KEY, token=TOKEN, transport=feed())
        items = (await q(db_session, "select count(*) from news_item"))[0][0]
        rows = await q(db_session, """select d.decision, count(*) from news_decision d
            group by 1 order by 1""")
        assert sum(n for _, n in rows) == items == r["inserted"]
        assert sum(r["decisions"].values()) == items
        assert (await q(db_session, """select count(*) from news_item i where not exists
            (select 1 from news_decision d where d.item_id = i.id)"""))[0][0] == 0
        assert (await q(db_session, """select count(*) from news_decision
            where knowable_at < decided_at or rule_version <> 'dedup-v3'"""))[0][0] == 0

    async def test_an_edit_gets_an_update_decision(self, db_session, unlocked):  # noqa: F811
        await poll_shadow(db_session, KEY, token=TOKEN, transport=feed())
        clock.freeze(T0 + _dt.timedelta(minutes=10))
        edited = BODY.replace(b"Jullundur Motor Agency (Delhi) Limited has informed",
                              b"Jullundur Motor Agency (Delhi) Limited has now informed")
        r = await poll_shadow(db_session, KEY, token=TOKEN, transport=feed(edited))
        assert r["decisions"] == {"STORY_UPDATE": 1}
        d = await q(db_session, """select d.decision, d.rule, d.evidence, o.changed
            from news_decision d join news_item_observation o on o.id = d.observation_id""")
        assert d == [("STORY_UPDATE", "MATERIAL_EDIT", {"changed": ["summary"]}, ["summary"])]

    async def test_decisions_are_append_only(self, db_session, unlocked):  # noqa: F811
        await poll_shadow(db_session, KEY, token=TOKEN, transport=feed())
        with pytest.raises(DBAPIError, match="append-only"):
            async with db_session.begin_nested():
                await db_session.execute(text("delete from news_decision"))

    async def test_a_duplicate_must_name_its_original(self, db_session, unlocked):  # noqa: F811
        await poll_shadow(db_session, KEY, token=TOKEN, transport=feed())
        iid, pid = (await q(db_session, "select id, first_poll_id from news_item limit 1"))[0]
        with pytest.raises(DBAPIError, match="ck_news_decision_duplicate_of"):
            async with db_session.begin_nested():
                await db_session.execute(text("""insert into news_decision (item_id, poll_id,
                    decision, rule, rule_version, evidence, decided_at, knowable_at)
                    values (:i, :p, 'DUPLICATE_ARTICLE', 'X', 'test', '{}', now(), now())"""),
                    {"i": iid, "p": pid})


class TestRegulatorCorrections:
    ORDER = "Final order in the matter of Adani Group Companies for alleged violations"
    CORR = "Corrigendum to the final order in the matter of Adani Group Companies"

    def pri(self, title, i=7, ago_h=3):
        return DD.Prior(i, f"https://s/{i}", "t", f"c{i}", T - _dt.timedelta(hours=ago_h),
                        title)

    def test_a_corrigendum_corrects_the_earlier_document_of_the_same_matter(self):
        d = new([self.pri(self.ORDER)], title=self.CORR, exchange=True)
        assert (d.decision, d.rule) == ("STORY_CORRECTION", "CORRECTION_OF_DOCUMENT")
        assert d.evidence["corrects"] == 7

    def test_another_matter_or_no_matter_is_not_a_correction(self):
        other = self.pri("Final order in the matter of Some Other Ltd")
        assert new([other], title=self.CORR, exchange=True).decision == "NEW_ARTICLE"
        assert new([self.pri(self.ORDER)], title="Corrigendum to circular dated 1 Sep",
                   exchange=True).decision == "NEW_ARTICLE"          # nothing guessed

    def test_the_rule_is_for_documents_not_media(self):
        assert new([self.pri(self.ORDER)], title=self.CORR).decision == "NEW_ARTICLE"
