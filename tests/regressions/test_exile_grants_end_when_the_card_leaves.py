"""Regression: "for as long as it remains exiled" ends when the card leaves.

``CastPermission.duration == "while_exiled"`` was swept by nothing, on the
argument that ``cast_permissions._covers`` already re-checks that the named
card is still in the granted zone. That argument is about the card being
*absent*, which is half of the duration. The other half is CR 400.7: a card
that leaves exile and comes back later is a new object with no relation to the
one the grant named — and the grant found it again by identity. A deck repeats
one immutable ``CardDefinition`` per copy, so it did not even have to be the
same physical card.

Psychic Theft (Invasion, shipped) was the card living it: "…exile that card.
You may cast that card for as long as it remains exiled. At the beginning of
the next end step, if you haven't cast the card, return it to its owner's
hand." The end step returned the card and the grant stayed in
``Game.cast_permissions`` for the rest of the game, letting its caster cast any
copy of that card that anything ever exiled again. Nothing could see it: no
compiled program was wrong, and the card behaved for as long as a test stopped
at the end step.

Found while landing Planeswalker's Mischief (Planeshift), which prints the same
three sentences with a cost waiver on the middle one — a *free* cast is the
version of this defect worth finding first. The fix is at the one seam a card
leaves exile by (``Game.take_card_from_exile``).

The second half of this file is the other thing that card needed and no card
had asked for: "exile **it**" behind a step that turned a card up. Read as the
ability's own source it lowered to ``exile_self``. No shipped card printed the
pair — the census below is the measurement, with a floor on how much it looked
at — but the pronoun now names the card whichever zone it was turned up in.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.cast_permissions import end_while_exiled_grants, grant_permission, permission_for
from engine.faces import compilation_units
from engine.grammar.lowering._records import produced_keys
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, resolve_stack


def _theft_game(catalog_by_name, held):
    """Seat 0 holds Psychic Theft; seat 1 holds *held*. Nobody is interactive."""
    game = Game(players=[
        PlayerState(
            name="A", hand=[catalog_by_name["Psychic Theft"]],
            library=[catalog_by_name["Forest"]] * 5,
        ),
        PlayerState(
            name="B", hand=[catalog_by_name[name] for name in held],
            library=[catalog_by_name["Forest"]] * 5,
        ),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    assert game.cast_from_hand(0, "Psychic Theft", target_player_index=1).supported
    # The pick is owed with an empty stack; the default takes the first legal card.
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    return game


def test_psychic_theft_stops_lending_the_card_once_it_is_returned(catalog_by_name):
    """The defect, end to end. The Bolt is exiled and lent; nobody casts it; the
    end step returns it. The grant must be gone — and when the *same card* is
    exiled again by something else, its old borrower may not cast it."""
    game = _theft_game(catalog_by_name, ["Lightning Bolt"])
    mine, theirs = game.players
    assert [card.name for card in theirs.exile] == ["Lightning Bolt"]
    assert len(game.cast_permissions) == 1

    game.resolve_end_step(0)
    resolve_stack(game)

    assert [card.name for card in theirs.hand] == ["Lightning Bolt"]
    assert game.cast_permissions == []
    # CR 400.7: exiled again, it is a new object the old effect never named.
    bolt = theirs.hand.pop(0)
    theirs.exile.append(bolt)
    assert permission_for(game, 0, bolt, "exile") is None
    # …and the cast path agrees: with no grant it does not even find the card,
    # which for a pile that is not the caster's own is a ValueError.
    with pytest.raises(ValueError, match="Card not in exile"):
        game.queue_from_hand(0, "Lightning Bolt", from_zone="exile")


def test_psychic_theft_still_lends_the_card_while_it_is_exiled(catalog_by_name):
    """The other direction: the fix ends nothing early. The card is cast out of
    the opponent's exile, at the caster's expense, into its owner's graveyard."""
    game = _theft_game(catalog_by_name, ["Lightning Bolt"])
    mine, theirs = game.players

    cast = game.cast_from_hand(
        0, "Lightning Bolt", from_zone="exile", target_player_index=1
    )
    resolve_stack(game)

    assert cast.supported, cast.details
    assert theirs.life == 17
    assert [card.name for card in theirs.graveyard] == ["Lightning Bolt"]
    assert game.cast_permissions == []


def test_a_grant_names_a_card_no_more_often_than_exile_holds_it(catalog_by_name):
    """Counted, not cleared. Two copies of one card in one exile are one object
    named by two grants; one copy leaving ends one grant's worth and the other
    copy is still lent."""
    bolt = catalog_by_name["Lightning Bolt"]
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B", exile=[bolt, bolt])])
    for _ in range(2):
        grant_permission(
            game, player_index=0, zone="exile", mode="cast", cards=[bolt],
            duration="while_exiled", zone_player_index=1,
        )

    assert game.take_card_from_exile(game.players[1], bolt)
    assert sum(len(grant.cards) for grant in game.cast_permissions) == 1
    assert permission_for(game, 0, bolt, "exile") is not None

    assert game.take_card_from_exile(game.players[1], bolt)
    assert game.cast_permissions == []


