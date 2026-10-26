"""Three shipped behaviours Onslaught's revealing round found wrong.

* An opponent nobody asks picked the **costliest** revealed card whatever the
  pick was for — right where the pick is lost (Thran Tome bins it), backwards
  where the revealer gets it: Intuition's AI opponent handed the caster the
  best of its three cards.
* ``static_line_support`` admitted "this creature enters with x +1/+1 counters
  on it" as a *prefix*, so any tail behind it was claimed and dropped (Stag
  Beetle entered 0/0 every time).
* The reveal-until lowering dropped "of that type" in silence (no payload
  form), so a run "until you reveal a creature card of that type" stopped on
  the first creature card of any type.
"""

from engine import Game
from engine.models import CardDefinition, PlayerState
from engine.grammar import compile_line
from engine.static_line_support import _is_supported_static_creature_line


def _card(name, cmc, type_line="Instant"):
    return CardDefinition(
        name=name, mana_cost="", type_line=type_line, oracle_text="",
        cmc=float(cmc), colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "oracle_text": ""},
    )


def test_intuitions_ai_opponent_hands_over_the_cheapest_card(set_pool):
    """"Search your library for three cards and reveal them. Target opponent
    chooses one. Put that card into your hand and the rest into your
    graveyard." The card the opponent names is the one the caster keeps, so
    a seat nobody asks names the cheapest — the 1 over the 6 and the 3."""
    spell = set_pool("TMP")["Intuition"]
    library = [_card("Six", 6), _card("One", 1), _card("Three", 3), _card("Spare", 2)]
    game = Game(players=[
        PlayerState(name="P0", library=list(library), hand=[spell]),
        PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game._settle()
    game.cast_from_hand(0, "Intuition", target_player_index=1)
    game.resolve_top_of_stack()
    assert game.confirm_search_library_picks(
        0, [{"zone": "library", "index": i} for i in (0, 1, 2)]
    )
    game.auto_resolve_pending_choices()
    assert [c.name for c in game.players[0].hand] == ["One"]
    assert sorted(c.name for c in game.players[0].graveyard) == [
        "Intuition", "Six", "Three",
    ]


def test_an_entry_counter_line_with_a_tail_is_not_admitted_by_its_head():
    """The exact "enters with X +1/+1 counters on it" (Rock Hydra) and the
    counted where-clause (Stag Beetle) are claimed; an invented tail nothing
    reads is not — it used to be, behind the prefix row."""
    assert _is_supported_static_creature_line(
        "This creature enters with X +1/+1 counters on it.", "Rock Hydra"
    )
    assert _is_supported_static_creature_line(
        "This creature enters with X +1/+1 counters on it, where X is the "
        "number of other creatures on the battlefield.", "Stag Beetle",
    )
    assert not _is_supported_static_creature_line(
        "This creature enters with X +1/+1 counters on it and you lose X life.",
        "Invented Beetle",
    )


def test_a_reveal_until_of_that_type_needs_a_step_that_chose_one():
    """"…until you reveal a creature card **of that type**" behind "Choose a
    creature type." carries the chosen word to the run; with no choosing step
    the words name nothing and the line refuses rather than stopping on any
    creature card."""
    tail = (
        "Reveal cards from the top of your library until you reveal a creature "
        "card of that type. Put that card onto the battlefield and shuffle the "
        "rest into your library."
    )
    chosen = compile_line("Choose a creature type. " + tail)
    assert chosen.usable
    run = [i for i in chosen.instructions if i.kind == "reveal_until_match"]
    assert run and run[0].payload["filter"].get("subtype_filter_from")
    # Thicket Elemental's spelling of the rest, which compiled before this
    # round with the narrowing dropped.
    alone = compile_line(tail.replace(
        "the rest into", "all other cards revealed this way into",
    ))
    assert not alone.usable
