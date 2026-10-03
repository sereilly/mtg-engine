"""Prophecy lands.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("PCY")` / `set_cards("PCY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W3G1: rhystic cave ---
# W2G1's block stood here: it pinned the *declined* Cave to making no free mana
# through either seam and said to rewrite it when the card landed. Its two
# floors survive below, in `test_w3g1_rhystic_cave_is_never_payment_mana`.
from engine import Game as _W3G1Game, PlayerState as _W3G1PlayerState
from engine.ai_policy import _plan_land_taps as _w3g1_ai_tap_plan
from engine.mana_payment import plan_payment as _w3g1_plan_payment
from engine.mana_payment import untapped_mana_lands as _w3g1_payment_lands
from engine.mana_payment import is_mana_ability as _w3g1_is_mana_ability
from engine.mixins.turn_management import (
    is_tap_alone_mana_ability as _w3g1_seam_runs,
)
from engine.models import Permanent as _W3G1Permanent
from engine.oracle import compile_card_oracle as _w3g1_compile
from tests.helpers import resolve_stack as _w3g1_resolve_stack


def _w3g1_cave_board(set_pool, *, active: int, p1_islands: int = 1, p0_islands: int = 0):
    """Rhystic Cave under seat 0, Islands under each side as asked, on
    *active*'s turn with that seat holding priority. Both seats interactive, so
    every answer in the toll chain is the test's to give."""
    game = _W3G1Game(players=[_W3G1PlayerState(name="P0"), _W3G1PlayerState(name="P1")])
    game.interactive_seats = {0, 1}
    game.start_turn(active)
    game._close_current_priority_step()
    cave = _W3G1Permanent(card=set_pool("PCY")["Rhystic Cave"])
    game._put_permanent_onto_battlefield(0, cave, None)
    for seat, count in ((0, p0_islands), (1, p1_islands)):
        for _ in range(count):
            game._put_permanent_onto_battlefield(
                seat, _W3G1Permanent(card=set_pool("LEA")["Island"]), None
            )
    for land in game.all_permanents():
        land.metadata["summoning_sickness_turn"] = -99
    game.start_priority_window(active)
    return game, cave  # _w3g1_cave_board


def _w3g1_owed(game) -> list[tuple[str, int]]:
    return [(choice.kind, choice.player_index) for choice in game.pending_choices]


def _w3g1_floating(game, seat: int) -> dict[str, int]:
    return {
        symbol: amount
        for symbol, amount in game.players[seat].mana_pool.items() if amount
    }  # _w3g1_floating


def test_w3g1_rhystic_cave_is_a_mana_ability_behind_a_toll(set_pool):
    """"{T}: Choose a color. Add one mana of that color unless any player pays
    {1}. Activate only as an instant." One ability, every sentence read: the
    colour is chosen, the mana sits on the toll's unpaid branch, and it reads
    the colour *this* resolution chose (the scratchpad slot), not a record the
    land never made as it entered. A mana ability (CR 605.1a — "regardless of
    … 'Activate only as an instant'", CR 605.1) even though its mana is behind
    an offer, which is why it never goes on the stack."""
    program = _w3g1_compile(set_pool("PCY")["Rhystic Cave"])
    assert program.supported
    (ability,) = program.activated_abilities
    assert _w3g1_is_mana_ability(ability)
    choose, toll = ability.instruction.payload["steps"]
    assert choose.kind == "choose_color"
    assert toll.kind == "unless_player_pays"
    assert toll.payload["payer"] == "any_player"
    assert toll.payload["cost"] == {"generic": 1}
    (mana,) = toll.payload["unpaid"]
    assert mana.payload == {"color_from": "chosen_color_this_way"}


def test_w3g1_rhystic_cave_mana_arrives_after_every_seat_declines(set_pool):
    """Activated on its controller's own turn with nothing on the stack. The
    toll goes round the table from the active player (CR 101.4) — the
    controller is asked too, since "any player" includes them — and the mana
    arrives only with the last decline. Nothing touches the stack (CR 605.3b),
    and until the last answer the game waits on the offer."""
    game, cave = _w3g1_cave_board(set_pool, active=0)
    result = game.activate_permanent_ability(
        0, "Rhystic Cave", permanent_index=game.battlefield_index_of(cave),
        mana_color="R",
    )
    assert result.supported, result
    assert cave.tapped
    assert not game.stack
    assert _w3g1_floating(game, 0) == {}
    assert _w3g1_owed(game) == [("optional_pay", 0)]
    assert game.waiting_prompt() is not None

    assert game.confirm_optional_pay(0, accept=False)
    assert _w3g1_floating(game, 0) == {}, "one seat declining is not the table declining"
    assert _w3g1_owed(game) == [("optional_pay", 1)]

    assert game.confirm_optional_pay(1, accept=False)
    assert _w3g1_floating(game, 0) == {"R": 1}
    assert game.pending_choices == []
    assert "Rhystic Cave produced {R} (the color chosen)" in game.log


def test_w3g1_any_player_paying_one_denies_the_mana(set_pool):
    """The opponent pays {1} from an untapped Island: no mana, and nobody after
    them is asked (CR 118.12a — the toll is bought off once). The Cave stays
    tapped; its cost was paid when it was activated."""
    game, cave = _w3g1_cave_board(set_pool, active=0, p1_islands=1)
    game.activate_permanent_ability(
        0, "Rhystic Cave", permanent_index=game.battlefield_index_of(cave),
        mana_color="G",
    )
    game.confirm_optional_pay(0, accept=False)
    assert game.confirm_optional_pay(1, accept=True)
    (island,) = game.controlled_by(1)
    assert island.tapped, "the {1} came off the payer's own land"
    assert _w3g1_floating(game, 0) == {}
    assert game.pending_choices == []
    assert cave.tapped
    assert not any("produced" in line for line in game.log if "Rhystic Cave" in line)


