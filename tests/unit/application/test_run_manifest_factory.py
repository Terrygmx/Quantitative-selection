from datetime import datetime, timezone

import pytest

from quant_agent.application.runs import RunManifestFactory
from quant_agent.domain.models import RunManifest
from quant_agent.domain.clock import FixedClock


def test_manifest_factory_uses_injected_clock_and_generates_run_ids():
    created_at = datetime(2026, 10, 24, 9, 30, tzinfo=timezone.utc)
    factory = RunManifestFactory(clock=FixedClock(created_at))
    inputs = {
        "git_sha": "a" * 40,
        "config_hash": "b" * 64,
        "data_snapshot": "snapshot-1",
        "seed": 42,
    }

    manifest = factory.create(**inputs)

    assert manifest.created_at == created_at
    assert manifest.git_sha == inputs["git_sha"]
    assert manifest.config_hash == inputs["config_hash"]
    assert manifest.data_snapshot == inputs["data_snapshot"]
    assert manifest.seed == 42
    assert manifest.run_id
    other = factory.create(**inputs)
    assert other.run_id != manifest.run_id
    assert manifest.content_hash != other.content_hash


def test_manifest_factory_can_use_deterministic_run_ids_for_replays():
    factory = RunManifestFactory(
        clock=FixedClock(datetime(2026, 10, 24, 9, 30, tzinfo=timezone.utc)),
        run_id_factory=lambda: "replay-1",
    )

    manifest = factory.create(
        git_sha="a" * 40,
        config_hash="b" * 64,
        data_snapshot="snapshot-1",
        seed=42,
    )

    assert manifest.run_id == "replay-1"
    assert RunManifest.from_dict(manifest.to_dict()) == manifest


def test_manifest_factory_rejects_naive_clock_time():
    class NaiveClock:
        def now(self):
            return datetime(2026, 10, 24, 9, 30)

    with pytest.raises(ValueError, match="timezone-aware"):
        RunManifestFactory(clock=NaiveClock()).create(
            git_sha="a" * 40,
            config_hash="b" * 64,
            data_snapshot="snapshot-1",
            seed=42,
        )
