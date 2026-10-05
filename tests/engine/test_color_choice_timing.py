"""Pool-wide: "the color of your choice" is asked when the effect is applied
(CR 608.2d), never read off the announcement.

CR 601.2b-c and CR 602.2b list what a spell or an ability announces as it goes
on the stack: modes, X, targets, the division, costs. A colour is none of those,
so CR 608.2d makes it a choice the player announces *while applying the
effect* - after every response has resolved. The engine read it off the
activation instead, on the wire field an any-colour mana ability uses: an
interactive seat was never asked, a client that sent no colour granted nothing,
and a player answering a Lightning Bolt with Mother of Runes had to name red
before the Bolt's controller could respond.

This drives every supported card printing such a choice on a spell or an
activated ability through the real entry points, **with a colour announced**,
and asks whether the resolution still stops to ask its controller. A handler
that reads the announcement answers without asking, which is exactly the shape
this fails on. Triggered abilities are out by construction: nothing announces a
trigger, so there is no announcement for one to read (Shyft asks already).

The floor is the population W2G5's census measured plus what this round's
census added; run on the tree before the fix, the guard named all eleven
(``_W3G2_ANNOUNCEMENT_READERS``).
"""

from __future__ import annotations

import re

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.mana_payment import is_mana_ability
from engine.models import Permanent
from engine.oracle import compile_card_oracle

#: Every printed spelling of a colour chosen while the effect is applied. "A
#: color of your choice" is not here: it is a *mana* choice (Harvest Mage), made
#: as a land is tapped, which is a mana ability's own resolution (CR 605.3b).
_W3G2_CHOICE = re.compile(
    r"the color(?: or colors)? of (?:your|its controller's) choice"
    r"|(?:^|[.:]\s*)choose a color\.",
    re.IGNORECASE,
)

#: The eleven lines that read the announcement on the tree this guard was
#: validated against (W2G5's seven, Dream Coat's plural spelling, and the three
#: "Choose a color." spells, whose choosing step read the cast's colour).
_W3G2_ANNOUNCEMENT_READERS = frozenset({
    "Alchor's Tomb", "Distorting Lens", "Dream Coat", "Feat of Resistance",
    "Jeweled Spirit", "Knight of Dawn", "Mother of Runes", "Persecute",
    "Prismatic Boon", "Rappelling Scouts", "Reverent Mantra",
})

_COLOUR_PROMPTS = ("color_choice", "color_set_choice")


def _w3g2_catalog():
    cards = {}
    for card in load_cards(manifest_set_paths(include_measured=True)):
        cards.setdefault(card.name, card)
    return cards


def _w3g2_population():
    """(card, line, ability index or None) for every announced colour choice."""
    examined = 0
    rows = []
    for card in _w3g2_catalog().values():
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        examined += 1
        is_spell = any(t in card.type_line for t in ("Instant", "Sorcery"))
        for line in (card.oracle_text or "").split("\n"):
            if not _W3G2_CHOICE.search(line):
                continue
            activated = [
                index for index, ability in enumerate(program.activated_abilities)
                if ability.source_line == line
            ]
            # A mana ability is out for the reason "a color of your choice" is
            # (see ``_W3G2_CHOICE``): it resolves the moment it is activated
            # (CR 605.3b), so the colour named with the activation *is* the
            # choice made while the effect is applied. "{T}: Choose a color.
            # Add one mana of that color unless any player pays {1}." (Rhystic
            # Cave) prints this guard's spelling on one. Asked of the engine's
            # own predicate rather than of the card's name.
            if activated and all(
                is_mana_ability(program.activated_abilities[index])
                for index in activated
            ):
                continue
            if activated:
                rows.append((card, line, activated[0]))
            elif is_spell:
                rows.append((card, line, None))
    return examined, rows


def _w3g2_table(catalog):
    game = Game(players=[PlayerState(name="A", life=20), PlayerState(name="B", life=20)])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    mine = Permanent(card=catalog["Grizzly Bears"])
    theirs = Permanent(card=catalog["Grizzly Bears"])
    fodder = [Permanent(card=catalog["Forest"]) for _ in range(2)]
    for perm in (mine, theirs, *fodder):
        perm.metadata["summoning_sick"] = False
    game.players[0].battlefield.extend([mine, *fodder])
    game.players[1].battlefield.append(theirs)
    return game, mine


def _w3g2_announce(game, card, ability_index, mine):
    """Put the line on the stack with red announced; the first legal shape."""
    if ability_index is None:
        game.players[0].hand.append(card)
        shapes = (
            {"target_player_index": 0, "target_permanent_ids": [mine.permanent_id]},
            {"target_player_index": 1},
            {},
        )
        for shape in shapes:
            if game.queue_from_hand(0, card.name, x_value=1, new_color="R", **shape).supported:
                return True
        return False
    source = Permanent(card=card)
    source.metadata["summoning_sick"] = False
    game.players[0].battlefield.append(source)
    if "Aura" in card.type_line:
        attach_aura(source, mine)
    shapes = (
        {"target_player_index": 0, "target_permanent_ids": [mine.permanent_id]},
        {},
    )
    for shape in shapes:
        queued = game.queue_permanent_ability(
            0, card.name, ability_index=ability_index, mana_color="R", **shape
        )
        if queued.supported:
            return True
    return False


