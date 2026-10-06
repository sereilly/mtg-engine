""""Each player chooses …, then sacrifices the rest" is one event.

Cataclysm's ruling (2004-10-04, fetched from Scryfall): "The current player
makes their choices before the other player. After both players make choices,
**all the sacrifices are done simultaneously**."

The ``keep_permanents`` prompt performed its own seat's half as each seat
answered, on the strength of a docstring that said one player's sacrifices
cannot change another's board. They can — an Aura that stole a creature, an
artifact that makes Swamps creatures — and a permanent that watches things
leave is one event's witness rather than one seat's. So the answers are held
(``Game.new_keep_batch``) and the last one performs all of them, which is
``engine/piles.py``'s rule for the same reason: nothing moves until the last
answer.

The per-card halves are in each card's set file. This is the pool-wide census
and the invented card.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.faces import compilation_units
from engine.game_types import CardDefinition, OracleExecutionContext, Permanent
from engine.handlers import EFFECT_HANDLERS
from engine.oracle import compile_card_oracle
from engine.oracle_types import OracleInstruction
from tests.helpers import resolve_stack

KIND = "keep_chosen_sacrifice_rest"


def _card(name: str, type_line: str, text: str = "", **raw) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text=text,
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, **raw},
    )


def _instructions(value):
    if isinstance(value, OracleInstruction):
        yield value
        value = value.payload
    if isinstance(value, dict):
        value = tuple(value.values())
    if isinstance(value, (list, tuple)):
        for inner in value:
            yield from _instructions(inner)


def _several_seat_keeps(pool):
    """``(card, instruction)`` for every keep prompt armed for several seats."""
    for card in compilation_units(pool):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        roots = [
            *program.instructions,
            *(ability.instruction for ability in program.activated_abilities),
            *(ability.instruction for ability in program.triggered_abilities),
        ]
        seen: list[OracleInstruction] = []
        for step in _instructions(roots):
            if step.kind != KIND or any(step is found for found in seen):
                continue
            seen.append(step)
            if step.payload.get("who") in ("each_player", "each_opponent"):
                yield card, step


def _a_board_each(game: Game) -> None:
    """Enough of everything that every seat has both something to keep and
    something to give up under any of the pool's keep sentences."""
    basics = ("Plains", "Island", "Swamp", "Mountain", "Forest")
    for seat in range(len(game.players)):
        for basic in basics + basics[:3]:
            game._put_permanent_onto_battlefield(
                seat, Permanent(card=_card(basic, f"Basic Land — {basic}")), None
            )
        for name, type_line in (
            ("Relic", "Artifact"), ("Other Relic", "Artifact"),
            ("Shrine", "Enchantment"), ("Other Shrine", "Enchantment"),
        ):
            game._put_permanent_onto_battlefield(seat, Permanent(card=_card(name, type_line)), None)
        for name in ("Bear", "Other Bear"):
            game._put_permanent_onto_battlefield(
                seat,
                Permanent(card=_card(name, "Creature — Bear", power="2", toughness="2")),
                None,
            )


def _board(game: Game):
    return (
        [[perm.permanent_id for perm in game.controlled_by(seat)]
         for seat in range(len(game.players))],
        [[c.name for c in p.hand] for p in game.players],
        [[c.name for c in p.graveyard] for p in game.players],
    )


def test_no_keep_prompt_moves_anything_before_the_last_seat_answers(catalog):
    """The census: every several-seat keep in the pool, resolved at a
    three-seat table of interactive seats, each answered in turn with the
    answer its own registered default gives. The board is the same after the
    first answer and after the second, and different after the third.

    On the tree this was written against every one of them had moved the first
    seat's permanents by the first answer.
    """
    examined = []
    for card, instruction in _several_seat_keeps(catalog):
        game = Game(players=[PlayerState(name=n) for n in ("A", "B", "C")])
        game.enforce_mana_costs = False
        game.interactive_seats = {0, 1, 2}
        _a_board_each(game)
        context = OracleExecutionContext(
            caster=game.players[0], target=game.players[1], card=card,
        )
        before = _board(game)
        EFFECT_HANDLERS[KIND](game, instruction, context)
        owed = [c for c in game.pending_choices if c.kind == "keep_permanents"]
        # "Each opponent" at three seats is still two answers.
        assert len(owed) >= 2, card.name
        for choice in owed[:-1]:
            game._default_keep_permanents(choice)
            assert _board(game) == before, f"{card.name}: moved before the last answer"
        game._default_keep_permanents(owed[-1])
        assert _board(game) != before, f"{card.name}: the last answer applied nothing"
        assert not [c for c in game.pending_choices if c.kind == "keep_permanents"]
        examined.append(card.name)

    # Cataclysm, Global Ruin, Planar Overlay and Limited Resources on the tree
    # this was written against.
    assert len(examined) >= 4, examined
    for sighting in ("Cataclysm", "Global Ruin", "Planar Overlay"):
        assert sighting in examined


# -- an invented card ------------------------------------------------------------


def test_an_invented_keep_is_one_event_for_a_watcher_given_up_in_it():
    """"Each player chooses two creatures they control and sacrifices the
    rest", on a sorcery nobody printed, with a creature that watches
    creatures die. The watcher is one of the things its controller gives up — and it
    still sees the other creatures go in the same event, the other player's
    included (CR 603.10a: a leaves-the-battlefield ability looks back).

    One seat at a time, the watcher was gone before the other seat's creatures
    were sacrificed and its controller gained nothing for them.
    """
    purge = _card(
        "Thin the Herd", "Sorcery",
        "Each player chooses two creatures they control and sacrifices the rest.",
    )
    assert compile_card_oracle(purge).supported
    watcher = _card(
        "Carrion Watcher", "Creature — Bird",
        "Whenever a creature dies, you gain 1 life.",
        power="1", toughness="1",
    )
    assert compile_card_oracle(watcher).supported

    def bear(name):
        return _card(name, "Creature — Bear", power="2", toughness="2")

    game = Game(players=[
        PlayerState(name="P1", hand=[purge]), PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    mine = [Permanent(card=c) for c in (watcher, bear("A"), bear("B"), bear("C"))]
    theirs = [Permanent(card=bear(n)) for n in ("W", "X", "Y", "Z")]
    for perm in mine:
        game._put_permanent_onto_battlefield(0, perm, None)
    for perm in theirs:
        game._put_permanent_onto_battlefield(1, perm, None)

    assert game.queue_from_hand(0, "Thin the Herd").supported
    game.resolve_top_of_stack(pause_for_choices=True)
    # P1 keeps two Bears and gives up the Watcher and a Bear; P2 gives up two.
    assert game.confirm_keep_permanents(0, [mine[1].permanent_id, mine[2].permanent_id])
    assert len(list(game.controlled_by(0))) == 4, "nothing has moved yet"
    assert game.confirm_keep_permanents(1, [theirs[0].permanent_id, theirs[1].permanent_id])
    resolve_stack(game)

    assert sorted(p.card.name for p in game.controlled_by(0)) == ["A", "B"]
    assert sorted(p.card.name for p in game.controlled_by(1)) == ["W", "X"]
    # C, Y and Z: the three creatures that died beside the Watcher, two of
    # them the other player's. (Whether a watcher also answers to its *own*
    # death is the dies-dispatcher's question and not this test's; it does
    # not, today, on any road.) One seat at a time this was 20.
    assert game.players[0].life == 23, game.log
