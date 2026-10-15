from coprsync.state import State


def load(tmp_path):
    return State(tmp_path / "state.json")


def test_recording_advances_the_boundary(tmp_path):
    state = load(tmp_path)
    assert state.last_tag("photocraft") is None

    state.record("photocraft", "v1", "a.rpm", ["fedora-rawhide-x86_64"], 11)
    assert state.last_tag("photocraft") == "v1"
    assert state.is_published("photocraft", "v1", "a.rpm")
    assert not state.is_published("photocraft", "v1", "b.rpm")


def test_other_repos_are_independent(tmp_path):
    state = load(tmp_path)
    state.record("a", "v1", "a.rpm", [], 1)
    state.record("b", "v9", "b.rpm", [], 2)
    assert state.last_tag("a") == "v1"
    assert state.last_tag("b") == "v9"


def test_advancing_drops_older_records(tmp_path):
    state = load(tmp_path)
    state.record("photocraft", "v1", "a.rpm", [], 1)
    state.record("photocraft", "v2", "b.rpm", [], 2)
    assert state.last_tag("photocraft") == "v2"
    assert not state.is_published("photocraft", "v1", "a.rpm")
    assert state.is_published("photocraft", "v2", "b.rpm")


def test_partial_release_resumes(tmp_path):
    path = tmp_path / "state.json"
    state = State(path)
    state.record("photocraft", "v2", "x86.rpm", [], 1)
    state.save()

    resumed = State(path)
    assert resumed.is_published("photocraft", "v2", "x86.rpm")
    assert not resumed.is_published("photocraft", "v2", "aarch64.rpm")


def test_advance_without_assets_keeps_boundary(tmp_path):
    state = load(tmp_path)
    state.advance("photocraft", "v5")
    assert state.last_tag("photocraft") == "v5"
    assert not state.is_published("photocraft", "v5", "anything.rpm")


def test_save_is_sorted_and_stable(tmp_path):
    path = tmp_path / "state.json"
    state = State(path)
    state.record("b", "v1", "b.rpm", [], 1)
    state.record("a", "v1", "a.rpm", [], 1)
    state.save()
    text = path.read_text()
    assert text.index('"a"') < text.index('"b"')
    assert text.endswith("\n")
