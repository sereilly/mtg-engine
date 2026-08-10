"""The manual-verification tracker's read side.

Joins the recorded results against the catalog and the behavioural-peer map to
produce the listing the Debug Menu shows, and regenerates
``CARD_VERIFICATION.md`` from it. ``equivalent`` is derived on read, never
stored, so it cannot be mistaken for a human check.
"""

from __future__ import annotations

from engine.behaviour_signature import equivalent_peer

from .runtime import (
    BEHAVIOUR_PEERS,
    CATALOG_CARD_NAMES,
    VERIFICATION_MD_PATH,
    verification_store,
)


def _verification_listing() -> tuple[list[dict], dict[str, int]]:
    """Merge recorded results with the full catalog so every card is represented.

    An untested card whose behaviour class already contains a passing card is
    reported as ``equivalent`` rather than ``untested``: the engine resolves it
    through the same code paths, so a separate manual pass would exercise
    nothing new (see engine/behaviour_signature.py).

    This status is *derived*, never stored — ``card_verification.json`` holds
    only what a human recorded. That keeps the two claims distinguishable, and
    means the derivation follows its peer: if the peer is later marked failing,
    everything resting on it stops counting as covered on the next read.
    """
    results = verification_store.results()
    verified = {name for name, entry in results.items() if entry.get("status") == "pass"}
    cards: list[dict] = []
    counts = {"pass": 0, "fail": 0, "untested": 0, "equivalent": 0}
    for name in CATALOG_CARD_NAMES:
        entry = results.get(name)
        status = entry["status"] if entry else "untested"
        peer = None
        if status == "untested":
            peer = equivalent_peer(name, BEHAVIOUR_PEERS, verified)
            if peer is not None:
                status = "equivalent"
        counts[status] = counts.get(status, 0) + 1
        cards.append(
            {
                "card_name": name,
                "status": status,
                "reason": entry.get("reason", "") if entry else "",
                "updated_at": entry.get("updated_at") if entry else None,
                "equivalent_to": peer,
            }
        )
    return cards, counts


def _write_verification_markdown() -> None:
    """Regenerate the human-readable master tracking document."""
    cards, counts = _verification_listing()
    lines = [
        "# Card Verification Tracker",
        "",
        "Master record of which cards have been manually validated in-game. "
        "Generated automatically — edit results via the in-game Debug Menu.",
        "",
        f"- Total cards: **{len(cards)}**",
        f"- Passed: **{counts['pass']}**",
        f"- Failed: **{counts['fail']}**",
        f"- Equivalent to a passing card: **{counts['equivalent']}**",
        f"- Untested: **{counts['untested']}**",
        "",
        "`equivalent` is derived, never recorded: the engine resolves that card "
        "through the same code paths as the named peer, so a separate manual pass "
        "would exercise nothing new. It is a weaker claim than a check — it "
        "inherits the peer's correctness. See BEHAVIOUR_CLASSES.md.",
        "",
        "| Card | Status | Failure reason / equivalent to |",
        "| --- | --- | --- |",
    ]
    badge = {
        "pass": "✅ pass",
        "fail": "❌ fail",
        "untested": "⬜ untested",
        "equivalent": "≡ equivalent",
    }
    for card in cards:
        note = (card["reason"] or "").replace("|", "\\|").replace("\n", " ")
        if card["status"] == "equivalent":
            note = f"same behaviour as {card['equivalent_to']}"
        lines.append(f"| {card['card_name']} | {badge[card['status']]} | {note} |")
    VERIFICATION_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
