from __future__ import annotations

from collections.abc import Callable
import secrets

from quant_agent.ports.clock import Clock, SystemClock
from quant_agent.domain.models import RunManifest


def _random_run_id() -> str:
    return f"run-{secrets.token_hex(8)}"


class RunManifestFactory:
    def __init__(
        self,
        clock: Clock = SystemClock(),
        run_id_factory: Callable[[], str] = _random_run_id,
    ):
        self.clock = clock
        self.run_id_factory = run_id_factory

    def create(
        self,
        *,
        git_sha: str,
        config_hash: str,
        data_snapshot: str,
        seed: int,
    ) -> RunManifest:
        now = self.clock.now()
        if now.tzinfo is None:
            raise ValueError("clock must return timezone-aware datetime")
        return RunManifest(
            run_id=self.run_id_factory(),
            git_sha=git_sha,
            config_hash=config_hash,
            data_snapshot=data_snapshot,
            seed=seed,
            created_at=now,
        )
