# News point-in-time specification

**Code:**

- `backend/app/news/store.py` (write)
- `backend/app/canon/news_pit.py` (read)
- `backend/app/features/news_features.py` (Stage 3 v2 candidate)

**Tests:** `tests/news/test_pit_replay.py`, `test_news_pit.py`, `test_store.py`, `test_failures_security.py`.

## The rule

**A news fact is knowable from the moment Prajna first observed it, never from the time a publisher claims.**

A reader at `as_of` sees a row only if its `knowable_at < as_of` (strict), where:

| Row | `knowable_at` | Enforced by |
|---|---|---|
| `news_item` | `discovered_at`: the end of the poll that first saw it | DB check `knowable_at >= discovered_at`; the store writes `knowable_at = discovered_at` |
| title / summary / time **edits** (`news_item_observation`) | `observed_at`: the poll that saw the change | the reader takes the latest observation **before** `as_of`, else the first version |
| event category, market scope, entity link, mention, story membership, assessment, dedup decision, AI output | **its own** `knowable_at` (when it was computed) | DB checks `knowable_at >= classified_at / mapped_at / joined_at / assessed_at / decided_at / generated_at`; the reader filters each one separately |

**`published_at` is stored exactly as the publisher gave it** (`published_at_raw` too). It is used only to **measure** latency, never to decide visibility.

### Special cases

| Case | Behaviour |
|---|---|
| **Backlog** (items in a source's first successful poll) | `knowable_at` = that poll. Whether the item was visible earlier is unknown, so it is never back-dated. Excluded from latency |
| **Late item** (published 06:00, first seen 11:00) | knowable at 11:00 |
| **Future-dated item** (a publisher time after discovery) | knowable at discovery; its negative latency is counted as CLOCK_SKEW, never averaged |
| **Date-only source** (SEBI) | no publication time; knowable at discovery; latency NOT_MEASURABLE |
| **Zone-less or unparseable time** | `published_at` = NULL with a BAD_TIMESTAMP issue. The time is never guessed |
| **An item disappears from the feed** | nothing is deleted; it stays knowable |
| **Duplicate** | stored, and knowable like any item. Its DUPLICATE_ARTICLE decision is knowable only from `decided_at`, so a reader before that sees it undecided |
| **SHADOW rows** | never visible: the reader joins `news_poll.mode = 'PRODUCTION'` |

## Verified by replay

`tests/news/test_pit_replay.py` writes one PRODUCTION day through the real store:

| Poll (IST) | Items |
|---|---|
| 08:40 | backlog A, B |
| 08:57 | A edited; C new |
| 09:05 | D, a same-source duplicate of C |
| 09:20 | E, whose publisher time is 10:30 |
| 11:00 | F, whose publisher time is 06:00 |

It then reads with `news_pit` at the 8 instants:

| as_of | Visible |
|---|---|
| 08:30 | nothing |
| 08:55 | A (original summary), B |
| 09:00 | A (edited summary), B, C (NEW_ARTICLE) |
| 09:15 | + D, marked DUPLICATE_ARTICLE of C |
| 09:30 | + E (knowable 09:20, although "published" 10:30); F not visible |
| 10:00 | the same as 09:30 |
| 12:00 | + F, knowable 11:00, never back-dated to 06:00 |
| 15:00 | the same six |

At every instant, every returned row has `knowable_at < as_of`, and so does its story membership. A separate test shows that SHADOW rows are never returned.

## Stage 3 (v2 candidate)

Features read only `news_pit` at the snapshot's `as_of`. Their quality state:

| State | Condition | Values |
|---|---|---|
| NORMAL | a PRODUCTION poll succeeded within 2 h before `as_of` | counts; 0 is a real zero |
| MISSING | no PRODUCTION poll before `as_of` at all | every feature MISSING_INPUT |
| STALE | PRODUCTION polls exist, but none succeeded within 2 h | every feature MISSING_INPUT |
| INVALID | a returned row is not knowable before `as_of`, or the reader's row limit (50,000) was reached | every feature MALFORMED_INPUT (fail closed) |

**Duplicates are never counted.** Replay check: 5 counted plus 1 duplicate at 12:00; STALE at 15:00; MISSING at 08:30.
