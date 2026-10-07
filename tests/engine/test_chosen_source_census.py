"""Census: "a source of your choice" is a choice — offered, held and kept.

CR 609.7a: "If an effect requires a player to choose a source of damage, they
may choose a permanent; a spell on the stack …". CR 615.8: such an effect
prevents "the next instance of damage from **that source**". CR 615.9: where
the sentence gives the source a property ("a **red** source of your choice"),
the shield rechecks it when the damage would be dealt.

A chosen source is not a target (CR 115.1), and this engine got that fact
wrong in both directions at once, on the activation side:

* **the picker treated it as one.** ``_enumerate_targets`` ran the targeting
  gate over every candidate that was not a cost, so a source with shroud, an
  opponent's with hexproof and one with protection from the choosing card were
  left out. Every colour Circle is a white enchantment: Circle of Protection:
  Black could not be offered a Black Knight.
* **the gate did not look at all.** ``activation_target_refusal`` returned on
  ``also_stack`` before comparing anything, so a named source the picker does
  not offer was accepted — a Grizzly Bears as Circle of Protection: Red's "red
  source", a green spell, two sources at once.
* **and for the Circles the name was thrown away.** ``grant_prevention_shield``
  recorded the chosen source "only for the log; matching is by color", so the
  shield answered the next damage from *any* source of the colour — which is
  why nothing had noticed the first two.

The three statements below are made over every activated ability in the pool
whose spec says its picker is a chosen source (``source_of_choice`` or
``also_stack``), on a table that holds, for each colour and on each seat, a
plain creature and its shrouded, hexproof and protected twins.

Validated backwards on the tree before the change (its tallies are what
``parity_census`` / ``gate_census`` / ``binding_census`` return):

* statement 1 — a warded golem treated differently from its plain twin 390
  times in 1,400;
* statement 2, naming a wider sample than the one kept here (the plain golem
  of every colour on both seats, every shrouded one on seat 1, the artifact,
  the land and both spells) — 254 of 327 unoffered namings accepted, and 24
  of 24 pairs. That 254 counts a source the old picker withheld *wrongly*
  beside one that was no legal source at all; with the picker put right the
  same sample is 253 unoffered, none accepted;
* statement 3 — 13 of 19 bound abilities answered a source that was not the
  one chosen: the twelve that narrow by colour (five Circles, five Runes,
  Greater Realm of Preservation, Penance), and Nova Pentacle, whose handler
  read the choice off a channel its picker does not write.

Five abilities are outside statement 3 because the named golem's damage to
their controller is not reduced at all on this table (Kithkin Armor, Prismatic
Circle, Story Circle, Protective Sphere, Rhystic Circle). They are counted,
not diagnosed here.
"""

from __future__ import annotations

from functools import lru_cache

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec
from tests.helpers import _nosick, resolve_stack

_COLOURS = (("White", "W"), ("Blue", "U"), ("Black", "B"), ("Red", "R"), ("Green", "G"))

#: What a targeting gate would withhold and a choice must not: ``(label,
#: oracle text, keywords)``. ``keywords`` is what layer 6 reads a printed
#: keyword off; a protection is read off the text.
_WARDS = (
    ("Shroud", "Shroud", ("Shroud",)),
    ("Hexproof", "Hexproof", ("Hexproof",)),
    ("Pro White", "Protection from white", ()),
    ("Pro Artifacts", "Protection from artifacts", ()),
    ("Pro Creatures", "Protection from creatures", ()),
)

# 24 abilities on the day; the floors are what stop a filter from passing a
# sweep that examined nothing.
# Measured October 2026: 28 abilities; 1,400 twins compared; 71 unoffered and
# 105 offered namings in the sample, and 24 pairs; 19 abilities bound. Floors,
# not equalities — the pool grows — and what stops a later filter from passing
# a sweep that examined nothing.
_MIN_ABILITIES = 24
_MIN_TWINS_COMPARED = 1200
_MIN_UNOFFERED_NAMINGS = 60
_MIN_OFFERED_NAMINGS = 90
_MIN_PAIRS = 20
_MIN_BOUND = 16


def _golem(label: str, symbol: str, text: str = "", keywords: tuple = ()) -> CardDefinition:
    kind = "Creature — Golem"
    name = f"Census {label}"
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line=kind, oracle_text=text,
        colors=(symbol,), color_identity=(symbol,), keywords=keywords, produced_mana=(),
        raw={"name": name, "type_line": kind, "power": "2", "toughness": "2", "colors": [symbol]},
    )


