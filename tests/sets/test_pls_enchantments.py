"""Planeshift enchantments.

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

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G7: triggers and cast rules ---
import pytest

from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine.models import CardDefinition as _W1G7Card
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_card(name, type_line, text="", *, cost="{1}", colors=(), pt=None):
    """A fixture card with exactly the printed text a test needs."""
    raw = {"name": name, "type_line": type_line}
    if pt is not None:
        raw["power"], raw["toughness"] = str(pt[0]), str(pt[1])
    made = _W1G7Card(
        name=name, mana_cost=cost, cmc=float(cost.count("{")),
        type_line=type_line, oracle_text=text, colors=tuple(colors),
        color_identity=tuple(colors), keywords=(), produced_mana=(), raw=raw,
    )
    return made


def _w1g7_lands(set_pool, count, name="Swamp"):
    """*count* untapped basics — real ones, so they tap for real mana."""
    land = set_pool("LEA")[name]
    return [_W1G7Permanent(card=land) for _ in range(count)]


def _w1g7_board(mine=(), theirs=(), *, hands=((), ()), interactive=()):
    """Two seats, a library each, costs off — the enchantment under test on
    seat 0 unless the test says otherwise."""
    filler = _w1g7_card("W1G7 Filler", "Creature - Test", pt=(1, 1))
    table = _W1G7Game(players=[
        _W1G7PlayerState(
            name="P1", battlefield=list(mine), hand=list(hands[0]),
            library=[filler] * 8,
        ),
        _W1G7PlayerState(
            name="P2", battlefield=list(theirs), hand=list(hands[1]),
            library=[filler] * 8,
        ),
    ])
    table.enforce_mana_costs = False
    table.interactive_seats = set(interactive)
    return table


# Phyrexian Tyranny — "Whenever a player draws a card, that player loses 2 life
# unless they pay {2}." CR 121.2 makes a draw a per-card event, so a draw-two is
# two triggers and two tolls; "a player" is the third value of the seat axis
# `draws_card` already carried for "you" and "an opponent".


def test_w1g7_phyrexian_tyranny_compiles_as_a_toll_on_any_seats_draw(set_pool):
    program = _w1g7_compile(set_pool("PLS")["Phyrexian Tyranny"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "draws_card"
    assert trigger.condition.payload == {"drawer": "a player"}
    assert trigger.instruction.kind == "may"
    assert trigger.instruction.payload["actor"] == "event_subject_player"
    assert trigger.instruction.payload["cost"] == {"generic": 2}


def test_w1g7_phyrexian_tyranny_costs_the_drawing_opponent_two_life(set_pool):
    tyranny = _W1G7Permanent(card=set_pool("PLS")["Phyrexian Tyranny"])
    table = _w1g7_board([tyranny], [])

    table._draw_with_replacements(table.players[1], 1)
    table.check_state_based_actions()
    _w1g7_resolve_stack(table)
    table.auto_resolve_pending_choices()

    # No land to pay with, so the offer is never made and the toll applies.
    assert [seat.life for seat in table.players] == [20, 18]


def test_w1g7_phyrexian_tyranny_binds_its_own_controller_too(set_pool):
    """"A player" is not "an opponent": the enchantment's controller drawing is
    the event happening to a seat the card names."""
    tyranny = _W1G7Permanent(card=set_pool("PLS")["Phyrexian Tyranny"])
    table = _w1g7_board([tyranny], [])

    table._draw_with_replacements(table.players[0], 1)
    table.check_state_based_actions()
    _w1g7_resolve_stack(table)
    table.auto_resolve_pending_choices()

    assert [seat.life for seat in table.players] == [18, 20]


def test_w1g7_phyrexian_tyranny_is_one_toll_per_card_drawn(set_pool):
    """CR 121.2: drawing two cards is two draws, so two triggers and two
    separate offers — three lands pay for exactly one of them."""
    tyranny = _W1G7Permanent(card=set_pool("PLS")["Phyrexian Tyranny"])
    lands = _w1g7_lands(set_pool, 3)
    table = _w1g7_board([tyranny], lands, interactive={1})

    table._draw_with_replacements(table.players[1], 2)
    table.check_state_based_actions()
    assert [item.card.name for item in table.stack] == ["Phyrexian Tyranny"] * 2

    table.resolve_top_of_stack(pause_for_choices=True)
    (offer,) = table.pending_choices
    assert (offer.kind, offer.player_index) == ("optional_pay", 1), (
        "the drawing player is the payer, not the enchantment's controller"
    )
    assert table.confirm_optional_pay(1, accept=True)
    assert table.players[1].life == 20
    assert sum(land.tapped for land in lands) == 2

    # The second toll: one untapped land cannot cover {2}, so it is not offered.
    table.resolve_top_of_stack(pause_for_choices=True)
    assert table.pending_choices == []
    assert table.players[1].life == 18
    assert not table.stack


def test_w1g7_phyrexian_tyranny_a_declined_toll_loses_the_life(set_pool):
    tyranny = _W1G7Permanent(card=set_pool("PLS")["Phyrexian Tyranny"])
    lands = _w1g7_lands(set_pool, 2)
    table = _w1g7_board([tyranny], lands, interactive={1})

    table._draw_with_replacements(table.players[1], 1)
    table.check_state_based_actions()
    table.resolve_top_of_stack(pause_for_choices=True)
    assert table.confirm_optional_pay(1, accept=False)

    assert table.players[1].life == 18
    assert not any(land.tapped for land in lands)


def test_w1g7_phyrexian_tyranny_fires_in_the_draw_step_that_drew(set_pool):
    """CR 504.2 with CR 603.3: the turn-based draw's trigger goes on the stack
    before the active player's draw-step priority, not a phase later. The
    headless turn resolves it inside the step, so the toll is already settled
    when the main phase begins."""
    tyranny = _W1G7Permanent(card=set_pool("PLS")["Phyrexian Tyranny"])
    table = _w1g7_board([tyranny], [])
    table.turn = 2

    table.begin_turn_bookkeeping(1)
    table.resolve_untap_step(1)
    table.resolve_upkeep(1)
    table.resolve_draw_step(1)
    table.auto_resolve_pending_choices()

    assert table.current_step == "draw"
    assert table.players[1].life == 18


# Cloud Cover — "Whenever another permanent you control becomes the target of a
# spell or ability an opponent controls, you may return that permanent to its
# owner's hand." Cowardice's board-wide scope with three printed narrowings —
# "another", "you control", "an opponent controls" — and each has a test that
# fails if it is dropped.


def _w1g7_cloud_table(*, hands=((), ()), interactive=(0,)):
    cloud = _W1G7Permanent(card=_w1g7_cloud_table.pool["Cloud Cover"])
    mine = _W1G7Permanent(card=_w1g7_card("W1G7 Mine", "Creature - Test", pt=(2, 2)))
    theirs = _W1G7Permanent(
        card=_w1g7_card("W1G7 Theirs", "Creature - Test", pt=(2, 2))
    )
    table = _w1g7_board(
        [cloud, mine], [theirs], hands=hands, interactive=interactive
    )
    return table, cloud, mine, theirs


def _w1g7_zap():
    return _w1g7_card(
        "W1G7 Zap", "Instant", "W1G7 Zap deals 2 damage to target creature.",
        cost="{R}", colors=("R",),
    )


def _w1g7_unmake():
    return _w1g7_card(
        "W1G7 Unmake", "Instant", "Destroy target enchantment.",
        cost="{W}", colors=("W",),
    )


@pytest.fixture
def _w1g7_cloud(set_pool):
    _w1g7_cloud_table.pool = set_pool("PLS")
    return _w1g7_cloud_table


def test_w1g7_cloud_cover_compiles_with_all_three_narrowings(set_pool):
    program = _w1g7_compile(set_pool("PLS")["Cloud Cover"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "self_becomes_target"
    assert trigger.condition.payload == {
        "targeted_by": "a spell or ability",
        "targeting_controller": "an opponent controls",
        "targeted_filter": {"controller": "you", "exclude_self": True},
    }
    assert trigger.instruction.kind == "may"
    assert [step.kind for step in trigger.instruction.payload["action"]] == [
        "bounce_event_subject"
    ]


def test_w1g7_cloud_cover_saves_a_creature_an_opponent_targeted(_w1g7_cloud):
    table, _cloud, mine, _theirs = _w1g7_cloud(hands=((), (_w1g7_zap(),)))

    table.cast_from_hand(1, "W1G7 Zap", target_permanent_ids=[mine.permanent_id])
    (offer,) = table.pending_choices
    assert (offer.kind, offer.player_index) == ("optional_pay", 0)
    assert table.confirm_optional_pay(0, accept=True)
    _w1g7_resolve_stack(table)

    assert [card.name for card in table.players[0].hand] == ["W1G7 Mine"]
    assert not table.is_on_battlefield(mine)
    # CR 608.2b: the spell found its only target gone.
    assert any("every target is illegal" in line for line in table.log)


def test_w1g7_cloud_cover_is_a_may_and_declining_lets_the_spell_resolve(_w1g7_cloud):
    table, _cloud, mine, _theirs = _w1g7_cloud(hands=((), (_w1g7_zap(),)))

    table.cast_from_hand(1, "W1G7 Zap", target_permanent_ids=[mine.permanent_id])
    assert table.confirm_optional_pay(0, accept=False)
    _w1g7_resolve_stack(table)

    assert table.players[0].hand == []
    assert mine.damage_marked == 2 or not table.is_on_battlefield(mine)


def test_w1g7_cloud_cover_ignores_its_own_controllers_spells(_w1g7_cloud):
    """"…a spell or ability **an opponent controls**"."""
    table, _cloud, mine, _theirs = _w1g7_cloud(hands=((_w1g7_zap(),), ()))

    table.cast_from_hand(0, "W1G7 Zap", target_permanent_ids=[mine.permanent_id])

    assert table.pending_choices == []
    assert table.players[0].hand == []


def test_w1g7_cloud_cover_does_not_watch_itself(_w1g7_cloud):
    """"**Another** permanent you control" — CR 109.2's "not this object"."""
    table, cloud, _mine, _theirs = _w1g7_cloud(hands=((), (_w1g7_unmake(),)))

    table.cast_from_hand(
        1, "W1G7 Unmake", target_permanent_ids=[cloud.permanent_id]
    )
    _w1g7_resolve_stack(table)

    assert table.pending_choices == []
    assert [card.name for card in table.players[0].graveyard] == ["Cloud Cover"]
    assert table.players[0].hand == []


