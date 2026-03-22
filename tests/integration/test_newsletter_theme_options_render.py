from pathlib import Path


def test_theme_option_mockups_exist_and_use_html_constraints() -> None:
    mockup_dir = Path("docs/theme-mockups")
    index_html = (mockup_dir / "index.html").read_text(encoding="utf-8")

    expected_files = [
        "option-a-financial-briefing.html",
        "option-b-terminal-executive.html",
        "option-c-magazine-ledger.html",
        "option-d-research-memo.html",
        "option-e-market-tape.html",
    ]

    assert "Newsletter Theme Directions" in index_html
    assert "email-safe font stacks" in index_html

    for filename in expected_files:
        html = (mockup_dir / filename).read_text(encoding="utf-8")
        assert f'href="./{filename}"' in index_html
        assert '<meta name="viewport" content="width=device-width,initial-scale=1"' in html
        assert '<meta name="color-scheme" content="light dark"' in html
        assert '<link rel="stylesheet" href="./theme-preview.css"' in html
        assert 'class="email-frame"' in html
        assert 'class="story-title"' in html
        assert "story-time" in html

    stylesheet = (mockup_dir / "theme-preview.css").read_text(encoding="utf-8")
    assert "overflow-wrap: anywhere;" in stylesheet
    assert "max-width: 22ch;" in stylesheet
    assert "@media (max-width: 680px)" in stylesheet
    assert "@media (prefers-color-scheme: dark)" in stylesheet
