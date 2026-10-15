from asyncio import CancelledError
from unittest.mock import Mock

import pytest
from pytest import LogCaptureFixture, MonkeyPatch

from backend_app.db.session import get_database_session


def install_session(monkeypatch: MonkeyPatch) -> Mock:
    session = Mock()
    monkeypatch.setattr("backend_app.db.session.get_session_factory", lambda: lambda: session)
    return session


def test_session_cleanup_does_not_commit(monkeypatch: MonkeyPatch) -> None:
    session = install_session(monkeypatch)
    dependency = get_database_session()
    assert next(dependency) is session
    with pytest.raises(StopIteration):
        next(dependency)
    session.commit.assert_not_called()
    session.close.assert_called_once()


@pytest.mark.parametrize("error", [RuntimeError("failure"), KeyboardInterrupt(), CancelledError()])
def test_session_rolls_back_and_preserves_failure(
    monkeypatch: MonkeyPatch, error: BaseException
) -> None:
    session = install_session(monkeypatch)
    dependency = get_database_session()
    next(dependency)
    with pytest.raises(type(error)) as caught:
        dependency.throw(error)
    assert caught.value is error
    session.rollback.assert_called_once()
    session.close.assert_called_once()
    session.commit.assert_not_called()


def test_cleanup_failure_does_not_mask_original_failure(
    monkeypatch: MonkeyPatch, caplog: LogCaptureFixture
) -> None:
    session = install_session(monkeypatch)
    session.rollback.side_effect = RuntimeError("rollback-secret")
    session.close.side_effect = RuntimeError("close-secret")
    dependency = get_database_session()
    next(dependency)
    original = ValueError("original")
    with pytest.raises(ValueError) as caught:
        dependency.throw(original)
    assert caught.value is original
    assert "rollback-secret" not in caplog.text and "close-secret" not in caplog.text


def test_close_failure_without_original_failure_propagates(monkeypatch: MonkeyPatch) -> None:
    session = install_session(monkeypatch)
    session.close.side_effect = RuntimeError("close failed")
    dependency = get_database_session()
    next(dependency)
    with pytest.raises(RuntimeError, match="close failed"):
        next(dependency)
