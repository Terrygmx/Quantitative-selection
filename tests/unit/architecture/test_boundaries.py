from pathlib import Path
import ast


def test_application_and_strategies_do_not_import_adapter_contracts():
    repo_root = Path(__file__).resolve().parents[3]
    root = repo_root / "src" / "quant_agent"

    offenders = [
        str(path)
        for directory in ("application", "strategies")
        for path in (root / directory).rglob("*.py")
        if any(
            isinstance(node, ast.ImportFrom)
            and node.module == "quant_agent.adapters.market_data"
            or isinstance(node, ast.Import)
            and node.names[0].name == "quant_agent.adapters.market_data"
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        )
    ]

    assert offenders == []
