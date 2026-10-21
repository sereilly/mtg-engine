"""The revealed-hand dialog's "Choose no more" is shown only for an "up to" pick.

``renderRevealedHandPickModal`` hides ``#revealedHandPickFooter`` with the
``hidden`` class unless the prompt says ``up_to`` (Discordant Dirge), and
leaves the button with no handler otherwise. But ``.modal-footer`` sets
``display: flex`` *after* ``.hidden`` in ``styles.css``, with the same
specificity, so the class did nothing: found at Torment's Phase 5
(2026-10-21) on Mesmeric Fiend — "you choose a nonland card from it", the
payload's ``up_to`` false — the dialog offered "Choose no more", a button that
did nothing when clicked. A ``.modal-footer.hidden`` rule now hides it.

Read as text: what decides it is the cascade, which bare node cannot run.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "web" / "static"


def _rules(css: str):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        yield match.start(), [s.strip() for s in match.group(1).split(",")], match.group(2)


def _classes_of(html: str, element_id: str) -> list[str]:
    match = re.search(rf'<[a-z]+[^>]*\bid="{element_id}"[^>]*>', html)
    assert match, f"#{element_id} is gone from index.html"
    classes = re.search(r'class="([^"]*)"', match.group(0))
    return classes.group(1).split() if classes else []


def test_the_footer_starts_hidden_and_hidden_wins_over_its_display():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    classes = _classes_of(html, "revealedHandPickFooter")
    assert "hidden" in classes and "modal-footer" in classes

    rules = list(_rules(css))
    hidden_at = min(pos for pos, sels, _ in rules if ".hidden" in sels)
    overriding = [
        cls for cls in classes if cls != "hidden"
        and any(
            f".{cls}" in sels and re.search(r"display\s*:\s*(?!none)", body) and pos > hidden_at
            for pos, sels, body in rules
        )
    ]
    unhidden = [
        cls for cls in overriding
        if not any(
            f".{cls}.hidden" in sels and re.search(r"display\s*:\s*none", body)
            for _pos, sels, body in rules
        )
    ]
    assert overriding == ["modal-footer"], "the case this test exists for"
    assert unhidden == [], (
        f"{unhidden}: a display rule after .hidden keeps the footer on screen"
    )


def test_the_dialog_still_offers_the_way_out_for_an_up_to_pick():
    """The neighbour: the button is wired only where ``up_to`` is said."""
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    body = source[source.index("function renderRevealedHandPickModal("):]
    body = body[: body.index("\n}\n")]
    assert 'doneFooter.classList.toggle("hidden", !canStop)' in body
    assert "const canStop = Boolean(info.up_to);" in body