def _w3g2_asked(game) -> bool:
    """Resolve, answering a CR 608.2d "A or B" with its colour alternative, and
    report whether seat 0 was ever asked a colour."""
    for _ in range(10):
        owed = [choice for choice in game.pending_choices if choice.player_index == 0]
        if any(choice.kind in _COLOUR_PROMPTS for choice in owed):
            return True
        modes = [choice for choice in owed if choice.kind == "mode_choice"]
        if modes:
            labels = list(modes[0].data.get("labels") or ())
            pick = next(i for i, label in enumerate(labels) if "color" in label)
            assert game.resolve_pending_choice("mode_choice", 0, mode_index=pick)
            continue
        if not game.stack:
            return False
        game.resolve_top_of_stack()
    return False  # _w3g2_asked


def test_a_chosen_colour_is_asked_at_resolution_not_read_off_the_announcement():
    catalog = _w3g2_catalog()
    examined, rows = _w3g2_population()

    not_asked = []
    for card, line, ability_index in rows:
        game, mine = _w3g2_table(catalog)
        assert _w3g2_announce(game, card, ability_index, mine), (card.name, game.log[-3:])
        if not _w3g2_asked(game):
            not_asked.append(card.name)

    assert not not_asked, sorted(not_asked)
    # The floor: the census read the pool, and drove every card it was
    # validated on (plus the two that already asked, Prismatic Lace and
    # Wishmonger).
    assert examined >= 4000, examined
    driven = {card.name for card, _, _ in rows}
    assert _W3G2_ANNOUNCEMENT_READERS <= driven, sorted(_W3G2_ANNOUNCEMENT_READERS - driven)
    assert len(rows) >= 13, [card.name for card, _, _ in rows]


@pytest.mark.parametrize("name", sorted(_W3G2_ANNOUNCEMENT_READERS))
def test_the_announced_colour_does_not_recolour_the_object_on_the_stack(name):
    """The announcement's colour rode the key a Lace writes to recolour a spell,
    so every object announced with one *was* that colour on the stack: a white
    Feat of Resistance cast "for red" could be countered by Red Elemental Blast.
    Nothing announces a colour for these any more, and a caller that still
    sends one leaves the object its own colour."""
    catalog = _w3g2_catalog()
    card = catalog[name]
    _, rows = _w3g2_population()
    ability_index = next(index for c, _, index in rows if c.name == name)
    game, mine = _w3g2_table(catalog)
    assert _w3g2_announce(game, card, ability_index, mine)
    assert "R" not in game._stack_item_colors(game.stack[-1]) or "R" in card.colors


# --- INV W1G6: "of that color" inside a noun phrase -------------------------
# The other half of CR 608.2d: once the colour is chosen, the sentence behind
# the choice *spends* it — "for each permanent of that color" (Rith), "all
# creatures of that color" (Dromar). The filter key that carries the phrase was
# read by nobody, so three Invasion cards arrived supported and counted every
# permanent on the seat. It is resolved out of the resolution's scratchpad
# where a resolution is in hand, and refused everywhere else.


def test_an_unresolved_colour_of_this_resolution_matches_nothing():
    """Fail closed: a matcher holding no resolution answers False for the key,
    for a permanent and for a card alike — the direction that counts (or
    sweeps) nothing rather than the whole board."""
    from engine.handlers._common import (_card_matches_filter,
                                         permanent_matches_filter,
                                         resolve_color_chosen_in_resolution)

    catalog = _w3g2_catalog()
    bears = Permanent(card=catalog["Grizzly Bears"])
    for key in ("color_chosen_this_way", "color_of_your_choice"):
        assert not permanent_matches_filter(bears, {key: True}), key
        assert not _card_matches_filter(catalog["Grizzly Bears"], {key: True}), key

    class _Resolution:
        results = {"chosen_color_this_way": "G"}

    resolved = resolve_color_chosen_in_resolution(
        {"color_chosen_this_way": True, "type_filter": "creature"}, _Resolution(),
    )
    assert resolved == {"type_filter": "creature", "color_filter": "G"}
    assert permanent_matches_filter(bears, resolved)
    # Nothing chosen: the key stays, and the matcher goes on refusing.
    unanswered = resolve_color_chosen_in_resolution({"color_chosen_this_way": True}, object())
    assert unanswered == {"color_chosen_this_way": True}


def test_every_compiled_reader_of_that_colour_sits_behind_a_step_that_chose():
    """Census, both manifest roles: a payload carrying the phrase — as a count
    filter key or as the ``color_filter_from`` a sweep, a discard and a hand
    pick read — is in a sequence whose earlier step is ``choose_color``.
    Without one the reader has nothing to resolve and the card does nothing
    while reporting supported."""
    def _walk(node, chose, found):
        if hasattr(node, "kind") and hasattr(node, "payload"):
            reads = "color_filter_from" in node.payload or "color_chosen_this_way" in repr(
                {k: v for k, v in node.payload.items() if k not in ("steps", "then")}
            )
            if reads:
                found.append(chose)
            for key in ("steps", "then"):
                seen = chose
                for step in node.payload.get(key) or ():
                    _walk(step, seen, found)
                    seen = seen or getattr(step, "kind", "") == "choose_color"
        return found

    examined, readers, orphans = 0, [], []
    for card in _w3g2_catalog().values():
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        examined += 1
        found: list[bool] = []
        for instruction in program.instructions:
            _walk(instruction, False, found)
        if found:
            readers.append(card.name)
            if not all(found):
                orphans.append(card.name)

    assert not orphans, sorted(orphans)
    assert examined >= 4000, examined
    # Persecute (shipped) and Invasion's eight: the floor that says the walk
    # really reached the payloads it is about.
    assert {"Persecute", "Rith, the Awakener", "Wash Out", "Addle"} <= set(readers), sorted(readers)
