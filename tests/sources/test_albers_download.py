from __future__ import annotations

import hashlib
import http.server
import itertools
import json
import threading
from pathlib import Path

import pytest

from tests.conftest import load_path

alb = load_path("albers", "marketimmune/sources/albers_download.py")
BLOB = bytes(range(256)) * 4000  # ~1 MB


class RangeHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        rng = self.headers.get("Range")
        if not rng:
            self.send_response(200)
            self.send_header("Content-Length", str(len(BLOB)))
            self.end_headers()
            self.wfile.write(BLOB)
            return
        start_s, end_s = rng.removeprefix("bytes=").split("-")
        start, end = int(start_s), int(end_s) if end_s else len(BLOB) - 1
        body = BLOB[start : end + 1]
        self.send_response(206)
        self.send_header("Content-Range", f"bytes {start}-{end}/{len(BLOB)}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server():  # type: ignore[no-untyped-def]
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/blob"
    httpd.shutdown()


def test_split_covers_file() -> None:
    size = 10 * alb.MIN_SEGMENT + 3
    r = alb.split(size, 8)
    assert r[0][0] == 0 and r[-1][1] == size and len(r) == 8
    assert all(a[1] == b[0] for a, b in itertools.pairwise(r))
    assert alb.split(1000, 8) == [(0, 1000)]


def test_segmented_download_resumes_and_verifies(
    tmp_path: Path, server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(alb, "MIN_SEGMENT", 64 * 1024)
    rf = alb.RemoteFile("blob.bin", len(BLOB), hashlib.md5(BLOB).hexdigest(), server)
    # Simulate an interrupted earlier run: a plan with 4 segments, two partly done.
    segdir = tmp_path / "blob.bin.parts"
    segdir.mkdir()
    ranges = alb.split(len(BLOB), 4)
    (segdir / "plan.json").write_text(json.dumps({"size": rf.size, "md5": rf.md5, "ranges": ranges}))
    (segdir / "seg000").write_bytes(BLOB[:1000])
    (segdir / "seg002").write_bytes(BLOB[ranges[2][0] : ranges[2][0] + 5000])
    out = alb.download(rf, tmp_path, segments=8)  # the saved 4-segment plan wins
    assert out.read_bytes() == BLOB
    assert (tmp_path / "blob.bin.md5ok").exists() and not segdir.exists()
    assert alb.download(rf, tmp_path, segments=8) == out  # verified: skipped


def test_bad_md5_is_kept_aside(tmp_path: Path, server: str) -> None:
    rf = alb.RemoteFile("blob.bin", len(BLOB), "0" * 32, server)
    with pytest.raises(RuntimeError, match="md5"):
        alb.download(rf, tmp_path, segments=2)
    assert (tmp_path / "blob.bin.bad").exists() and not (tmp_path / "blob.bin").exists()


def test_manifest_keeps_rows_from_earlier_sets(tmp_path: Path) -> None:
    index = {
        k: alb.RemoteFile(k, 1, "0" * 32, f"http://x/{k}")
        for k in ("README.md", "sol_orders_202512.tar.xz", "trades_2025_12.tar")
    }
    (tmp_path / "sol_orders_202512.tar.xz").write_bytes(b"x")
    (tmp_path / "sol_orders_202512.tar.xz.md5ok").write_text("0" * 32)
    alb.write_manifest(tmp_path, index, ["README.md", "sol_orders_202512.tar.xz"])
    alb.write_manifest(tmp_path, index, ["README.md", "trades_2025_12.tar"])
    rows = json.loads((tmp_path / "MANIFEST.json").read_text())["files"]
    assert [r["key"] for r in rows] == [
        "README.md",
        "sol_orders_202512.tar.xz",
        "trades_2025_12.tar",
    ]
    assert [r["verified"] for r in rows] == [False, True, False]
    assert "trades_2025_12.tar" in alb.SETS["trades"]
