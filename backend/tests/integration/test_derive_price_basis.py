"""prajna derive price-basis --commit (hardening phase 6): every stored bar's
payload gets exactly one basis row; idempotent. Regression: the commit path
failed with AmbiguousColumnError (instrument also carries payload_sha256) and
was never exercised by a test - the dry run only counts."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from app.core import clock
from app.ingest.ca_derive import derive_price_basis
from tests.support import stage2_seed as SEED
from tests.support.stage2_seed import NOW

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]


async def test_commit_gives_every_bar_payload_one_basis_and_is_idempotent(db_session):
    s = db_session
    clock.freeze(NOW)
    try:
        await SEED.seed(s)
        payloads = (await s.execute(text("select count(distinct payload_sha256) from ohlcv_bar"))).scalar()
        assert payloads >= 1
        first = await derive_price_basis(s, commit=True, token=TOKEN)
        assert first["missing"] == payloads and first["inserted"] == payloads
        lacking = (await s.execute(text("""select count(*) from ohlcv_bar b
            where not exists (select 1 from ohlcv_payload_basis p where p.payload_sha256 = b.payload_sha256)"""))).scalar()
        assert lacking == 0
        bases = {r[0] for r in (await s.execute(text("select distinct price_basis from ohlcv_payload_basis"))).all()}
        assert bases <= {"RAW_OBSERVED", "VENDOR_ADJUSTED"}
        again = await derive_price_basis(s, commit=True, token=TOKEN)
        assert again["missing"] == 0 and again["inserted"] == 0          # idempotent
    finally:
        clock.unfreeze()
