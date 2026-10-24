"""A card **from outside the game** (CR 400.11), as a noun-phrase scope.

"…a sorcery card you own from outside the game" is not a zone — CR 400.11:
"Outside the game is not a zone" — so the noun parser records it as a field of
its own (``ObjectFilter.outside_the_game``), never emitted by ``to_payload``
and listed in ``lowering/_filters.CONDITIONALLY_EMITTED_FIELDS``. That makes
every lowering not written for it refuse the phrase by name instead of looking
for the card on the battlefield or in some zone its handler defaults to — the
silent widening a new filter field is engineered against.

Three halves: the one production that reads the scope honours the printed
narrowings it is handed (and refuses the ones a card cannot answer); every
other production refuses; and every card in the pool that prints the words
compiles onto the one pick or Ring of Ma'rûf's draw interceptor.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.grammar import compile_line
from engine.oracle import compile_card_oracle
from tests.helpers import CARDS_BY_NAME, _mk_card, resolve_stack

#: The two instruction kinds a card from outside the game is brought in by.
_OUTSIDE_GAME_KINDS = frozenset({
    "put_outside_game_card_into_hand", "arm_outside_game_draw_replacement",
})


@pytest.mark.parametrize("line", [
    "exile a card you own from outside the game",
    "discard a card you own from outside the game",
    "return target creature card you own from outside the game to your hand",
    "search your library for a card you own from outside the game, put it into "
    "your hand, then shuffle",
    "draw a card for each card you own from outside the game",
    "put a card you own from outside the game on top of your library",
])
def test_a_production_not_written_for_the_scope_refuses_it(line):
    """Each line parses as far as its own production goes and then refuses —
    in the parse or in the lowering — rather than compiling as though the
    three words were not printed."""
    compiled = compile_line(line, card_name="Probe")
    assert not compiled.instructions, (line, compiled.instructions)
    assert compiled.parse_error or compiled.lowering_error


@pytest.mark.parametrize("line, refusal", [
    # A keyword is a battlefield question; a card in a sideboard has none to ask.
    ("you may reveal a creature card with flying you own from outside the game "
     "and put it into your hand", "cannot test that card phrase"),
    # CR 400.11a: a *player's* sideboard; the pick reads the caster's own.
    ("you may reveal a card an opponent owns from outside the game and put it "
     "into your hand", "does not say 'you own'"),
    ("put a creature card from outside the game into your hand", "you own"),
])
def test_the_pick_refuses_a_narrowing_it_cannot_honour(line, refusal):
    compiled = compile_line(line, card_name="Probe")
    assert not compiled.instructions
    assert refusal in (compiled.lowering_error or ""), compiled.lowering_error


def test_a_printed_colour_narrows_what_the_pick_offers():
    """A card that prints a colour where the Wishes print a type (Glittering
    Wish's "multicolored", a red Wish) is the same production with another
    card-testable key — and the key is *enforced*: of a red and a blue card
    outside the game only the red one is offered, and the blue one is refused
    as an answer."""
    wish = _mk_card(
        "Probe Wish", "{1}{R}", "Sorcery",
        "You may reveal a red card you own from outside the game and put it into "
        "your hand. Exile Probe Wish.",
    )
    assert compile_card_oracle(wish).supported
    game = Game(players=[
        PlayerState(
            name="Alice", hand=[wish], library=[CARDS_BY_NAME["Island"]] * 3,
            sideboard=[CARDS_BY_NAME["Ancestral Recall"], CARDS_BY_NAME["Lightning Bolt"]],
        ),
        PlayerState(name="Bob", library=[CARDS_BY_NAME["Island"]] * 3),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.start_turn(0)
    assert game.cast_from_hand(0, "Probe Wish").supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.resolve_pending_choice("optional_pay", 0, accept=True, option=None)
    (pick,) = game.pending_choices_of("outside_game_pick")

    assert game.live_outside_game_picks(pick) == [1]
    assert not game.confirm_outside_game_pick(0, 0)
    assert game.confirm_outside_game_pick(0, 1)
    resolve_stack(game)
    assert [card.name for card in game.players[0].hand] == ["Lightning Bolt"]


def _flat_kinds(program) -> set[str]:
    def walk(instructions):
        for instruction in instructions or ():
            yield instruction.kind
            for key in ("steps", "action", "then", "otherwise", "instruction"):
                inner = instruction.payload.get(key)
                if isinstance(inner, tuple | list):
                    yield from walk(inner)
                elif inner is not None and hasattr(inner, "kind"):
                    yield from walk((inner,))

    kinds = set(walk(program.instructions))
    for ability in (*program.activated_abilities, *program.triggered_abilities):
        if ability.instruction is not None:
            kinds |= set(walk((ability.instruction,)))
    return kinds


def test_every_card_printing_the_words_brings_a_card_in():
    """Census, over both manifest roles: each card whose text says "from
    outside the game" is supported, and its program reaches one of the two
    kinds that read a sideboard. Before the Judgment Wishes five of these were
    unsupported (the census's backwards check), and Ring of Ma'rûf was a card
    hook the grammar could not see behind. The floor is the six cards that
    printed the words on the day this was written."""
    cards = load_cards(manifest_set_paths(include_measured=True))
    printing = [
        card for card in compilation_units(cards)
        if "from outside the game" in (card.oracle_text or "").lower()
    ]
    assert len(printing) >= 6, [card.name for card in printing]
    stray = [
        card.name for card in printing
        if not compile_card_oracle(card).supported
        or not (_flat_kinds(compile_card_oracle(card)) & _OUTSIDE_GAME_KINDS)
    ]
    assert not stray, stray
