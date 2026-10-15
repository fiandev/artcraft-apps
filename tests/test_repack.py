from coprsync.repack import generate_spec
from coprsync.rpmmeta import RpmMeta

META = RpmMeta(
    name="photocraft",
    epoch="",
    version="0.9.0",
    release="1",
    license="MIT OR Apache-2.0",
    summary="Open-source image editor",
    description="Line one.\nLine two with 100% coverage.",
    vendor="Learning Machines LLC",
    url="https://getartcraft.com/apps/photocraft",
    group="",
    arch="x86_64",
    requires=("libX11.so.6()(64bit)", "libvulkan.so.1()(64bit)"),
    files=("/usr/bin/photocraft", "/usr/share/applications/photocraft.desktop"),
)


def test_spec_carries_upstream_identity():
    spec = generate_spec(META, "photocraft-0.9.0-linux-x86_64.rpm")
    assert "Name:           photocraft" in spec
    assert "Version:        0.9.0" in spec
    assert "Release:        1" in spec
    assert "License:        MIT OR Apache-2.0" in spec
    assert "Vendor:         Learning Machines LLC" in spec
    assert "URL:            https://getartcraft.com/apps/photocraft" in spec
    assert "Source0:        photocraft-0.9.0-linux-x86_64.rpm" in spec
    assert "Epoch:" not in spec
    assert "Group:" not in spec


def test_spec_keeps_upstream_runtime_deps_verbatim():
    spec = generate_spec(META, "x.rpm")
    assert "Requires:       libX11.so.6()(64bit)" in spec
    assert "Requires:       libvulkan.so.1()(64bit)" in spec


def test_spec_repackages_without_compiling():
    spec = generate_spec(META, "x.rpm")
    assert "%global __os_install_post %{nil}" in spec
    assert "AutoReqProv:    no" in spec
    assert "rpm2cpio %{SOURCE0} | cpio -idmu --quiet" in spec
    assert "cp -a %{_builddir}/payload/. %{buildroot}/" in spec
    assert "%files\n/usr/bin/photocraft\n/usr/share/applications/photocraft.desktop\n" in spec


def test_spec_escapes_percent_in_free_text():
    spec = generate_spec(META, "x.rpm")
    assert "Line two with 100%% coverage." in spec


def test_epoch_line_only_when_present():
    spec = generate_spec(RpmMeta(**{**META.__dict__, "epoch": "2"}), "x.rpm")
    assert "Epoch:          2" in spec
