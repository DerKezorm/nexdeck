import pytest

from managed_update_transaction import (
    ManagedUpdateOperations,
    execute_managed_update,
)


IMAGE_ID = "sha256:" + "a" * 64


def make_operations(events, fail_at=None):
    def action(name, result=None):
        def run(*args):
            events.append(name)
            if name == fail_at:
                raise RuntimeError(f"Simulated {name} failure")
            return result
        return run

    return ManagedUpdateOperations(
        verify_deployment=action("verify"),
        resolve_target=action("resolve", "target"),
        prepare_image=action("prepare", IMAGE_ID),
        write_override=action("write"),
        recreate=action("recreate"),
        verify_image=action("verify_image"),
        wait_healthy=action("health"),
        rollback=action("rollback"),
    )


def test_successful_managed_update():
    events = []

    result = execute_managed_update(
        make_operations(events)
    )

    assert result == IMAGE_ID
    assert events == [
        "verify",
        "resolve",
        "prepare",
        "verify",
        "write",
        "recreate",
        "verify_image",
        "health",
    ]


@pytest.mark.parametrize("failure", [
    "write",
    "recreate",
    "verify_image",
    "health",
])
def test_mutation_failure_triggers_rollback(failure):
    events = []

    with pytest.raises(RuntimeError, match=failure):
        execute_managed_update(
            make_operations(events, fail_at=failure)
        )

    assert events[-1] == "rollback"


@pytest.mark.parametrize("failure", [
    "verify",
    "resolve",
    "prepare",
])
def test_preparation_failure_does_not_rollback(failure):
    events = []

    with pytest.raises(RuntimeError, match=failure):
        execute_managed_update(
            make_operations(events, fail_at=failure)
        )

    assert "rollback" not in events
    assert "write" not in events
