import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_ENTRYPOINT = PROJECT_ROOT / "src" / "tail_momentum_selector.py"


def test_legacy_cli_help_is_usable():
    result = subprocess.run(
        [sys.executable, str(LEGACY_ENTRYPOINT), "--help"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "A股尾盘启动隔夜策略扫描器" in result.stdout
