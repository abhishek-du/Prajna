"""The guards themselves. If these fail, nothing else in the suite is trustworthy."""

from __future__ import annotations

import os
import socket

import pytest

from app.core.config import FORBIDDEN_DATABASES, Settings, database_name
from app.core.errors import AuthorizationError, DatabaseIsolationError
from app.db.engine import assert_not_v1, build_engine


class TestDatabaseIsolation:
    def test_engine_refuses_v1_database(self):
        with pytest.raises(DatabaseIsolationError, match="autotrade_pro"):
            assert_not_v1("postgresql+asyncpg://u:p@localhost:5432/autotrade_pro")

    def test_engine_refuses_v1_test_database(self):
        with pytest.raises(DatabaseIsolationError):
            assert_not_v1("postgresql+asyncpg://u:p@localhost:5432/autotrade_test")

    def test_build_engine_refuses_v1(self):
        with pytest.raises(DatabaseIsolationError):
            build_engine("postgresql+asyncpg://u:p@localhost:5432/autotrade_pro")

    def test_settings_validator_refuses_v1(self, monkeypatch):
        monkeypatch.setenv("PRAJNA_DATABASE_URL",
                           "postgresql+asyncpg://u:p@localhost:5432/autotrade_pro")
        with pytest.raises(Exception, match="V1|autotrade_pro"):
            Settings(_env_file=None)

    def test_dsn_naming_no_database_is_refused(self):
        with pytest.raises(DatabaseIsolationError):
            assert_not_v1("postgresql+asyncpg://u:p@localhost:5432/")

    def test_prajna_dsn_is_accepted(self):
        assert_not_v1("postgresql+asyncpg://u:p@localhost:5432/prajna")

    def test_forbidden_set_covers_both_v1_databases(self):
        assert FORBIDDEN_DATABASES == {"autotrade_pro", "autotrade_test"}

    def test_tests_run_against_prajna_only(self):
        assert database_name(os.environ["PRAJNA_DATABASE_URL"]).startswith("prajna")


class TestNetworkGuard:
    def test_outbound_is_blocked_by_default(self):
        from tests.conftest import NetworkAccessBlocked
        with pytest.raises(NetworkAccessBlocked):
            socket.create_connection(("api.upstox.com", 443), timeout=2)

    def test_loopback_still_reachable(self):
        # The test database must remain usable while the guard is active.
        s = socket.socket()
        s.settimeout(2)
        s.connect(("127.0.0.1", 5432))
        s.close()


class TestWriteAuthorization:
    def test_commit_without_token_is_refused(self, monkeypatch):
        from app.core import authz
        monkeypatch.setattr(authz, "get_settings",
                            lambda: type("S", (), {"PRAJNA_WRITE_TOKEN": "secret"})())
        with pytest.raises(AuthorizationError, match="requires a write token"):
            authz.authorize_write(None)

    def test_wrong_token_is_refused(self, monkeypatch):
        from app.core import authz
        monkeypatch.setattr(authz, "get_settings",
                            lambda: type("S", (), {"PRAJNA_WRITE_TOKEN": "secret"})())
        with pytest.raises(AuthorizationError, match="rejected"):
            authz.authorize_write("wrong")

    def test_unconfigured_token_refuses_all_commits(self, monkeypatch):
        from app.core import authz
        monkeypatch.setattr(authz, "get_settings",
                            lambda: type("S", (), {"PRAJNA_WRITE_TOKEN": ""})())
        with pytest.raises(AuthorizationError, match="not configured"):
            authz.authorize_write("anything")

    def test_correct_token_returns_fingerprint(self, monkeypatch):
        from app.core import authz
        monkeypatch.setattr(authz, "get_settings",
                            lambda: type("S", (), {"PRAJNA_WRITE_TOKEN": "secret"})())
        fp = authz.authorize_write("secret")
        assert fp == authz.token_fingerprint("secret")
        assert len(fp) == 64
