from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path


def python_files() -> list[Path]:
    return (
        sorted(Path("marketimmune").rglob("*.py"))
        + sorted(Path("aegisbench").rglob("*.py"))
        + sorted(Path("hindsight").rglob("*.py"))
        + sorted(Path("scripts").glob("*.py"))
    )


def fallback_typecheck() -> int:
    missing_annotations: list[str] = []
    for path in python_files():
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))
        for node in ast.walk(ast.parse(source, filename=str(path))):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if node.name.startswith("_") and node.name != "__init__":
                    continue
                if node.returns is None:
                    missing_annotations.append(
                        f"{path}:{node.lineno} {node.name} missing return type"
                    )
                for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
                    if arg.arg in {"self", "cls"}:
                        continue
                    if arg.annotation is None:
                        missing_annotations.append(
                            f"{path}:{node.lineno} {node.name}.{arg.arg} missing type"
                        )
    if missing_annotations:
        print("\n".join(missing_annotations))
        return 1
    print("fallback typecheck passed: AST parse and public annotations clean")
    return 0


def main() -> int:
    if importlib.util.find_spec("mypy") is None:
        return fallback_typecheck()
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "mypy",
                "--config-file",
                "pyproject.toml",
                "marketimmune",
                "aegisbench",
                "hindsight",
            ],
            check=False,
            text=True,
        )
    except OSError:
        return fallback_typecheck()
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
