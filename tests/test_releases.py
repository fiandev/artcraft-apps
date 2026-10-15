from coprsync.releases import RpmAsset, asset_arch, is_publishable, new_releases, release_tag, rpm_assets


def release(tag, *, draft=False, prerelease=False, assets=()):
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "assets": [
            {"name": name, "url": f"https://api.example/{name}", "size": 10} for name in assets
        ],
    }


def test_asset_arch():
    assert asset_arch("photocraft-0.9.0-linux-x86_64.rpm") == "x86_64"
    assert asset_arch("photocraft-0.9.0-linux-aarch64.rpm") == "aarch64"
    assert asset_arch("photocraft-0.9.0-macos-universal.dmg") is None
    assert asset_arch("photocraft-web-0.9.0.zip") is None


def test_rpm_assets_filters_and_orders():
    payload = release(
        "v1",
        assets=["x-1-windows-x64.msi", "x-1-linux-aarch64.rpm", "SHA256SUMS.txt", "x-1-linux-x86_64.rpm"],
    )
    assets = rpm_assets(payload)
    assert assets == (
        RpmAsset("x-1-linux-aarch64.rpm", "aarch64", "https://api.example/x-1-linux-aarch64.rpm", 10),
        RpmAsset("x-1-linux-x86_64.rpm", "x86_64", "https://api.example/x-1-linux-x86_64.rpm", 10),
    )


def test_publishable_flags():
    assert is_publishable(release("v1"), include_prereleases=False)
    assert not is_publishable(release("v1", draft=True), include_prereleases=False)
    assert not is_publishable(release("v1", prerelease=True), include_prereleases=False)
    assert is_publishable(release("v1", prerelease=True), include_prereleases=True)
    assert not is_publishable(release(""), include_prereleases=True)


def test_release_tag_strips_whitespace():
    assert release_tag({"tag_name": "  v0.9.0 "}) == "v0.9.0"
    assert release_tag({}) == ""


def test_window_includes_boundary_so_partial_releases_retry():
    releases = [release("v3"), release("v2"), release("v1")]
    window = new_releases(releases, "v2", include_prereleases=False)
    assert [release_tag(r) for r in window] == ["v3", "v2"]


def test_window_is_empty_when_already_at_head():
    releases = [release("v2"), release("v1")]
    assert [release_tag(r) for r in new_releases(releases, "v2", include_prereleases=False)] == ["v2"]


def test_window_when_boundary_aged_out_of_the_fetch():
    releases = [release("v9"), release("v8")]
    assert len(new_releases(releases, "v1", include_prereleases=False)) == 2


def test_first_run_defaults_to_latest_only():
    releases = [release("v3"), release("v2"), release("v1")]
    latest = new_releases(releases, None, include_prereleases=False)
    assert [release_tag(r) for r in latest] == ["v3"]
    every = new_releases(releases, None, include_prereleases=False, initial="all")
    assert [release_tag(r) for r in every] == ["v3", "v2", "v1"]


def test_window_skips_prereleases():
    releases = [release("v3", prerelease=True), release("v2"), release("v1")]
    window = new_releases(releases, "v2", include_prereleases=False)
    assert [release_tag(r) for r in window] == ["v2"]
