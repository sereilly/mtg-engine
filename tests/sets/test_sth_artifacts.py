"""Stronghold artifacts.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("STH")` / `set_cards("STH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G5: player-action triggers and replacements ---
#
# Three artifacts whose *event* is something a player does — a land drop, an
# entry a player may pay for, a creature arriving on somebody's board. Driven
# through a real game in every case: a trigger condition can sit in both front
# ends' tables and still have nothing that announces it, and a replacement can
# claim its line and decline at run time, and no instrument here sees either.

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_G5_LEA_ART = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _g5_art_game(*players: PlayerState, costs: bool = False) -> Game:
    game = Game(players=list(players))
    game.enforce_mana_costs = costs
    return game


def test_horn_of_greed_draws_for_whichever_player_played_the_land(set_pool):
    """"Whenever **a player** plays a land, **that player** draws a card."

    The third value of an axis that had two. The event already existed for "you"
    and "an opponent" (Dirtcowl Wurm) — one announcement made at CR 305.1's
    special action, with the printed word as the narrowing — and the unnarrowed
    reading had no value at all, so the trigger never fired for anybody. The
    drawing seat is the one the land drop froze, because a land on a battlefield
    says nothing about who played it.
    """
    program = compile_card_oracle(set_pool("STH")["Horn of Greed"])
    assert program.supported, program.reason

    horn = Permanent(card=set_pool("STH")["Horn of Greed"])
    game = _g5_art_game(
        PlayerState(name="P1", battlefield=[horn], hand=[_G5_LEA_ART["Forest"]],
                    library=[_G5_LEA_ART["Mountain"]] * 8, life=20),
        PlayerState(name="P2", hand=[_G5_LEA_ART["Island"]],
                    library=[_G5_LEA_ART["Swamp"]] * 8, life=20),
        costs=True,
    )
    game.start_turn(0)
    game.resolve_stack()

    game.cast_from_hand(0, "Forest")
    game.resolve_stack()
    assert len(game.players[0].hand) == 1, game.log      # played one, drew one
    assert len(game.players[1].hand) == 1, game.log      # untouched

    game.start_next_turn()
    game.resolve_stack()
    before = len(game.players[1].hand)
    game.cast_from_hand(1, "Island")
    game.resolve_stack()
    # P2 played a land and P2 drew for it — the opponent's land drop feeds the
    # opponent, which is exactly what makes this the unnarrowed reading.
    assert len(game.players[1].hand) == before, game.log


def test_volraths_laboratory_makes_a_token_of_the_chosen_color_and_type(set_pool):
    """"As this artifact enters, choose a color and a creature type." /
    "{5}, {T}: Create a 2/2 creature token of **the chosen color and type**."

    Both halves are back-references to one CR 614.1c choice, so both are checked
    in one game: the prompt has to carry two answers, and the token has to read
    both records — its CR 111.4 name follows the subtype, so a dropped record
    would arrive as an unnamed colourless token.
    """
    program = compile_card_oracle(set_pool("STH")["Volrath's Laboratory"])
    assert program.supported, program.reason

    game = _g5_art_game(
        PlayerState(name="P1", hand=[set_pool("STH")["Volrath's Laboratory"]], life=20),
        PlayerState(name="P2", life=20),
    )
    game.interactive_seats = {0}
    game.start_turn(0)
    game.cast_from_hand(0, "Volrath's Laboratory")
    game.resolve_stack()

    lab = game.players[0].battlefield[0]
    assert game.confirm_enter_choice(0, mana_color="U", creature_type="merfolk"), game.log
    assert lab.metadata["chosen_color"] == "U"
    assert lab.metadata["chosen_creature_type"] == "merfolk"

    lab.metadata["summoning_sickness_turn"] = -99
    result = game.activate_permanent_ability(0, "Volrath's Laboratory")
    game.resolve_stack()
    assert result.supported, result

    token = game.players[0].battlefield[-1]
    assert token.card.name == "Merfolk Token", game.log
    assert token.has_type("merfolk"), game.log
    assert token.card.colors == ("U",), token.card.colors
    assert (token.effective_power, token.effective_toughness) == (2, 2)


def test_mox_diamond_enters_when_a_land_is_discarded_for_it(set_pool):
    """"If this artifact would enter, you may discard a land card instead. If
    you do, put this artifact onto the battlefield."

    The paying half of an optional CR 614.1a entry replacement.
    """
    program = compile_card_oracle(set_pool("STH")["Mox Diamond"])
    assert program.supported, program.reason

    game = _g5_art_game(
        PlayerState(name="P1",
                    hand=[set_pool("STH")["Mox Diamond"], _G5_LEA_ART["Forest"]],
                    life=20),
        PlayerState(name="P2", life=20),
    )
    game.interactive_seats = {0}
    game.start_turn(0)
    game.cast_from_hand(0, "Mox Diamond")
    game.resolve_stack()

    pending = game.pending_entry_discard_tolls
    assert pending, game.log
    assert game.confirm_entry_discard_toll(0, hand_index=pending[0]["hand_indices"][0])

    assert [p.card.name for p in game.players[0].battlefield] == ["Mox Diamond"], game.log
    assert [c.name for c in game.players[0].graveyard] == ["Forest"], game.log


def test_mox_diamond_declined_never_enters_the_battlefield(set_pool):
    """"If you don't, put it into its owner's graveyard."

    The declining half, and the reason the whole paragraph is one replacement:
    the artifact must never *be* on the battlefield. Letting it enter and
    binning it afterwards would put a permanent into a graveyard, which is a
    death (CR 700.4) — with an id, layer contributions and every
    enters-the-battlefield trigger in front of it.
    """
    game = _g5_art_game(
        PlayerState(name="P1",
                    hand=[set_pool("STH")["Mox Diamond"], _G5_LEA_ART["Forest"]],
                    life=20),
        PlayerState(name="P2", life=20),
    )
    game.interactive_seats = {0}
    game.start_turn(0)
    game.cast_from_hand(0, "Mox Diamond")
    game.resolve_stack()

    assert game.confirm_entry_discard_toll(0, hand_index=None)
    assert not game.players[0].battlefield, game.log
    assert [c.name for c in game.players[0].graveyard] == ["Mox Diamond"], game.log
    assert [c.name for c in game.players[0].hand] == ["Forest"], game.log


def test_mox_diamond_with_no_land_in_hand_goes_to_the_graveyard(set_pool):
    """CR 101.3 with nothing to choose from: an offer whose only answer is the
    decline. The permanent still never enters."""
    game = _g5_art_game(
        PlayerState(name="P1",
                    hand=[set_pool("STH")["Mox Diamond"], _G5_LEA_ART["Black Lotus"]],
                    life=20),
        PlayerState(name="P2", life=20),
    )
    game.start_turn(0)
    game.cast_from_hand(0, "Mox Diamond")
    game.resolve_stack()

    assert not game.players[0].battlefield, game.log
    assert [c.name for c in game.players[0].graveyard] == ["Mox Diamond"], game.log
    assert [c.name for c in game.players[0].hand] == ["Black Lotus"], game.log


def test_mox_diamond_taps_for_mana_once_it_is_out(set_pool):
    """The second printed line, which is only reachable through the first: a
    replacement that consumed the entry and never put anything back would leave
    this untestable and the card reporting supported."""
    game = _g5_art_game(
        PlayerState(name="P1",
                    hand=[set_pool("STH")["Mox Diamond"], _G5_LEA_ART["Forest"]],
                    life=20),
        PlayerState(name="P2", life=20),
    )
    game.start_turn(0)
    game.cast_from_hand(0, "Mox Diamond")
    game.resolve_stack()

    mox = game.players[0].battlefield[0]
    mox.metadata["summoning_sickness_turn"] = -99
    result = game.activate_permanent_ability(0, "Mox Diamond", mana_color="U")
    game.resolve_stack()
    assert result.supported, result
    assert game.players[0].mana_pool["U"] == 1, game.log


def _g5_portcullis_board(set_pool, existing: int) -> tuple[Game, Permanent]:
    """A Portcullis and *existing* Bears already on the battlefield, each cast
    so that every one of them entered through the one entry path."""
    portcullis = Permanent(card=set_pool("STH")["Portcullis"])
    game = _g5_art_game(
        PlayerState(name="P1", battlefield=[portcullis],
                    hand=[_G5_LEA_ART["Grizzly Bears"]] * (existing + 1), life=20),
        PlayerState(name="P2", life=20),
    )
    game.start_turn(0)
    for _ in range(existing):
        game.cast_from_hand(0, "Grizzly Bears")
        game.resolve_stack()
    return game, portcullis


def test_portcullis_lets_the_first_two_creatures_through(set_pool):
    """"…if there are two or more **other** creatures on the battlefield."

    CR 603.4's intervening-if, and the word "other" is what makes the threshold
    three creatures rather than two: it excludes the creature that just entered,
    not the artifact, which is not a creature and could never be counted. Read
    as the source instead, the second Bears would have been exiled.
    """
    program = compile_card_oracle(set_pool("STH")["Portcullis"])
    assert program.supported, program.reason

    for already_out in (0, 1):
        game, _ = _g5_portcullis_board(set_pool, already_out)
        game.cast_from_hand(0, "Grizzly Bears")
        game.resolve_stack()
        assert not game.players[0].exile, (already_out, game.log)
        creatures = [p for p in game.players[0].battlefield if p.has_type("creature")]
        assert len(creatures) == already_out + 1, (already_out, game.log)


def test_portcullis_exiles_the_third_creature_and_gives_it_back(set_pool):
    """The threshold met, and the second printed sentence behind it: the exile
    is CR 610.3-linked to the artifact, so the creature comes back when the
    artifact leaves — under its owner's control, as a new object."""
    game, portcullis = _g5_portcullis_board(set_pool, 2)
    game.cast_from_hand(0, "Grizzly Bears")
    game.resolve_stack()

    assert [c.name for c in game.players[0].exile] == ["Grizzly Bears"], game.log
    creatures = [p for p in game.players[0].battlefield if p.has_type("creature")]
    assert len(creatures) == 2, game.log

    game.remove_all_from_battlefield([portcullis])
    game.resolve_stack()

    assert not game.players[0].exile, game.log
    creatures = [p for p in game.players[0].battlefield if p.has_type("creature")]
    assert len(creatures) == 3, game.log
