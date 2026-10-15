import pytest

from coprsync.coprclient import _load_client, read_credentials
from coprsync.errors import CoprError

INI = """
[copr-cli]
login = Y57wcg==##fkfaxbkjhuoiebfafadl
username = fiandev
token = vbfseelqdebzedukgombekmuvbkqwo
copr_url = https://copr.fedorainfracloud.org
# expiration date: 2027-04-13
"""

YAML_NESTED = """
copr-cli:
  login: Y57wcg==##fkfaxbkjhuoiebfafadl
  username: fiandev
  token: vbfseelqdebzedukgombekmuvbkqwo
  copr_url: https://copr.fedorainfracloud.org
"""

YAML_FLAT = """
username: fiandev
login: abc
token: def
copr_url: https://copr.fedorainfracloud.org
"""

JSON_BLOB = '{"copr-cli": {"username": "fiandev", "login": "abc", "token": "def"}}'


@pytest.mark.parametrize("text", [INI, YAML_NESTED, YAML_FLAT, JSON_BLOB])
def test_both_shapes_are_accepted(tmp_path, text):
    path = tmp_path / "copr"
    path.write_text(text)
    creds = read_credentials(path)
    assert creds["username"] == "fiandev"
    assert creds["login"]
    assert creds["token"]


def test_ini_percent_in_token_is_not_interpolated(tmp_path):
    """RawConfigParser matters: tokens regularly contain '%'."""
    path = tmp_path / "copr"
    path.write_text(
        "[copr-cli]\nusername = u\nlogin = a%b%%c\ntoken = t%20x\n"
    )
    assert read_credentials(path)["login"] == "a%b%%c"


def test_yaml_keys_are_case_insensitive(tmp_path):
    path = tmp_path / "copr"
    path.write_text(
        "copr-cli:\n  USERNAME: u\n  Login: l\n  Token: t\n  Copr_URL: https://x\n"
    )
    creds = read_credentials(path)
    assert creds["username"] == "u"
    assert creds["copr_url"] == "https://x"


@pytest.mark.parametrize(
    "text",
    ["", "just some prose\n", "[other]\nusername = u\n", "[copr-cli]\nusername = u\n"],
)
def test_unusable_files_report_clearly(tmp_path, text):
    path = tmp_path / "copr"
    path.write_text(text)
    with pytest.raises(CoprError):
        read_credentials(path)


def test_partial_credentials_name_the_missing_key(tmp_path):
    path = tmp_path / "copr"
    path.write_text("copr-cli:\n  username: u\n  login: l\n")
    with pytest.raises(CoprError, match="missing: token"):
        read_credentials(path)


def test_config_url_wins_over_the_secret_and_warns(tmp_path, monkeypatch, caplog):
    path = tmp_path / "copr"
    path.write_text(YAML_NESTED)
    monkeypatch.setenv("COPR_CONFIG_FILE", str(path))

    with caplog.at_level("WARNING", logger="coprsync"):
        client = _load_client("https://copr.example.internal")

    assert client.config["copr_url"] == "https://copr.example.internal"
    assert "https://copr.fedorainfracloud.org" in caplog.text


def test_no_warning_when_urls_agree(tmp_path, monkeypatch, caplog):
    path = tmp_path / "copr"
    path.write_text(INI)
    monkeypatch.setenv("COPR_CONFIG_FILE", str(path))

    with caplog.at_level("WARNING", logger="coprsync"):
        _load_client("https://copr.fedorainfracloud.org")

    assert caplog.text == ""


def test_missing_file_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv("COPR_CONFIG_FILE", str(tmp_path / "absent"))
    with pytest.raises(CoprError, match="no Copr credentials"):
        _load_client("https://copr.fedorainfracloud.org")
