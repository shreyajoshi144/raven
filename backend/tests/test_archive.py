import io
import tarfile

import pytest

from app.analysis.archive import Limits, read_archive
from app.core.errors import JobError
from tests.fixtures.sample_repo import FAKE_AWS_KEY, SAMPLE_FILES, make_tarball


def chunks(data: bytes, n: int = 4096):
    for i in range(0, len(data), n):
        yield data[i:i + n]


def run(files, **lim):
    return read_archive(chunks(make_tarball(files)), Limits(**lim))


def test_sample_repo_inventory():
    res = run(SAMPLE_FILES)
    by = {e.path: e for e in res.entries}
    assert by["app/main.py"].status == "analyzed" and by["app/main.py"].content
    assert by["node_modules/leftpad/index.js"].excluded_reason == "dependency_dir"
    assert by["build/out.py"].excluded_reason == "build_artifact"
    assert by["vendor/lib.py"].excluded_reason == "vendor"
    assert by[".env"].excluded_reason == "secret_file" and by[".env"].content is None
    assert by["logo.png"].excluded_reason == "binary"
    assert by["app/generated_pb2.py"].excluded_reason == "generated"
    assert FAKE_AWS_KEY not in (by["app/services/user_service.py"].content or "")
    assert by["app/services/user_service.py"].has_secret_like
    # .env.example keeps names only, never values
    tpl = by[".env.example"].content
    assert "DATABASE_URL=" in tpl and "supersecretpassword" not in tpl and "change-me" not in tpl
    assert not res.partial


def test_file_count_limit_marks_partial():
    files = {f"m{i}.py": "x = 1\n" for i in range(30)}
    res = run(files, max_files=10)
    assert res.partial and len(res.entries) == 10
    assert any("File limit" in r for r in res.partial_reasons)


def test_per_file_and_total_size_limits():
    files = {"big.py": "x = 1\n" * 1000, "a.py": "a=1\n" * 100, "b.py": "b=1\n" * 100}
    res = run(files, max_file_bytes=1000, max_total_bytes=500)
    st = {e.path: e for e in res.entries}
    assert st["big.py"].excluded_reason == "too_large"
    assert st["a.py"].status == "analyzed"
    assert st["b.py"].excluded_reason == "total_size_limit" and res.partial


def test_python_file_count_limit():
    res = run({f"m{i}.py": "x=1\n" for i in range(5)}, max_python_files=2)
    assert sum(1 for e in res.entries if e.status == "analyzed") == 2 and res.partial


def test_symlink_hardlink_and_traversal_skipped():
    sym = tarfile.TarInfo("owner-r-abc/link.py"); sym.type = tarfile.SYMTYPE; sym.linkname = "/etc/passwd"
    hard = tarfile.TarInfo("owner-r-abc/hard.py"); hard.type = tarfile.LNKTYPE; hard.linkname = "app.py"
    res = read_archive(chunks(make_tarball({"ok.py": "x=1\n", "../evil.py": "y=2\n", "a/../../b.py": "z=3\n"}, prefix="owner-r-abc", extra=[sym, hard])), Limits())
    paths = [e.path for e in res.entries]
    assert paths == ["ok.py"]
    assert res.stats.excluded.get("unsafe_path") == 2


def test_compressed_size_cap_truncates_without_crash():
    import os
    files = {f"f{i}.py": os.urandom(2000).hex() for i in range(200)}
    res = read_archive(chunks(make_tarball(files)), Limits(max_archive_bytes=20_000))
    assert res.partial and any("Archive exceeded" in r for r in res.partial_reasons)
    assert 0 < len(res.entries) < 200


def test_decompression_bomb_rejected():
    bomb = io.BytesIO()
    with tarfile.open(fileobj=bomb, mode="w:gz") as tar:
        data = b"\x00" * (30 * 1024 * 1024)
        info = tarfile.TarInfo("o-r-1/huge.bin"); info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    raw = bomb.getvalue()
    assert len(raw) < 100_000  # highly compressible
    with pytest.raises(JobError) as e:
        read_archive(chunks(raw), Limits(max_uncompressed_bytes=5 * 1024 * 1024))
    assert e.value.code == "ARCHIVE_INVALID"


def test_garbage_and_corrupt_archives():
    with pytest.raises(JobError) as e:
        read_archive(chunks(b"this is not a gzip"), Limits())
    assert e.value.code == "ARCHIVE_INVALID"
    good = make_tarball({"a.py": "x=1\n" * 50})
    with pytest.raises(JobError):
        read_archive(chunks(good[: len(good) // 2] + b"\x00garbage"), Limits())


def test_deadline_enforced():
    import time
    with pytest.raises(JobError) as e:
        read_archive(chunks(make_tarball({"a.py": "x=1\n"})), Limits(), deadline=time.monotonic() - 1)
    assert e.value.code == "ANALYSIS_TIMEOUT"


def test_binary_python_file_and_bad_encoding_excluded():
    res = run({"nul.py": b"x = 1\x00\n", "latin.py": b"x = '\xe9'\n"})
    assert all(e.status == "excluded" and e.excluded_reason == "binary" for e in res.entries)
