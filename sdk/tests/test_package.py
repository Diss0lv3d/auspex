"""Connector packages and their content hash (S32, task 3, D-064)."""

import hashlib
import io
import json
import stat
import zipfile

import pytest
from auspex_sdk import package as pk
from auspex_sdk.manifest import manifest_to_json, parse_manifest
from auspex_sdk.package import PackageError, build_zip, read_package, tree_hash
from test_manifest import reference


def good_files() -> dict[str, bytes]:
    return {
        "manifest.json": manifest_to_json(parse_manifest(reference())),
        "pkg/__init__.py": b"",
        "pkg/handlers.py": b"def dry(): ...\n",
    }


def raw_zip(members: list[tuple[zipfile.ZipInfo | str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in members:
            z.writestr(info, data)
    return buf.getvalue()


def test_the_hash_ignores_zip_bytes():
    files = good_files()
    a = raw_zip([(zipfile.ZipInfo(n, (2001, 2, 3, 4, 5, 6)), d) for n, d in files.items()])
    b = raw_zip(
        [(zipfile.ZipInfo(n, (2020, 1, 1, 0, 0, 0)), d) for n, d in reversed(list(files.items()))]
    )
    assert a != b
    assert read_package(a)[1] == read_package(b)[1] == tree_hash(files)


def test_the_hash_has_the_documented_shape():
    files = {"b.py": b"2", "a.py": b"1"}
    lines = b"".join(
        p.encode() + b"\0" + hashlib.sha256(files[p]).hexdigest().encode() + b"\n"
        for p in ("a.py", "b.py")
    )
    assert tree_hash(files) == "sha256:" + hashlib.sha256(lines).hexdigest()


def test_any_file_change_changes_the_hash():
    files = good_files()
    base = tree_hash(files)
    assert tree_hash({**files, "pkg/handlers.py": b"x"}) != base
    assert tree_hash({**files, "pkg/new.py": b""}) != base
    renamed = {("pkg/other.py" if k == "pkg/handlers.py" else k): v for k, v in files.items()}
    assert tree_hash(renamed) != base


def test_build_zip_is_deterministic():
    files = good_files()
    assert build_zip(files) == build_zip(dict(reversed(list(files.items()))))
    with zipfile.ZipFile(io.BytesIO(build_zip(files))) as z:
        assert [i.filename for i in z.infolist()] == sorted(files)
        assert {i.date_time for i in z.infolist()} == {(1980, 1, 1, 0, 0, 0)}
    manifest, digest, got = read_package(build_zip(files))
    assert manifest.id == "ibm.qradar" and digest == tree_hash(files) and got == files


def link_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    return info


@pytest.mark.parametrize(
    "member",
    [
        "../x.py",
        "/abs.py",
        "pkg/../x.py",
        "pkg\\x.py",
        "C:/x.py",
        "pkg//x.py",
        "pkg/__pycache__/x.pyc",
        "pkg/x.pyc",
        "pkg/.hidden",
        ".env",
        "connector.yaml",
        "pkg/other.yml",
        "tests/test_a.py",
        "pkg/test/a.py",
        "pkg/test_a.py",
    ],
)
def test_bad_members_are_refused_by_name(member):
    data = raw_zip([("manifest.json", good_files()["manifest.json"]), (member, b"x")])
    with pytest.raises(PackageError) as e:
        read_package(data)
    assert e.value.member == member


def test_a_nul_in_a_path_is_refused():
    # zipfile itself truncates names at a NUL, so the rule is exercised on the checker
    with pytest.raises(PackageError):
        pk._check_path("pkg/x\0.py")


def test_symlinks_are_refused():
    data = raw_zip(
        [("manifest.json", good_files()["manifest.json"]), (link_info("pkg/l"), b"/etc")]
    )
    with pytest.raises(PackageError) as e:
        read_package(data)
    assert e.value.member == "pkg/l"


@pytest.mark.filterwarnings("ignore:Duplicate name")
def test_duplicates_are_refused_even_behind_a_dot_prefix():
    m = good_files()["manifest.json"]
    for second in ("pkg/a.py", "./pkg/a.py"):
        data = raw_zip([("manifest.json", m), ("pkg/a.py", b"1"), (second, b"2")])
        with pytest.raises(PackageError, match="duplicate") as e:
            read_package(data)
        assert e.value.member in ("pkg/a.py", "./pkg/a.py")


def test_directory_entries_are_skipped_and_a_directory_with_data_is_refused():
    m = good_files()["manifest.json"]
    ok = raw_zip([("manifest.json", m), ("pkg/", b""), ("pkg/a.py", b"1")])
    assert sorted(read_package(ok)[2]) == ["manifest.json", "pkg/a.py"]
    with pytest.raises(PackageError) as e:
        read_package(raw_zip([("manifest.json", m), ("pkg/", b"data")]))
    assert e.value.member == "pkg/"


def test_caps_are_enforced(monkeypatch):
    m = good_files()["manifest.json"]
    with pytest.raises(PackageError, match="bytes"):
        read_package(b"\0" * (pk.MAX_PACKAGE_BYTES + 1))
    many = raw_zip([("manifest.json", m)] + [(f"pkg/f{i}.py", b"") for i in range(pk.MAX_FILES)])
    with pytest.raises(PackageError, match="files"):
        read_package(many)
    big_manifest = raw_zip([("manifest.json", b" " * (pk.MAX_MANIFEST_BYTES + 1))])
    with pytest.raises(PackageError) as e:
        read_package(big_manifest)
    assert e.value.member == "manifest.json"
    # total size is checked from the declared sizes, before anything inflates
    monkeypatch.setattr(pk, "MAX_PACKAGE_BYTES", 10_000)
    bomb = raw_zip([("manifest.json", m), ("pkg/a.py", b"\0" * 20_000)])
    assert len(bomb) < 10_000
    with pytest.raises(PackageError, match="more than"):
        read_package(bomb)


def test_a_lying_declared_size_is_refused(monkeypatch):
    m = good_files()["manifest.json"]
    data = bytearray(raw_zip([("manifest.json", m), ("pkg/a.py", b"A" * 5000)]))
    # shrink the declared uncompressed size in both headers
    needle = (5000).to_bytes(4, "little")
    small = (10).to_bytes(4, "little")
    i = 0
    while (i := data.find(needle, i)) != -1:
        data[i : i + 4] = small
        i += 4
    with pytest.raises(PackageError) as e:
        read_package(bytes(data))
    assert e.value.member == "pkg/a.py"


def test_a_missing_or_invalid_manifest_is_refused():
    with pytest.raises(PackageError, match="manifest.json") as e:
        read_package(raw_zip([("pkg/a.py", b"1")]))
    assert e.value.member == "manifest.json"
    with pytest.raises(PackageError, match="manifest.json"):
        read_package(raw_zip([("pkg/manifest.json", b"{}")]))
    with pytest.raises(PackageError, match="JSON"):
        read_package(raw_zip([("manifest.json", b"{nope")]))
    with pytest.raises(PackageError, match="JSON"):
        read_package(raw_zip([("manifest.json", b"\xff\xfe")]))
    with pytest.raises(PackageError, match="JSON object"):
        read_package(raw_zip([("manifest.json", b"[]")]))
    bad = reference()
    bad["schema_version"] = 2
    with pytest.raises(PackageError, match="schema_version") as e:
        read_package(raw_zip([("manifest.json", json.dumps(bad).encode())]))
    assert e.value.__cause__ is not None


def test_a_stray_value_error_from_parsing_is_a_package_error():
    bad = reference()
    bad["config"][0] = {"name": "base_url", "label": "U", "type": "url", "default": "https://[x/"}
    with pytest.raises(PackageError):
        read_package(raw_zip([("manifest.json", json.dumps(bad).encode())]))


def test_garbage_is_a_package_error():
    with pytest.raises(PackageError, match="zip"):
        read_package(b"not a zip at all")