def test_w1g7_cloud_cover_does_not_watch_an_opponents_permanents(_w1g7_cloud):
    """"…permanent **you control**"."""
    table, _cloud, _mine, theirs = _w1g7_cloud(hands=((), (_w1g7_zap(),)))

    table.cast_from_hand(1, "W1G7 Zap", target_permanent_ids=[theirs.permanent_id])

    assert table.pending_choices == []
    assert table.players[1].hand == []


def test_w1g7_cloud_cover_watches_an_opponents_ability_and_any_permanent(
    _w1g7_cloud, set_pool
):
    """"A spell **or ability**", and "**permanent**" rather than "creature":
    an opponent's activated ability aimed at a land fires it too."""
    table, _cloud, _mine, _theirs = _w1g7_cloud()
    forest = _W1G7Permanent(card=set_pool("LEA")["Forest"])
    table.players[0].battlefield.append(forest)
    table._initialize_permanent_state(forest, 0, 1)
    icy = _W1G7Permanent(card=_w1g7_card(
        "W1G7 Icy", "Artifact", "{T}: Tap target land.", cost="{4}",
    ))
    table.players[1].battlefield.append(icy)
    table._initialize_permanent_state(icy, 1, 0)

    assert table.activate_permanent_ability(
        1, "W1G7 Icy", target_permanent_ids=[forest.permanent_id]
    ).supported
    assert [c.kind for c in table.pending_choices] == ["optional_pay"]
    assert table.confirm_optional_pay(0, accept=True)
    _w1g7_resolve_stack(table)

    assert [card.name for card in table.players[0].hand] == ["Forest"]


