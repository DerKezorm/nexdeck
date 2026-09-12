"""A refused address reads as one sentence, without a double space.

⚠️ The host went into the message with a space after it, and the sentence adds
its own: "127.0.0.1  is not an address nexdeck calls." It stood like that in the
problems card and under every refused check. Found on 12.09.2026.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from app import config
from app.adapters.base import AdapterError, guard_member_target, guard_outbound


@pytest.fixture(autouse=True)
def fresh_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("NEXDECK_ALLOW_LOOPBACK_TARGETS", raising=False)
    config.reset_settings_cache()
    yield
    config.reset_settings_cache()


@pytest.mark.parametrize(("check", "url", "host"), [
    (guard_member_target, "http://127.0.0.1:8000/", "127.0.0.1"),
    (guard_outbound, "http://169.254.1.1/", "169.254.1.1"),
])
def test_the_refusal_names_the_host_in_one_clean_sentence(check: Callable[[str], None], url: str, host: str) -> None:
    with pytest.raises(AdapterError) as refused:
        check(url)
    assert refused.value.message == f"{host} is not an address nexdeck calls."
