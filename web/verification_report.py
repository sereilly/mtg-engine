"""The manual-verification tracker's read side.

Joins the recorded results against the catalog, the behavioural-peer map and
the simple-card table to produce the listing the Debug Menu shows, and
regenerates ``CARD_VERIFICATION.md`` from it. Two statuses are derived on
read, never stored, so neither can be mistaken for a human check:
``equivalent`` (a passing peer runs the same code) and the auto-pass (the card
has no abilities, or only keywords — there is nothing card-specific to check).
"""

from __future__ import annotations

from engine.behaviour_signature import equivalent_peer

from .runtime import (
    AUTO_PASSES,
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

    An untested *simple* card — no abilities at all, or nothing but keywords
    the engine implements (``engine.oracle.simple_card_keywords``) — is
    reported as ``pass`` with ``auto_pass`` naming why: its behaviour is the
    generic combat and keyword code plus its printed numbers, so there is no
    card-specific path for a manual check to exercise. It counts as a pass
    because that is what the tracker is for — deciding which cards still need
    a human — and these never did; ``counts["auto_pass"]`` keeps the number
    of them visible beside the checked ones.

    Both statuses are *derived*, never stored — ``card_verification.json``
    holds only what a human recorded. That keeps the claims distinguishable,
    and means each derivation follows what it rests on: if a peer is later
    marked failing, everything resting on it stops counting as covered on the
    next read, and a recorded result on a simple card (a printed number the
    data got wrong, say) always wins over the auto-pass. Only recorded passes
    seed equivalence: an auto-pass is weaker than a check, and equivalence
    propagates checks rather than creating them.
    """
    results = verification_store.results()
    verified = {name for name, entry in results.items() if entry.get("status") == "pass"}
    cards: list[dict] = []
    counts = {"pass": 0, "fail": 0, "untested": 0, "equivalent": 0, "auto_pass": 0}
    for name in CATALOG_CARD_NAMES:
        entry = results.get(name)
        status = entry["status"] if entry else "untested"
        peer = None
        auto_pass = None
        if status == "untested" and name in AUTO_PASSES:
            status = "pass"
            auto_pass = _auto_pass_label(AUTO_PASSES[name])
            counts["auto_pass"] += 1
        elif status == "untested":
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
                "auto_pass": auto_pass,
            }
        )
    return cards, counts


def _auto_pass_label(keywords: tuple[str, ...]) -> str:
    """Why a simple card passed without a check, for the listing's note column."""
    if not keywords:
        return "no abilities"
    return f"keywords only ({', '.join(keywords)})"


def write_verification_markdown() -> None:
    """Regenerate the human-readable master tracking document.

    Called by the Debug Menu's save route on every recorded result, and by
    CI's tracker-freshness step, which regenerates the file headlessly and
    fails on a diff — the markdown is a projection of
    ``card_verification.json`` plus the behaviour-class derivation, and a
    stale projection reads as an answer.
    """
    cards, counts = _verification_listing()
    lines = [
        "# Card Verification Tracker",
        "",
        "Master record of which cards have been manually validated in-game. "
        "Generated automatically — edit results via the in-game Debug Menu.",
        "",
        f"- Total cards: **{len(cards)}**",
        f"- Passed: **{counts['pass']}** "
        f"({counts['pass'] - counts['auto_pass']} checked in-game, "
        f"{counts['auto_pass']} auto-passed)",
        f"- Failed: **{counts['fail']}**",
        f"- Equivalent to a passing card: **{counts['equivalent']}**",
        f"- Untested: **{counts['untested']}**",
        "",
        "An *auto-pass* is derived, never recorded: the card has no abilities, "
        "or nothing but keywords the engine implements, so its behaviour is the "
        "generic combat and keyword code plus its printed numbers, and there is "
        "no card-specific path for a manual check to exercise. The note names "
        "which. A result recorded in-game always takes precedence over it.",
        "",
        "`equivalent` is derived, never recorded: the engine resolves that card "
        "through the same code paths as the named peer, so a separate manual pass "
        "would exercise nothing new. It is a weaker claim than a check — it "
        "inherits the peer's correctness. See BEHAVIOUR_CLASSES.md.",
        "",
        "| Card | Status | Failure reason / equivalent to / auto-pass |",
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
        elif card["auto_pass"]:
            note = f"auto-pass: {card['auto_pass']}"
        lines.append(f"| {card['card_name']} | {badge[card['status']]} | {note} |")
    VERIFICATION_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