def test_a_departure_ends_only_while_exiled_grants_over_that_pile(catalog_by_name):
    """What the sweep must *not* reach: a grant with a stated moment (CR 611.2a)
    is the cleanup step's to end, and a grant over another seat's pile is about
    another card."""
    bolt = catalog_by_name["Lightning Bolt"]
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    grant_permission(
        game, player_index=0, zone="exile", mode="cast", cards=[bolt],
        duration="end_of_turn", zone_player_index=1,
    )
    grant_permission(
        game, player_index=0, zone="exile", mode="cast", cards=[bolt],
        duration="while_exiled",
    )

    end_while_exiled_grants(game, 1, bolt)

    assert [grant.duration for grant in game.cast_permissions] == [
        "end_of_turn", "while_exiled",
    ]


def test_exile_it_behind_a_library_reveal_exiles_the_revealed_card(catalog_by_name):
    """An invented card, because no shipped one prints the pair: "Reveal the top
    card of your library. If it's a land card, exile it." The pronoun is the
    card the reveal turned up — off the top of its owner's library, into its
    owner's exile — and never the spell that said so."""
    probe = _mk_card(
        "Probe of the Revealed Card", "{1}", "Sorcery",
        "Reveal the top card of your library. If it's a land card, exile it.",
    )
    program = compile_card_oracle(probe)
    assert program.supported, program.reason
    game = Game(players=[
        PlayerState(
            name="A", hand=[probe, probe],
            library=[catalog_by_name["Forest"], catalog_by_name["Grizzly Bears"]],
        ),
        PlayerState(name="B"),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    mine = game.players[0]

    assert game.cast_from_hand(0, probe.name).supported
    resolve_stack(game)
    assert [card.name for card in mine.exile] == ["Forest"]
    assert [card.name for card in mine.library] == ["Grizzly Bears"]
    assert [card.name for card in mine.graveyard] == [probe.name]

    # A creature card on top: revealed, not a land, and it stays where it is.
    assert game.cast_from_hand(0, probe.name).supported
    resolve_stack(game)
    assert [card.name for card in mine.exile] == ["Forest"]
    assert [card.name for card in mine.library] == ["Grizzly Bears"]


def _exile_self_behind_a_reveal(instructions, produced, found, name):
    """Collect *name* where an ``exile_self`` follows a step that recorded
    ``revealed_card`` — the reading "exile it" must not have there."""
    for instruction in instructions:
        if instruction is None:
            continue
        if instruction.kind == "exile_self" and "revealed_card" in produced:
            found.append(name)
        for key in ("steps", "then", "else", "otherwise", "action"):
            nested = instruction.payload.get(key)
            if isinstance(nested, tuple) and nested and hasattr(nested[0], "kind"):
                # A sequence's steps share the scratchpad they write; a branch
                # reads what came before it and leaks nothing back.
                _exile_self_behind_a_reveal(
                    nested, produced if key == "steps" else set(produced), found, name
                )
        produced |= set(produced_keys(instruction))


def test_no_card_exiles_its_own_source_behind_a_reveal():
    """The census, over both manifest roles: no compiled program has an
    ``exile_self`` behind a step that turned a card up.

    The pair is not hypothetical: before this round's lowering, the first two
    sentences of Planeswalker's Mischief ("…reveals a card at random from their
    hand. If it's an instant or sorcery card, exile it") compiled to a reveal
    and an ``if_then`` whose branch was ``exile_self``. That the walk names
    such a pair is the test below this one; and it carries a floor on what it
    examined, because a census that measured nothing reads the same as one
    that found nothing.
    """
    cards = compilation_units(load_cards(manifest_set_paths(include_measured=True)))
    examined = 0
    found: list[str] = []
    for card in cards:
        program = compile_card_oracle(card)
        roots = list(program.instructions)
        roots += [ability.instruction for ability in program.activated_abilities]
        roots += [ability.instruction for ability in program.triggered_abilities]
        for root in roots:
            if root is None:
                continue
            examined += 1
            _exile_self_behind_a_reveal((root,), set(), found, card.name)

    assert examined > 9000, examined
    assert sorted(set(found)) == []


def test_the_census_names_the_pair_it_is_looking_for():
    """The backwards half, kept as a test: the walk above reports a hand-built
    ``reveal`` then ``exile_self``, in a sequence and inside a branch, and does
    not report an ``exile_self`` with no reveal in front of it."""
    from engine.oracle_types import OracleInstruction

    reveal = OracleInstruction("reveal_random_card_from_hand", "", {})
    exile = OracleInstruction("exile_self", "", {})
    branch = OracleInstruction("if_then", "", {"condition": {}, "then": (exile,), "else": ()})

    found: list[str] = []
    for label, steps in (
        ("flat", (reveal, exile)),
        ("branch", (reveal, branch)),
        ("no reveal", (exile, reveal)),
    ):
        _exile_self_behind_a_reveal(
            (OracleInstruction("sequence", "", {"steps": steps}),), set(), found, label
        )

    assert found == ["flat", "branch"]