# Warped Devotion — "Whenever a permanent is returned to a player's hand, that
# player discards a card." A zone change with both ends named, announced from
# `Game.put_card_into_hand` — the one seam handed the hand it is going to and,
# as `from_battlefield`, the permanent it is the card of.


def _w1g7_devotion_table(set_pool, *, mine=(), theirs=(), hands=((), ())):
    devotion = _W1G7Permanent(card=set_pool("PLS")["Warped Devotion"])
    table = _w1g7_board([devotion, *mine], list(theirs), hands=hands)
    return table, devotion


def _w1g7_settle(table):
    """Drain the stack and take every default the drained objects armed."""
    for _ in range(8):
        _w1g7_resolve_stack(table)
        if not table.pending_choices:
            return
        table.auto_resolve_pending_choices()
    raise AssertionError("the table did not settle")


def _w1g7_names(cards):
    return sorted(getattr(card, "name", None) or card.card.name for card in cards)


def test_w1g7_warped_devotion_compiles_onto_the_zone_change(set_pool):
    program = _w1g7_compile(set_pool("PLS")["Warped Devotion"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "permanent_returned_to_hand"
    assert trigger.condition.payload == {"returned_filter": {}}
    assert trigger.instruction.kind == "discard_target_cards"
    # "That player" is the seat the move froze, not a seat anybody targeted.
    assert trigger.instruction.payload == {
        "amount": 1, "who": "event_subject_player",
    }


def test_w1g7_warped_devotion_makes_the_bounced_permanents_owner_discard(set_pool):
    """Seat 1 bounces seat 0's creature: the hand it reaches is seat 0's, so
    seat 0 discards — not the player who cast the bounce, and not "the
    opponent of the enchantment's controller", which is the seat a targetless
    resolution defaults to and the one this card used to take the card from."""
    lea = set_pool("LEA")
    mine = _W1G7Permanent(card=_w1g7_card("W1G7 Mine", "Creature - Test", pt=(2, 2)))
    table, _devotion = _w1g7_devotion_table(
        set_pool, mine=[mine],
        hands=((lea["Forest"],), (lea["Unsummon"], lea["Swamp"])),
    )

    assert table.cast_from_hand(
        1, "Unsummon", target_permanent_ids=[mine.permanent_id]
    ).supported
    _w1g7_settle(table)

    assert len(table.players[0].hand) == 1, "one card arrived and one went"
    assert len(table.players[0].graveyard) == 1
    assert _w1g7_names(table.players[1].hand) == ["Swamp"]
    assert _w1g7_names(table.players[1].graveyard) == ["Unsummon"]


def test_w1g7_warped_devotion_follows_the_owner_whoever_did_the_bouncing(set_pool):
    lea = set_pool("LEA")
    theirs = _W1G7Permanent(
        card=_w1g7_card("W1G7 Theirs", "Creature - Test", pt=(2, 2))
    )
    table, _devotion = _w1g7_devotion_table(
        set_pool, theirs=[theirs],
        hands=((lea["Unsummon"], lea["Forest"]), (lea["Swamp"],)),
    )

    table.cast_from_hand(0, "Unsummon", target_permanent_ids=[theirs.permanent_id])
    _w1g7_settle(table)

    assert _w1g7_names(table.players[0].hand) == ["Forest"]
    assert len(table.players[1].hand) == 1 and len(table.players[1].graveyard) == 1


def test_w1g7_warped_devotion_ignores_a_card_that_was_never_a_permanent(set_pool):
    """A draw and a return from a graveyard both put a card into a hand and
    return no *permanent* — the narrowing "a permanent is returned" is."""
    lea = set_pool("LEA")
    table, _devotion = _w1g7_devotion_table(
        set_pool, hands=((lea["Raise Dead"], lea["Forest"]), (lea["Swamp"],)),
    )
    table.players[0].graveyard.append(lea["Grizzly Bears"])

    assert table.cast_from_hand(0, "Raise Dead", target_permanent_index=0).supported
    _w1g7_settle(table)
    table._draw_with_replacements(table.players[1], 1)
    table.check_state_based_actions()
    _w1g7_settle(table)

    assert _w1g7_names(table.players[0].hand) == ["Forest", "Grizzly Bears"]
    assert _w1g7_names(table.players[0].graveyard) == ["Raise Dead"]
    assert table.players[1].graveyard == []


def test_w1g7_warped_devotion_fires_for_a_token_that_is_bounced(set_pool):
    """CR 111.7: "if a token changes zones, applicable triggered abilities will
    trigger before the token ceases to exist." The token is returned to its
    owner's hand — and then is no card anywhere — so its owner discards."""
    from engine.tokens import make_token_card

    lea = set_pool("LEA")
    token = _W1G7Permanent(card=make_token_card(
        "Saproling", 1, 1, "Token Creature - Saproling", colors=("G",),
    ))
    table, _devotion = _w1g7_devotion_table(
        set_pool, theirs=[token], hands=((lea["Unsummon"],), (lea["Swamp"],)),
    )
    table._initialize_permanent_state(token, 1, 0)

    table.cast_from_hand(0, "Unsummon", target_permanent_ids=[token.permanent_id])
    _w1g7_settle(table)

    assert table.players[1].hand == [], "the token is not a card in a hand"
    assert _w1g7_names(table.players[1].graveyard) == ["Swamp"]
    assert not table.is_on_battlefield(token)


def test_w1g7_warped_devotion_sees_itself_returned(set_pool):
    """CR 603.10a: an ability that triggers when an object all players can see
    is put into a hand looks back in time, so the enchantment bounced by the
    effect is still there to see itself go."""
    lea = set_pool("LEA")
    table, devotion = _w1g7_devotion_table(
        set_pool, hands=((lea["Forest"],), (set_pool("LEG")["Boomerang"],)),
    )

    table.cast_from_hand(1, "Boomerang", target_permanent_ids=[devotion.permanent_id])
    _w1g7_settle(table)

    assert _w1g7_names(table.players[0].graveyard) == ["Forest"]
    assert _w1g7_names(table.players[0].hand) == ["Warped Devotion"]


def test_w1g7_warped_devotion_triggers_once_per_permanent_in_a_sweep(set_pool):
    """One trigger per permanent returned (CR 603.2c: an event containing
    several occurrences triggers once for each)."""
    lea, forest = set_pool("LEA"), set_pool("LEA")["Forest"]
    evacuation = next(
        set_pool(code)["Evacuation"]
        for code in ("STH", "5ED", "6ED", "TMP", "INV")
        if "Evacuation" in set_pool(code)
    )
    mine = [
        _W1G7Permanent(card=_w1g7_card(f"W1G7 Mine {n}", "Creature - Test", pt=(1, 1)))
        for n in (1, 2)
    ]
    theirs = [
        _W1G7Permanent(card=_w1g7_card("W1G7 Theirs", "Creature - Test", pt=(1, 1)))
    ]
    table, _devotion = _w1g7_devotion_table(
        set_pool, mine=mine, theirs=theirs,
        hands=((evacuation, forest, forest, forest), (lea["Swamp"], lea["Swamp"])),
    )

    assert table.cast_from_hand(0, "Evacuation").supported
    _w1g7_settle(table)

    # Seat 0: three Forests and two returned creatures in, two discards out.
    assert len(table.players[0].hand) == 3
    assert len(table.players[0].graveyard) == 3  # Evacuation + two discards
    # Seat 1: two Swamps and one returned creature in, one discard out.
    assert len(table.players[1].hand) == 2
    assert len(table.players[1].graveyard) == 1


def test_w1g7_warped_devotion_costs_a_gating_creature_a_card(set_pool):
    """Gating ("When this creature enters, return a red or green creature you
    control to its owner's hand") under Warped Devotion: the return is a
    permanent returned to a hand, so the gater's controller discards."""
    lea, pls = set_pool("LEA"), set_pool("PLS")
    gater = pls["Horned Kavu"]
    assert _w1g7_compile(gater).supported
    host = _W1G7Permanent(card=_w1g7_card(
        "W1G7 Red Host", "Creature - Test", pt=(2, 2), colors=("R",), cost="{R}",
    ))
    table, _devotion = _w1g7_devotion_table(
        set_pool, mine=[host], hands=((gater, lea["Forest"]), ()),
    )

    assert table.cast_from_hand(0, "Horned Kavu").supported
    _w1g7_settle(table)

    hand = _w1g7_names(table.players[0].hand)
    # Gating returned one of the two red-or-green creatures (the Kavu may
    # return itself); either way exactly one card came back and one was
    # discarded, so the hand is still one card and the graveyard holds one.
    assert len(hand) == 1, hand
    assert len(table.players[0].graveyard) == 1
    assert any("must choose 1 card(s) to discard" in line for line in table.log)


def test_w1g7_warped_devotion_with_sunken_hope_is_a_discard_every_upkeep(set_pool):
    """Sunken Hope ("each player's upkeep, that player returns a creature they
    control to its owner's hand") beside Warped Devotion: the active player
    bounces a creature and then discards."""
    lea = set_pool("LEA")
    hope = _W1G7Permanent(card=set_pool("PLS")["Sunken Hope"])
    theirs = _W1G7Permanent(
        card=_w1g7_card("W1G7 Theirs", "Creature - Test", pt=(2, 2))
    )
    table, _devotion = _w1g7_devotion_table(
        set_pool, mine=[hope], theirs=[theirs],
        hands=((lea["Forest"],), (lea["Swamp"],)),
    )
    table.turn = 2

    table.begin_turn_bookkeeping(1)
    table.resolve_untap_step(1)
    table.resolve_upkeep(1)
    _w1g7_settle(table)

    assert not table.is_on_battlefield(theirs)
    assert len(table.players[1].hand) == 1 and len(table.players[1].graveyard) == 1
    assert _w1g7_names(table.players[0].hand) == ["Forest"]


def test_w1g7_a_narrower_returned_subject_is_enforced():
    """The noun phrase is data: "a **creature** is returned to a player's hand"
    is the same row with a filter, and the filter is tested — an enchantment
    bounced past it discards nothing."""
    watcher = _W1G7Permanent(card=_w1g7_card(
        "W1G7 Watcher", "Enchantment",
        "Whenever a creature is returned to a player's hand, that player "
        "discards a card.",
    ))
    rock = _W1G7Permanent(card=_w1g7_card("W1G7 Rock", "Artifact", cost="{2}"))
    bear = _W1G7Permanent(card=_w1g7_card("W1G7 Bear", "Creature - Test", pt=(2, 2)))
    filler = _w1g7_card("W1G7 Card", "Sorcery", "Draw a card.")
    table = _w1g7_board([watcher], [rock, bear], hands=((), (filler, filler)))
    program = _w1g7_compile(watcher.card)
    assert program.supported, program.reason

    table.put_card_into_hand(table.players[1], rock.card, from_battlefield=rock)
    table.remove_from_battlefield(rock)
    _w1g7_settle(table)
    assert table.players[1].graveyard == []

    table.put_card_into_hand(table.players[1], bear.card, from_battlefield=bear)
    table.remove_from_battlefield(bear)
    _w1g7_settle(table)
    assert len(table.players[1].graveyard) == 1


# Keldon Twilight — "At the beginning of each player's end step, if no
# creatures attacked this turn, that player sacrifices a creature of their
# choice that they controlled since the beginning of the turn." Three pieces
# that each already had a neighbour: the per-player end step (Monsoon), a
# turn-wide attack record read as CR 603.4's intervening-if, and CR 302.6's
# clock as a narrowing on the forced-sacrifice prompt.


def _w1g7_twilight_table(set_pool, *, mine=("W1G7 Mine",), theirs=("W1G7 Theirs",),
                         interactive=()):
    twilight = _W1G7Permanent(card=set_pool("PLS")["Keldon Twilight"])
    ours = [
        _W1G7Permanent(card=_w1g7_card(name, "Creature - Test", pt=(2, 2)))
        for name in mine
    ]
    others = [
        _W1G7Permanent(card=_w1g7_card(name, "Creature - Test", pt=(2, 2)))
        for name in theirs
    ]
    table = _w1g7_board([twilight, *ours], others, interactive=interactive)
    table.turn = 4
    return table, ours, others


def _w1g7_to_end_step(table, seat, *, begin=True):
    """Run *seat*'s turn to the beginning of its end step, attacking with
    nobody; the end-step triggers are on the stack when this returns."""
    if begin:
        table.start_turn(seat)
    table._close_current_priority_step()
    for _ in range(12):
        if table.current_turn_phase == "ending":
            return
        table.enter_next_turn_phase()
    raise AssertionError("the turn never reached its ending phase")


def test_w1g7_keldon_twilight_compiles_with_its_gate_and_its_narrowing(set_pool):
    program = _w1g7_compile(set_pool("PLS")["Keldon Twilight"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "end_step"
    assert trigger.instruction.kind == "sacrifice_matching_permanent"
    assert trigger.instruction.payload == {
        "filter": {"type_filter": "creature", "controlled_since_turn_start": True},
        "who": "event_subject_player",
        "intervening_if": {"kind": "creatures_attacked_this_turn", "negated": True},
    }


def test_w1g7_keldon_twilight_takes_a_creature_from_the_player_whose_end_step_it_is(
    set_pool,
):
    table, ours, others = _w1g7_twilight_table(set_pool)

    _w1g7_to_end_step(table, 1)
    assert [item.card.name for item in table.stack] == ["Keldon Twilight"]
    _w1g7_settle(table)

    # "That player" is the active one — the opponent here, not the
    # enchantment's controller.
    assert not table.is_on_battlefield(others[0])
    assert table.is_on_battlefield(ours[0])


def test_w1g7_keldon_twilight_binds_its_own_controller_on_their_turn(set_pool):
    table, ours, others = _w1g7_twilight_table(set_pool)

    _w1g7_to_end_step(table, 0)
    _w1g7_settle(table)

    assert not table.is_on_battlefield(ours[0])
    assert table.is_on_battlefield(others[0])


def test_w1g7_keldon_twilight_does_not_trigger_on_a_turn_a_creature_attacked(set_pool):
    """CR 603.4: an intervening-if that is false means the ability does not
    trigger at all — nothing goes on the stack. The record is the seat's, so an
    attacker that has since left the battlefield still attacked."""
    table, _ours, others = _w1g7_twilight_table(set_pool)
    table.start_turn(1)
    table._close_current_priority_step()
    table.advance_combat_phase()
    table.advance_combat_phase()
    assert table.declare_attackers(1, [0])[0]
    table.remove_from_battlefield(others[0])  # the attacker is gone …
    assert table.players[1].attacked_this_turn  # … and still attacked

    for _ in range(12):
        if table.current_turn_phase == "ending":
            break
        table.enter_next_turn_phase()

    assert table.current_turn_phase == "ending"
    assert table.stack == []


def test_w1g7_keldon_twilight_spares_a_creature_that_arrived_this_turn(set_pool):
    """"…that they controlled since the beginning of the turn". A creature cast
    this turn is not one, so a player holding only that one sacrifices
    nothing — and with an older creature beside it, only the older is offered."""
    fresh = _w1g7_card("W1G7 Fresh", "Creature - Test", pt=(2, 2))
    table, _ours, _others = _w1g7_twilight_table(set_pool, theirs=())
    table.players[1].hand.append(fresh)
    table.start_turn(1)
    assert table.cast_from_hand(1, "W1G7 Fresh").supported
    _w1g7_settle(table)

    _w1g7_to_end_step(table, 1, begin=False)
    _w1g7_settle(table)

    assert _w1g7_names(table.controlled_by(1)) == ["W1G7 Fresh"]
    assert table.players[1].graveyard == []


def test_w1g7_keldon_twilight_offers_only_the_creatures_it_names(set_pool):
    fresh = _w1g7_card("W1G7 Fresh", "Creature - Test", pt=(2, 2))
    table, _ours, others = _w1g7_twilight_table(
        set_pool, theirs=("W1G7 Old",), interactive={1},
    )
    table.players[1].hand.append(fresh)
    table.start_turn(1)
    table.cast_from_hand(1, "W1G7 Fresh")
    table.resolve_stack(pause_for_choices=True)

    _w1g7_to_end_step(table, 1, begin=False)
    table.resolve_top_of_stack(pause_for_choices=True)

    (owed,) = table.pending_choices
    assert (owed.kind, owed.player_index) == ("sacrifice", 1)
    offered = table._sacrifice_candidate_indices(
        table.players[1], owed.data["filter"]
    )
    assert [table.players[1].battlefield[i].card.name for i in offered] == [
        "W1G7 Old"
    ]
    assert others[0].card.name == "W1G7 Old"


# Phyrexian Tyranny and the seat nobody asks. "Pay tolls, always" answered this
# card by tapping two lands in every draw step for the rest of the game, so a
# toll whose whole penalty is a little life is priced against the lands on the
# seat's own turn (`ai_policy.optional_pay_may_tap_lands`).


def _w1g7_tyranny_draw_step(set_pool, *, life, hand):
    """Seat 1 (three Forests, *hand*, *life*) takes its draw step under seat
    0's Tyranny with mana costs enforced, and answers the toll by default."""
    lea = set_pool("LEA")
    tyranny = _W1G7Permanent(card=set_pool("PLS")["Phyrexian Tyranny"])
    lands = _w1g7_lands(set_pool, 3, "Forest")
    table = _w1g7_board(
        [tyranny], lands, hands=((), tuple(lea[name] for name in hand)),
    )
    table.enforce_mana_costs = True
    table.players[1].life = life
    # The draw itself is a land, so what the seat could cast afterwards is
    # exactly the *hand* the test handed it.
    table.players[1].library = [lea["Forest"]] * 6
    table.turn = 2

    table.begin_turn_bookkeeping(1)
    table.resolve_untap_step(1)
    table.resolve_upkeep(1)
    table.resolve_draw_step(1)
    table.auto_resolve_pending_choices()
    return table, lands


def test_w1g7_a_healthy_seat_keeps_its_lands_for_the_spell_in_its_hand(set_pool):
    table, lands = _w1g7_tyranny_draw_step(
        set_pool, life=20, hand=("Grizzly Bears",)
    )

    assert table.players[1].life == 18
    assert not any(land.tapped for land in lands)


def test_w1g7_a_seat_with_nothing_to_cast_pays_the_toll(set_pool):
    """The mana would sit idle, so the life is the dearer price even at 20."""
    table, lands = _w1g7_tyranny_draw_step(set_pool, life=20, hand=())

    assert table.players[1].life == 20
    assert sum(land.tapped for land in lands) == 2


def test_w1g7_a_seat_low_on_life_pays_even_holding_a_spell(set_pool):
    """Declining would leave it under `LIFE_TOLL_FLOOR`."""
    from engine.ai_policy import LIFE_TOLL_FLOOR

    table, lands = _w1g7_tyranny_draw_step(
        set_pool, life=LIFE_TOLL_FLOOR + 1, hand=("Grizzly Bears",)
    )

    assert table.players[1].life == LIFE_TOLL_FLOOR + 1
    assert sum(land.tapped for land in lands) == 2


def test_w1g7_a_toll_off_its_own_turn_is_still_paid(set_pool):
    """On another seat's turn the lands are idle until the untap step, so the
    standing answer stands: pay."""
    lea = set_pool("LEA")
    tyranny = _W1G7Permanent(card=set_pool("PLS")["Phyrexian Tyranny"])
    lands = _w1g7_lands(set_pool, 3, "Forest")
    table = _w1g7_board([tyranny], lands, hands=((), (lea["Grizzly Bears"],)))
    table.enforce_mana_costs = True
    table.active_player_index = 0

    table._draw_with_replacements(table.players[1], 1)
    table.check_state_based_actions()
    _w1g7_resolve_stack(table)
    table.auto_resolve_pending_choices()

    assert table.players[1].life == 20
    assert sum(land.tapped for land in lands) == 2
