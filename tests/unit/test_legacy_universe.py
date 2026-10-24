from pathlib import Path

from tail_momentum_selector import load_universe


def test_universe_file_overrides_codes(tmp_path: Path):
    universe = tmp_path / "universe.txt"
    universe.write_text("sh600519\n\n# comment\n sz000858 \n", encoding="utf-8")

    assert load_universe("sh688981,sz300750", str(universe)) == ["sh600519", "sz000858"]