#: ``{colour symbol: (plain, {ward label: card})}``.
_GOLEMS = {
    symbol: (
        _golem(f"{colour} Plain", symbol),
        {
            label: _golem(f"{colour} {label}", symbol, text, keywords)
            for label, text, keywords in _WARDS
        },
    )
    for colour, symbol in _COLOURS
}


@lru_cache(maxsize=1)
def _pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        cards.setdefault(card.name, card)
    return cards


@lru_cache(maxsize=1)
def _rows() -> tuple:
    """``(card, ability index)`` for every activated ability whose picker is a
    chosen source."""
    rows = []
    for card in sorted(_pool().values(), key=lambda entry: entry.name):
        if card.primary_type in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, ability in enumerate(program.activated_abilities):
            spec = derive_activation_spec(ability) or {}
            if spec.get("source_of_choice") or spec.get("also_stack"):
                rows.append((card, index))
    return tuple(rows)


def _table(card, *, stack: bool = True) -> tuple[Game, Permanent]:
    """Both seats hold every golem, an Ornithopter and a Forest; seat 0 holds
    *card*; seat 1 has a Lightning Bolt (at seat 0) and a Giant Growth on the
    stack — unless *stack* is False, for a naming that is not about a spell:
    the two casts are most of what a table costs, and they move no permanent,
    so a slot means the same thing on either table."""
    pool = _pool()

    def bait() -> list:
        # On the battlefield as the game is built rather than entered one at a
        # time: every golem is vanilla or a keyword, a table is built once per
        # naming, and thirty-two entries apiece were most of what a row cost.
        row = []
        for plain, warded in _GOLEMS.values():
            row.append(_nosick(Permanent(card=plain)))
            row.extend(_nosick(Permanent(card=definition)) for definition in warded.values())
        row.append(_nosick(Permanent(card=pool["Ornithopter"])))
        row.append(_nosick(Permanent(card=pool["Forest"])))
        return row

    game = Game(players=[
        PlayerState(
            "A", library=[pool["Forest"]] * 12, hand=[pool["Forest"]] * 2, battlefield=bait(),
        ),
        PlayerState(
            "B", library=[pool["Forest"]] * 12, battlefield=bait(),
            hand=[pool["Lightning Bolt"], pool["Giant Growth"]],
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    # *card* itself enters the ordinary way, so whatever it does as it enters
    # has happened.
    source = Permanent(card=card)
    game._put_permanent_onto_battlefield(0, source, None)
    _nosick(source)
    if "chosen_color" not in source.metadata:
        # "As this enters, choose a color" (Prismatic Circle, Story Circle).
        source.metadata["chosen_color"] = "R"
    if not stack:
        return game, source
    growth_target = next(p for p in game.controlled_by(1) if p.card.name == "Census Green Plain")
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.queue_from_hand(
        1, "Giant Growth", target_permanent_ids=[growth_target.permanent_id],
    ).supported
    return game, source


def _offered(game, source, ability_index) -> tuple[set, set]:
    """``(permanent slots, stack positions)`` the ability's picker offers: a
    slot is ``(seat, battlefield index)`` and a position counts from the
    bottom of the stack, so both mean the same thing on the next table built
    the same way — a ``permanent_id`` does not."""
    spec = game.activation_target_spec(0, game.battlefield_index_of(source), ability_index)
    permanents, spells = set(), set()
    depth = len(game.stack)
    for entry in spec.get("valid_targets") or ():
        if entry.get("kind") == "permanent":
            permanents.add((entry["seat"], entry["index"]))
        elif entry.get("kind") == "stack":
            spells.add(depth - 1 - entry["stack_index"])
    return permanents, spells


def _slot(game, permanent) -> tuple:
    return (game.controller_index_of(permanent), game.battlefield_index_of(permanent))


def _activate(game, source, card, ability_index, **named):
    return game.queue_permanent_ability(
        0, card.name, permanent_index=game.battlefield_index_of(source),
        ability_index=ability_index, x_value=1, **named,
    )


def test_the_golems_carry_what_their_names_say():
    """The fixture, asked — a sweep whose bait is not bait passes."""
    game, _source = _table(_pool()["Pentagram of the Ages"])
    by_name = {p.card.name: p for p in game.controlled_by(1)}
    for colour, symbol in _COLOURS:
        plain = by_name[f"Census {colour} Plain"]
        assert game._effective_colors(plain) == {symbol}
        assert game._has_keyword(by_name[f"Census {colour} Shroud"], "shroud")
        assert game._has_keyword(by_name[f"Census {colour} Hexproof"], "hexproof")
        assert ("color", "W") in game._protection_qualities(by_name[f"Census {colour} Pro White"])
        assert ("card_type", "artifact") in game._protection_qualities(
            by_name[f"Census {colour} Pro Artifacts"]
        )
        assert ("card_type", "creature") in game._protection_qualities(
            by_name[f"Census {colour} Pro Creatures"]
        )


def parity_census() -> dict:
    """Statement 1's tally: each warded golem against its plain twin of the
    same colour on the same seat."""
    compared = 0
    differs: list[str] = []
    for card, ability_index in _rows():
        game, source = _table(card)
        offered, _spells = _offered(game, source, ability_index)
        for seat in (0, 1):
            by_name = {p.card.name: p for p in game.controlled_by(seat)}
            for colour, _symbol in _COLOURS:
                plain = _slot(game, by_name[f"Census {colour} Plain"]) in offered
                for label, _text, _keywords in _WARDS:
                    compared += 1
                    twin = by_name[f"Census {colour} {label}"]
                    if (_slot(game, twin) in offered) is not plain:
                        differs.append(
                            f"{card.name}#{ability_index}: seat {seat}'s {twin.card.name} "
                            f"{'offered' if not plain else 'withheld'}"
                        )
    return {"compared": compared, "differs": differs}


def test_a_chosen_source_is_offered_whatever_wards_it():
    """Statement 1. Shroud, hexproof and protection stop a permanent being
    *targeted*; a source is chosen. So each warded golem is offered exactly
    when its plain twin of the same colour on the same seat is."""
    assert len(_rows()) >= _MIN_ABILITIES, len(_rows())
    tally = parity_census()
    assert tally["compared"] >= _MIN_TWINS_COMPARED, tally["compared"]
    assert not tally["differs"], (len(tally["differs"]), tally["differs"][:16])


def gate_census() -> dict:
    """Statement 2's tally. A sample of the table rather than all of it — a
    table is built per naming, and naming all sixty-six permanents cost the
    suite five minutes to say what seven of them say. Chosen **relative to the
    picker**, so every ability is named something it offers and (where it
    narrows at all) something it does not: of seat 1's plain golems the first
    it offers and the first it does not, the shrouded twin of the offered
    one, seat 1's Ornithopter and Forest, and the two spells on the stack."""
    unoffered = offered_count = pairs = 0
    accepted_illegal: list[str] = []
    refused_legal: list[str] = []
    doubled: list[str] = []
    for card, ability_index in _rows():
        probe, source = _table(card)
        permanents, spells = _offered(probe, source, ability_index)
        theirs = {p.card.name: p for p in probe.controlled_by(1)}
        plains = [p for name, p in theirs.items() if name.endswith(" Plain")]
        offered_plain = next((p for p in plains if _slot(probe, p) in permanents), None)
        unoffered_plain = next((p for p in plains if _slot(probe, p) not in permanents), None)
        sample = [offered_plain, unoffered_plain, theirs["Ornithopter"], theirs["Forest"]]
        if offered_plain is not None:
            colour = offered_plain.card.name.split()[1]
            sample.append(theirs[f"Census {colour} Shroud"])
        names = [("permanent", _slot(probe, p)) for p in sample if p is not None]
        names += [("stack", position) for position in range(len(probe.stack))]
        for kind, key in names:
            game, source = _table(card, stack=kind == "stack")
            if kind == "permanent":
                permanent = game.permanent_at(*key)
                named = {"target_permanent_ids": [permanent.permanent_id]}
                legal = key in permanents
                label = permanent.card.name
            else:
                named = {"target_stack_index": key}
                legal = key in spells
                label = game.stack[key].card.name
            depth = len(game.stack)
            result = _activate(game, source, card, ability_index, **named)
            where = f"{card.name}#{ability_index} naming {label}"
            if legal:
                offered_count += 1
                if not result.supported:
                    refused_legal.append(f"{where}: {result.details}")
                continue
            unoffered += 1
            if result.supported:
                accepted_illegal.append(where)
            elif len(game.stack) != depth or source.tapped:
                accepted_illegal.append(f"{where}: refused, and a cost was paid")

        game, source = _table(card, stack=False)
        pair = [p.permanent_id for p in game.controlled_by(1) if _slot(game, p) in permanents][:2]
        if len(pair) == 2:
            pairs += 1
            if _activate(game, source, card, ability_index, target_permanent_ids=pair).supported:
                doubled.append(f"{card.name}#{ability_index}")
    return {
        "unoffered": unoffered, "offered": offered_count, "pairs": pairs,
        "accepted_illegal": accepted_illegal, "refused_legal": refused_legal,
        "doubled": doubled,
    }


def test_no_activation_accepts_a_source_its_picker_does_not_offer():
    """Statement 2. Each sampled source is named in turn: accepted exactly
    when the picker offers it, and when it is refused nothing has been paid
    and nothing is on the stack. Two sources at once are refused — the
    sentence says "a source"."""
    tally = gate_census()
    assert tally["unoffered"] >= _MIN_UNOFFERED_NAMINGS, tally["unoffered"]
    assert tally["offered"] >= _MIN_OFFERED_NAMINGS, tally["offered"]
    assert tally["pairs"] >= _MIN_PAIRS, tally["pairs"]
    assert not tally["accepted_illegal"], (
        len(tally["accepted_illegal"]), tally["accepted_illegal"][:16],
    )
    assert not tally["refused_legal"], (len(tally["refused_legal"]), tally["refused_legal"][:16])
    assert not tally["doubled"], tally["doubled"]


def _life_lost_to(game, source_of_damage) -> int:
    before = game.players[0].life
    game._deal_damage_to_player(game.players[0], 2, source=source_of_damage)
    return before - game.players[0].life


def binding_census() -> dict:
    """Statement 3's tally. An ability is *bound* when the named golem's
    damage to its controller is reduced at all — the ones where it is not
    protect something other than their controller's face (Kithkin Armor's
    enchanted creature) and are outside the statement, counted as ``unbound``.
    """
    bound: list[str] = []
    unbound: list[str] = []
    findings: list[str] = []
    for card, ability_index in _rows():
        probe, source = _table(card)
        permanents, _spells = _offered(probe, source, ability_index)
        theirs = [
            p for p in probe.controlled_by(1)
            if _slot(probe, p) in permanents and p.card.name.endswith(" Plain")
        ]
        if not theirs:
            continue
        named_slot = _slot(probe, theirs[0])
        colour = theirs[0].card.name.split()[1]
        label = f"{card.name}#{ability_index}"

        def armed():
            game, source = _table(card)
            named = game.permanent_at(*named_slot)
            assert _activate(
                game, source, card, ability_index, target_permanent_ids=[named.permanent_id],
            ).supported, card.name
            # The ability alone: the Bolt and the Growth under it stay put.
            game.resolve_top_of_stack()
            other = next(
                p for p in game.controlled_by(1) if p.card.name == f"Census {colour} Shroud"
            )
            return game, named, other

        game, named, other = armed()
        if _life_lost_to(game, named) >= 2:
            unbound.append(label)
            continue
        bound.append(label)
        game, named, other = armed()
        if _life_lost_to(game, other) != 2:
            findings.append(
                f"{label}: named {named.card.name}, and answered {other.card.name}'s damage"
            )
        elif _life_lost_to(game, named) >= 2:
            findings.append(f"{label}: did not answer the source that was chosen")
    return {"bound": bound, "unbound": unbound, "findings": findings}


def test_a_shield_answers_the_source_that_was_chosen_and_no_other():
    """Statement 3 (CR 615.8). Seat 0 names one of seat 1's golems; a second
    golem of the same colour then deals 2 to seat 0 and all of it lands, and
    the named one deals 2 and less than all of it does."""
    tally = binding_census()
    assert len(tally["bound"]) >= _MIN_BOUND, (len(tally["bound"]), tally["unbound"])
    assert not tally["findings"], (len(tally["findings"]), tally["findings"])


# -- the cards ---------------------------------------------------------------


@pytest.fixture
def by_name(catalog_by_name):
    return catalog_by_name


def _duel(by_name, mine=(), theirs=()) -> Game:
    game = Game(players=[
        PlayerState("A", library=[by_name["Forest"]] * 12),
        PlayerState("B", library=[by_name["Forest"]] * 12),
    ])
    game.enforce_mana_costs = False
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=by_name[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    return game


def _named(game, seat, name) -> Permanent:
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def test_circle_of_protection_black_may_choose_a_black_knight(by_name):
    """Black Knight has protection from white and the Circle is white. The
    Circle does not target, so the Knight is offered, may be named, and its
    damage is prevented."""
    game = _duel(by_name, mine=["Circle of Protection: Black"], theirs=["Black Knight"])
    circle, knight = _named(game, 0, "Circle of Protection: Black"), _named(game, 1, "Black Knight")

    offered, _spells = _offered(game, circle, 0)
    assert _slot(game, knight) in offered

    assert game.queue_permanent_ability(
        0, "Circle of Protection: Black", target_permanent_ids=[knight.permanent_id],
    ).supported
    resolve_stack(game)
    game._deal_damage_to_player(game.players[0], 2, source=knight)

    assert game.players[0].life == 20


def test_circle_of_protection_red_refuses_a_green_source(by_name):
    """"The next time a **red** source of your choice…": a Grizzly Bears is
    not one. Refused, with nothing on the stack."""
    game = _duel(
        by_name, mine=["Circle of Protection: Red"], theirs=["Grizzly Bears", "Hill Giant"],
    )
    bears = _named(game, 1, "Grizzly Bears")

    result = game.queue_permanent_ability(
        0, "Circle of Protection: Red", target_permanent_ids=[bears.permanent_id],
    )

    assert not result.supported
    assert game.stack == []


def test_a_circle_prevents_the_chosen_source_and_not_its_neighbour(by_name):
    """Two red creatures; the Circle names the Hill Giant. The Goblin's 1
    lands, the Giant's 3 does not, and the Giant's *second* 3 does (CR 615.8:
    "any subsequent instances of damage … are dealt normally")."""
    game = _duel(
        by_name, mine=["Circle of Protection: Red"], theirs=["Hill Giant", "Mons's Goblin Raiders"],
    )
    giant, goblin = _named(game, 1, "Hill Giant"), _named(game, 1, "Mons's Goblin Raiders")

    assert game.queue_permanent_ability(
        0, "Circle of Protection: Red", target_permanent_ids=[giant.permanent_id],
    ).supported
    resolve_stack(game)
    assert any("Hill Giant" in line for line in game.log[-3:])

    game._deal_damage_to_player(game.players[0], 1, source=goblin)
    assert game.players[0].life == 19
    game._deal_damage_to_player(game.players[0], 3, source=giant)
    assert game.players[0].life == 19
    game._deal_damage_to_player(game.players[0], 3, source=giant)
    assert game.players[0].life == 16


def test_a_circle_rechecks_the_chosen_sources_colour(by_name):
    """CR 615.9 / 609.7b: the chosen Hill Giant, turned blue before it deals
    its damage, is no longer a red source — the damage is dealt and the shield
    is not used up."""
    from engine.color_changes import change_color

    game = _duel(by_name, mine=["Circle of Protection: Red"], theirs=["Hill Giant"])
    giant = _named(game, 1, "Hill Giant")
    assert game.queue_permanent_ability(
        0, "Circle of Protection: Red", target_permanent_ids=[giant.permanent_id],
    ).supported
    resolve_stack(game)

    change_color(giant, "U")
    game._deal_damage_to_player(game.players[0], 3, source=giant)
    assert game.players[0].life == 17

    change_color(giant, "R")
    game._deal_damage_to_player(game.players[0], 3, source=giant)
    assert game.players[0].life == 17


def test_a_circle_activated_naming_nothing_still_answers_the_colour(by_name):
    """The headless caller's default, unchanged: an activation that names no
    source arms the sourceless form, which answers the next red source."""
    game = _duel(by_name, mine=["Circle of Protection: Red"], theirs=["Hill Giant"])
    giant = _named(game, 1, "Hill Giant")
    assert game.queue_permanent_ability(0, "Circle of Protection: Red").supported
    resolve_stack(game)

    game._deal_damage_to_player(game.players[0], 3, source=giant)

    assert game.players[0].life == 20


def test_nova_pentacle_moves_the_chosen_sources_damage_and_no_other(by_name):
    """"The next time a source of your choice would deal damage to you this
    turn, that damage is dealt to target creature of an opponent's choice
    instead." The picker asks for the source and its answer arrives as the
    ability's named permanent; the handler read a second channel nothing had
    written, found no source, and armed the record against *any* — so the
    Grizzly Bears' damage was moved where the Hill Giant had been chosen."""
    game = _duel(
        by_name, mine=["Nova Pentacle", "Craw Wurm"], theirs=["Hill Giant", "Grizzly Bears"],
    )
    game.interactive_seats = set()
    giant, bears = _named(game, 1, "Hill Giant"), _named(game, 1, "Grizzly Bears")

    assert game.queue_permanent_ability(
        0, "Nova Pentacle", target_permanent_ids=[giant.permanent_id],
    ).supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)

    game._deal_damage_to_player(game.players[0], 2, source=bears)
    assert game.players[0].life == 18
    game._deal_damage_to_player(game.players[0], 3, source=giant)
    assert game.players[0].life == 18
    assert sum(p.damage_marked for p in game.all_permanents()) == 3
