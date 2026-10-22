"""A cast trigger's "it" is the spell that fired it (CR 603.3, CR 608.2b).

Two Lightning Bolts on the stack are two objects cast from one card: a deck
repeats one immutable ``CardDefinition`` per copy, and both seats' decks are
built from one catalog. A cast trigger used to carry that card and look for
"the stack item whose card is this" — so with a look-alike underneath, Nether
Void's trigger for the second Bolt demanded its {3} for the first, and a
trigger whose own spell had already been countered went on to act on the
look-alike.

The fire sites carry the spell's ``StackItem`` now (``cast_item``) and the
readers ask ``handlers._targets.triggering_spell``.
``tests/engine/test_cast_trigger_spell_identity.py`` asks both questions of
every such trigger in the pool; these are the two shipped shapes — a counter
and a copy — with the stack and the log read at each step.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import _nosick, resolve_stack


def _table(catalog_by_name, source, *, hands):
    """Seat 0 controls *source* at its main phase; *hands* is per seat."""
    game = Game(players=[
        PlayerState(
            name=f"P{seat}",
            hand=[catalog_by_name[name] for name in hands[seat]],
            battlefield=[_nosick(Permanent(card=catalog_by_name[source]))] if seat == 0 else [],
            library=[catalog_by_name["Forest"]] * 6,
        )
        for seat in (0, 1)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    return game


def _spells(game) -> list:
    return [item for item in game.stack if not item.is_ability]


def test_nether_voids_trigger_for_the_second_bolt_is_about_the_second_bolt(catalog_by_name):
    """"Whenever a player casts a spell, counter it unless that player pays
    {3}." Two Bolts, the second cast in response to the first one's trigger.
    The top trigger is the second Bolt's: unpaid, it counters the Bolt aimed at
    seat 0 and leaves the Bolt aimed at seat 1 where it was. It used to counter
    the first Bolt and let the second through."""
    game = _table(
        catalog_by_name, "Nether Void", hands=(["Lightning Bolt", "Lightning Bolt"], []),
    )
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=0).supported
    first, second = _spells(game)
    assert first.card is second.card, "one card, two spells — the whole of the defect"
    assert [item.card.name for item in game.stack] == [
        "Lightning Bolt", "Nether Void", "Lightning Bolt", "Nether Void",
    ]

    game.resolve_top_of_stack()

    assert _spells(game) == [first] and _spells(game)[0] is first
    assert "Lightning Bolt was countered by Nether Void and moved to graveyard" in game.log

    resolve_stack(game)
    # Both were countered in the end, each by its own trigger, and nobody took
    # 3: the first Bolt's trigger still found the first Bolt.
    assert [player.life for player in game.players] == [20, 20]
    assert [card.name for card in game.players[0].graveyard] == [
        "Lightning Bolt", "Lightning Bolt",
    ]


def test_nether_void_does_not_counter_a_bystander_once_its_spell_is_gone(catalog_by_name):
    """The second Bolt is countered in response to its own Nether Void
    trigger. The trigger then has nothing to counter (CR 608.2b's shape) — it
    used to find the first Bolt, which is the same card, and counter that."""
    game = _table(
        catalog_by_name, "Nether Void", hands=(["Lightning Bolt", "Lightning Bolt"], []),
    )
    game.queue_from_hand(0, "Lightning Bolt", target_player_index=1)
    game.queue_from_hand(0, "Lightning Bolt", target_player_index=0)
    first, second = _spells(game)

    game.counter_stack_object(second)
    game.resolve_top_of_stack()

    assert _spells(game)[0] is first and len(_spells(game)) == 1
    assert "Nether Void: the spell it would counter is no longer on the stack" in game.log


def test_double_vision_copies_its_own_spell_even_once_it_was_countered(catalog_by_name):
    """"Whenever you cast your first instant or sorcery spell each turn, copy
    that spell." An opponent's Bolt is on the stack; seat 0 answers with its
    own first Bolt of the turn, which is countered in response to the copy
    trigger. The copy is still made, of seat 0's Bolt as it last existed
    (CR 608.2h; Double Vision's ruling of 2020-06-23: "A copy is created even
    if the spell that caused Double Vision's ability to trigger has been
    countered by the time that ability resolves") — and never of the
    opponent's Bolt underneath, which is the same card and is what the
    trigger used to copy. For a while it copied nothing at all, which was
    the look-alike fixed by answering a different question."""
    game = _table(
        catalog_by_name, "Double Vision", hands=(["Lightning Bolt"], ["Lightning Bolt"]),
    )
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    theirs, mine = _spells(game)
    assert theirs.card is mine.card
    assert game.stack[-1].card.name == "Double Vision"

    game.counter_stack_object(mine)
    game.resolve_top_of_stack()

    assert game.stack[0] is theirs
    (copy,) = [item for item in game.stack if item.is_copy]
    # Seat 0's Bolt was aimed at seat 1; the look-alike is aimed at seat 0.
    assert copy.caster_index == 0 and copy.target_player_index == 1
    resolve_stack(game)
    assert [player.life for player in game.players] == [17, 17]


def test_double_vision_copies_its_own_bolt_over_a_look_alike(catalog_by_name):
    """The same stack with nothing countered: the copy is of seat 0's Bolt —
    aimed where seat 0 aimed it — and seat 1 takes 6."""
    game = _table(
        catalog_by_name, "Double Vision", hands=(["Lightning Bolt"], ["Lightning Bolt"]),
    )
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    game.queue_from_hand(0, "Lightning Bolt", target_player_index=1)

    game.resolve_top_of_stack()
    copy = game.stack[-1]
    assert copy.is_copy and copy.target_player_index == 1 and copy.caster_index == 0

    resolve_stack(game)
    assert [player.life for player in game.players] == [17, 14]