def test_w3g1_the_colour_is_asked_before_the_toll_when_none_was_named(set_pool):
    """An activation that names no colour (a client that did not ask) is asked
    as the ability resolves (CR 608.2d), and the toll waits behind it: the
    colour is chosen, *then* the table decides whether to pay — the printed
    order of the two sentences."""
    game, cave = _w3g1_cave_board(set_pool, active=0, p1_islands=0)
    game.activate_permanent_ability(
        0, "Rhystic Cave", permanent_index=game.battlefield_index_of(cave),
    )
    assert _w3g1_owed(game) == [("color_choice", 0)]
    assert game.confirm_color_choice(0, "B")
    assert _w3g1_owed(game) == [("optional_pay", 0)]
    game.confirm_optional_pay(0, accept=False)
    game.confirm_optional_pay(1, accept=False)
    assert _w3g1_floating(game, 0) == {"B": 1}


def test_w3g1_rhystic_cave_answers_a_spell_on_the_opponents_turn(set_pool):
    """"Activate only as an instant": on the opponent's turn, in response to
    their Dark Ritual, with priority (CR 304.5). The toll starts with the
    *active* player — the opponent — and the {R} it makes pays for a Lightning
    Bolt cast on top of the Ritual. The Cave's ability never joined the stack:
    only the two spells resolve."""
    game, cave = _w3g1_cave_board(set_pool, active=1, p1_islands=0)
    game.enforce_mana_costs = True
    swamp = _W3G1Permanent(card=set_pool("LEA")["Swamp"])
    game._put_permanent_onto_battlefield(1, swamp, None)
    game.players[1].hand.append(set_pool("LEA")["Dark Ritual"])
    game.players[0].hand.append(set_pool("LEA")["Lightning Bolt"])
    assert game.tap_land_for_mana(1, "Swamp", "B", permanent_id=swamp.permanent_id)
    assert game.queue_from_hand(1, "Dark Ritual").supported
    assert game.pass_priority(1) == "passed"
    assert game.has_priority(0)

    result = game.queue_permanent_ability(
        0, "Rhystic Cave", permanent_index=game.battlefield_index_of(cave),
        mana_color="R",
    )
    assert result.supported, result
    assert [item.card.name for item in game.stack] == ["Dark Ritual"]
    assert _w3g1_owed(game) == [("optional_pay", 1)], "APNAP: the active player first"
    game.confirm_optional_pay(1, accept=False)
    game.confirm_optional_pay(0, accept=False)
    assert _w3g1_floating(game, 0) == {"R": 1}

    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert _w3g1_floating(game, 0) == {}
    _w3g1_resolve_stack(game)
    assert game.players[1].life == 17
    assert game.players[1].mana_pool["B"] == 3


def test_w3g1_rhystic_cave_needs_priority(set_pool):
    """No priority, no activation (CR 602.5e, CR 304.5) — which is also why it
    can never be tapped part-way through paying a cost (CR 601.2g), when
    nobody has priority. Refused before the cost: the Cave stays untapped."""
    game, cave = _w3g1_cave_board(set_pool, active=1)
    game.start_priority_window(1)
    result = game.activate_permanent_ability(
        0, "Rhystic Cave", permanent_index=game.battlefield_index_of(cave),
        mana_color="R",
    )
    assert not result.supported
    assert "priority" in result.details
    assert not cave.tapped
    assert game.pending_choices == []


def test_w3g1_rhystic_cave_is_never_payment_mana(set_pool):
    """W2G1's floor, now with the card supported: a land whose mana needs
    priority and can be denied is never counted as mana a payment can tap.

    * the payment planner (``untapped_mana_lands`` / ``plan_payment``) does not
      count it — it read Scryfall's WUBRG summary as a free five-colour land;
    * the tap seam refuses it, taps nothing and adds nothing, and the web route
      that asks ``is_tap_alone_mana_ability`` sends a click to the activation
      path instead, which gates it and offers the toll;
    * the AI's tap plan does not count it either.

    The Island beside it is untouched by the rule."""
    game, cave = _w3g1_cave_board(set_pool, active=1, p0_islands=1)
    (island,) = [p for p in game.controlled_by(0) if p is not cave]
    (ability,) = _w3g1_compile(cave.card).activated_abilities
    assert not _w3g1_seam_runs(ability)

    assert _w3g1_payment_lands(game.controlled_by(0)) == [island]
    assert _w3g1_plan_payment({}, _w3g1_payment_lands(game.controlled_by(0)), {"R": 1}) is None
    assert _w3g1_ai_tap_plan(game, game.players[0], {"generic": 2}) is None
    assert _w3g1_ai_tap_plan(game, game.players[0], {"generic": 1}) == (
        (game.battlefield_index_of(island),), ("U",),
    )

    assert game.tap_land_for_mana(0, "Rhystic Cave", "R", permanent_id=cave.permanent_id) is False
    assert not cave.tapped
    assert _w3g1_floating(game, 0) == {}
    assert game.pending_choices == []

    assert game.tap_land_for_mana(0, "Island", "U", permanent_id=island.permanent_id)
    assert _w3g1_floating(game, 0) == {"U": 1}
# end of the W3G1 lands block
