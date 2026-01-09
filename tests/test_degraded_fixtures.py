import json
from pathlib import Path

from apprscan.server import service


def _load_schema_required() -> set[str]:
    schema_path = Path("src/apprscan/schemas/company_package.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return set(schema.get("required", []))


def _load_fixture(name: str) -> dict:
    path = Path("tests/fixtures/company_package") / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_degraded_website_missing_fixture():
    required = _load_schema_required()
    package = _load_fixture("degraded.website_missing.json")
    assert required.issubset(package.keys())
    assert package["status"] == "degraded"
    assert package["degraded_reason"] == "website_missing"
    assert package["hiring"]["evidence"] == []
    assert package["next_action"]
    assert package["safety"]["cookie_wall"]["detected"] is False
    md = service.render_company_markdown(package)
    assert "Next action" in md


def test_degraded_cookie_wall_fixture():
    required = _load_schema_required()
    package = _load_fixture("degraded.cookie_wall.json")
    assert required.issubset(package.keys())
    assert package["status"] == "degraded"
    assert package["degraded_reason"] == "cookie_wall"
    assert package["hiring"]["evidence"] == []
    assert package["next_action"]
    assert package["safety"]["cookie_wall"]["detected"] is True
    assert package["safety"]["cookie_wall"]["signals"]
    md = service.render_company_markdown(package)
    assert "cookie wall" in md.lower()
