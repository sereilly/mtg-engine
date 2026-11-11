"""Round kg/seats: a printed "target player" / "target opponent" is announced.

CR 601.2c announces every instance of the word "target", and CR 603.3d does
the same for a triggered ability as it is put on the stack. A seat printed
**inside another slot or a count** was announced by nobody: "Choose target
opponent … Destroy target nonblack creature **that player** controls" (Keeper
of the Dead) left the creature to its handler, "…target cards from **target
player's** graveyard" (Drafna's Restoration, Gaea's Blessing) never held the
player to being a target, and "…the number of … **target opponent** controls"
(Superior Numbers, Reap, Carpet of Flowers) took whichever opponent the
resolution met first. At two seats those agree with the rules by
coincidence; every board here has **three**.

The census at the bottom is the ratchet: every supported announcement of both
manifest roles whose printed line says "target player/opponent" more often
than its derived spec announces a seat — validated backwards against the base
of the round, where it named eleven announcements.
"""
from __future__ import annotations

import re

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.modal_triggers import modal_trigger_mode_spec, modal_trigger_modes
from engine.models import CardDefinition, Permanent
from engine.oracle import compiled_units
from engine.target_descriptions import ANNOUNCED_SEAT
from engine.target_roles import role_is_seat, spec_roles
from engine.targeting import (derive_activation_spec, derive_cast_spec,
                              derive_instruction_spec, spec_offers_a_player)
from tests.helpers import resolve_stack


def _body(name, *, colors=(), power=1, toughness=1):
    return CardDefinition(
        name=name, mana_cost="{1}", cmc=1.0, type_line="Creature — Bear",
        oracle_text="", colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature — Bear", "power": str(power),
             "toughness": str(toughness), "colors": list(colors)},
    )


def _table(boards=((), (), ()), hands=((), (), ()), graveyards=((), (), ()),
           interactive=()):
    """Three seats, seat 0 active in its main phase, nothing summoning-sick."""
    players = []
    for seat in range(3):
        players.append(PlayerState(
            name=f"P{seat}",
            battlefield=[Permanent(card=card) for card in boards[seat]],
            hand=list(hands[seat]), graveyard=list(graveyards[seat]),
            library=[_body(f"L{seat}-{index}") for index in range(6)],
        ))
    for player in players:
        for permanent in player.battlefield:
            permanent.metadata["summoning_sickness_turn"] = -99
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game._settle()
    game.start_turn(0)
    return game


# --- Keeper of the Dead: "that player" is the seat role in front of it --------

def _keeper_table(by_name):
    return _table(
        boards=([by_name["Keeper of the Dead"]], [_body("One")],
                [_body("TwoA"), _body("TwoB", colors=("W",))]),
        graveyards=([_body(f"Dead {index}") for index in range(3)], [], []),
    )


def test_keeper_of_the_dead_offers_each_opponent_with_their_own_creatures(catalog_by_name):
    game = _keeper_table(catalog_by_name)

    spec = game.activation_target_spec(0, 0, 0)

    assert spec["kind"] == "roles"
    offered = {
        entry["seat"]: sorted(option["name"] for option in entry["next"])
        for entry in spec["valid_targets"]
    }
    assert offered == {1: ["One"], 2: ["TwoA", "TwoB"]}


def test_keeper_of_the_dead_destroys_the_creature_the_activator_named(catalog_by_name):
    game = _keeper_table(catalog_by_name)
    two_b = game.players[2].battlefield[1]

    result = game.activate_permanent_ability(
        0, "Keeper of the Dead", permanent_index=0,
        target_role_refs=[{"seat": 2}, {"permanent_id": two_b.permanent_id}],
    )
    resolve_stack(game)

    assert result.supported, result.details
    assert [p.card.name for p in game.players[2].battlefield] == ["TwoA"]


def test_keeper_of_the_dead_refuses_a_creature_another_player_controls(catalog_by_name):
    game = _keeper_table(catalog_by_name)
    keeper = game.players[0].battlefield[0]
    one = game.players[1].battlefield[0]

    result = game.activate_permanent_ability(
        0, "Keeper of the Dead", permanent_index=0,
        target_role_refs=[{"seat": 2}, {"permanent_id": one.permanent_id}],
    )

    assert not result.supported
    assert not keeper.tapped, "refused before the cost was paid"
    assert [p.card.name for p in game.players[1].battlefield] == ["One"]


# --- Superior Numbers: the opponent its count is taken on ---------------------

def _superior_table(by_name):
    return _table(
        boards=([_body(f"M{index}") for index in range(4)],
                [_body("Big", toughness=10), _body("S1a"), _body("S1b")], []),
        hands=([by_name["Superior Numbers"]], [], []),
    )


@pytest.mark.parametrize("named, damage", [(2, 4), (1, 1)])
def test_superior_numbers_counts_the_opponent_the_caster_named(catalog_by_name, named, damage):
    """The 2008-08-01 ruling: "As you cast this, you target a creature and an
    opponent. The opponent does not have to be that creature's controller."
    Four creatures against the named opponent's: seat 2 has none, seat 1
    (whose creature is the target) three."""
    game = _superior_table(catalog_by_name)
    big = game.players[1].battlefield[0]

    result = game.cast_from_hand(0, "Superior Numbers", target_role_refs=[
        {"permanent_id": big.permanent_id}, {"seat": named},
    ])
    resolve_stack(game)

    assert result.supported, result.details
    assert big.damage_marked == damage


def test_superior_numbers_cannot_name_its_caster_as_the_opponent(catalog_by_name):
    game = _superior_table(catalog_by_name)
    big = game.players[1].battlefield[0]

    result = game.cast_from_hand(0, "Superior Numbers", target_role_refs=[
        {"permanent_id": big.permanent_id}, {"seat": 0},
    ])

    assert not result.supported


def test_superior_numbers_deals_nothing_when_its_opponent_goes_illegal(catalog_by_name):
    """CR 608.2b: "If part of the effect requires information about an
    illegal target, it fails to determine any such information." The count is
    that part, so the damage is nothing — not the caster's whole board."""
    game = _superior_table(catalog_by_name)
    big = game.players[1].battlefield[0]
    game.queue_from_hand(0, "Superior Numbers", target_role_refs=[
        {"permanent_id": big.permanent_id}, {"seat": 2},
    ])

    game.players[2].battlefield.append(Permanent(card=catalog_by_name["Ivory Mask"]))
    resolve_stack(game)

    assert big.damage_marked == 0


# --- Carpet of Flowers: a trigger's count-only seat ---------------------------

def _carpet_table(by_name, interactive=()):
    island = by_name["Island"]
    game = _table(
        boards=([by_name["Carpet of Flowers"]], [island], [island, island, island]),
        interactive=interactive,
    )
    # The firing the table's own turn start made, set aside: the test
    # enters the main phase itself.
    game.stack.clear()
    game.pending_choices.clear()
    for player in game.players:
        player.mana_pool.update({symbol: 0 for symbol in player.mana_pool})
    return game


def _pool(game):
    return {symbol: count for symbol, count in game.players[0].mana_pool.items() if count}


def test_carpet_of_flowers_asks_which_opponent_as_it_triggers(catalog_by_name):
    game = _carpet_table(catalog_by_name, interactive=(0,))
    game._enter_main_phase(precombat=True)

    assert [choice.kind for choice in game.pending_choices] == ["trigger_target"]
    assert game.confirm_trigger_target(0, seat=2)
    while game.stack and game.resolve_top_of_stack():
        pass
    assert game.confirm_optional_pay(0, "Carpet of Flowers", accept=True)
    assert game.confirm_mana_color_choice(0, "U")

    assert _pool(game) == {"U": 3}


def test_carpet_of_flowers_unasked_names_the_opponent_its_count_is_best_on(catalog_by_name):
    game = _carpet_table(catalog_by_name)
    game._enter_main_phase(precombat=True)

    assert [item.target_player_index for item in game.stack] == [2]
    while game.stack and game.resolve_top_of_stack():
        pass
    game.auto_resolve_pending_choices()

    assert sum(_pool(game).values()) == 3


# --- A target player's graveyard: the pile's owner is a target ----------------

_TARGET_PLAYER_PILES = (
    "Gaea's Blessing", "Dwell on the Past", "Krosan Reclamation",
    "Drafna's Restoration",
)


def _pile_table(by_name, name, *, masked=False):
    piece = by_name["Ornithopter"]
    return _table(
        boards=([], [], [by_name["Ivory Mask"]] if masked else []),
        hands=([by_name[name]], [], []),
        graveyards=([], [piece], [piece, piece]),
    )


@pytest.mark.parametrize("name", _TARGET_PLAYER_PILES)
def test_a_shrouded_players_graveyard_is_not_offered_or_announceable(catalog_by_name, name):
    """CR 702.18a: a player with shroud can't be the target — so neither can
    the pile "target player's graveyard" names, with or without a card."""
    game = _pile_table(catalog_by_name, name, masked=True)
    card = catalog_by_name[name]

    offered = {entry["seat"] for entry in game.cast_target_spec(0, card)["valid_targets"]}
    with_card = game.cast_from_hand(0, name, target_player_index=2, target_permanent_index=[0])
    without = game.cast_from_hand(0, name, target_player_index=2, target_permanent_index=[])

    assert offered == {1}
    assert not with_card.supported and not without.supported
    assert len(game.players[2].graveyard) == 2


@pytest.mark.parametrize("name", _TARGET_PLAYER_PILES)
def test_a_player_gone_illegal_in_response_has_nothing_moved(catalog_by_name, name):
    """The cards are still legal targets, so the spell resolves; the player is
    not, so "their library" is information it cannot determine (CR 608.2b)."""
    game = _pile_table(catalog_by_name, name)
    game.queue_from_hand(0, name, target_player_index=2, target_permanent_index=[0])

    game.players[2].battlefield.append(Permanent(card=catalog_by_name["Ivory Mask"]))
    resolve_stack(game)

    assert len(game.players[2].graveyard) == 2
    assert any("no longer a legal target (608.2b)" in line for line in game.log), game.log


def test_gaeas_blessing_with_no_card_and_its_player_gone_does_not_resolve(catalog_by_name):
    """Every target illegal — the player, and no card named — and the spell
    is removed from the stack: no card is drawn."""
    game = _pile_table(catalog_by_name, "Gaea's Blessing")
    game.queue_from_hand(0, "Gaea's Blessing", target_player_index=2, target_permanent_index=[])
    hand = len(game.players[0].hand)

    game.players[2].battlefield.append(Permanent(card=catalog_by_name["Ivory Mask"]))
    resolve_stack(game)

    assert len(game.players[0].hand) == hand
    assert any("every target is illegal (608.2b)" in line for line in game.log), game.log


# --- Reap: the opponent its X is counted on -----------------------------------

def _reap_table(by_name, *, masked=False):
    blacks = [_body(f"B{index}", colors=("B",)) for index in range(3)]
    return _table(
        boards=([], [_body("B1", colors=("B",))],
                blacks + ([by_name["Ivory Mask"]] if masked else [])),
        hands=([by_name["Reap"]], [], []),
        graveyards=([_body(f"G{index}") for index in range(4)], [], []),
    )


def _returned(game):
    return sorted(card.name for card in game.players[0].hand if card.name.startswith("G"))


def test_reap_counts_x_on_the_opponent_named(catalog_by_name):
    game = _reap_table(catalog_by_name)

    spec = game.cast_target_spec(0, catalog_by_name["Reap"])
    result = game.cast_from_hand(0, "Reap", target_player_index=2, target_permanent_index=[0, 1, 2])
    resolve_stack(game)

    assert spec["defined_x_by_seat"] == {1: 1, 2: 3}
    assert result.supported, result.details
    assert _returned(game) == ["G0", "G1", "G2"]


@pytest.mark.parametrize("seat", [None, 0])
def test_reap_naming_its_own_pile_or_nobody_counts_the_first_opponent(catalog_by_name, seat):
    """The browser sends the pile's seat — the caster's own, never an opponent
    (CR 102.3) — so that reads as no opponent named, answered once at
    announcement with the first one the description admits."""
    game = _reap_table(catalog_by_name)

    too_many = game.cast_from_hand(0, "Reap", target_player_index=seat, target_permanent_index=[0, 1])
    result = game.cast_from_hand(0, "Reap", target_player_index=seat, target_permanent_index=[0])
    resolve_stack(game)

    assert not too_many.supported, "seat 1 has one black permanent"
    assert result.supported, result.details
    assert _returned(game) == ["G0"]


def test_reap_cannot_name_a_shrouded_opponent(catalog_by_name):
    game = _reap_table(catalog_by_name, masked=True)

    result = game.cast_from_hand(0, "Reap", target_player_index=2, target_permanent_index=[0])

    assert not result.supported
    assert "target player" in result.details


# --- Instigator and Fiery Justice: a seat nobody announced --------------------

def test_instigator_compels_the_creatures_of_the_player_it_targets(catalog_by_name):
    game = _table(
        boards=([catalog_by_name["Instigator"]], [_body("One")], [_body("TwoA")]),
        hands=([_body("Hand")], [], []),
    )

    spec = game.activation_target_spec(0, 0, 0)
    result = game.activate_permanent_ability(
        0, "Instigator", permanent_index=0, target_player_index=2,
    )
    resolve_stack(game)

    assert spec["kind"] == "player"
    assert result.supported, result.details
    assert game.players[2].battlefield[0].metadata.get("must_attack_until_eot") == 1
    assert not game.players[1].battlefield[0].metadata.get("must_attack_until_eot")


def _justice_table(by_name, *, masked=False):
    return _table(
        boards=([], [_body("One")], [_body("Two")] + ([by_name["Ivory Mask"]] if masked else [])),
        hands=([by_name["Fiery Justice"]], [], []),
    )


@pytest.mark.parametrize("named, gainer", [(2, 2), (0, 1), (None, 1)])
def test_fiery_justice_gives_the_life_to_an_opponent(catalog_by_name, named, gainer):
    """"Target opponent gains 5 life" is its own target beside the division.
    Naming the caster (what the browser's default seat was, and an AI seat
    sent) or nobody is answered with the first opponent; it never gave the
    caster the life again."""
    game = _justice_table(catalog_by_name)

    result = game.cast_from_hand(
        0, "Fiery Justice", target_player_index=named, divided_targets=[(1, 0, 5)],
    )
    resolve_stack(game)

    assert result.supported, result.details
    assert [player.life for player in game.players] == [
        25 if seat == gainer else 20 for seat in range(3)
    ]


def test_fiery_justice_with_every_target_gone_does_not_resolve(catalog_by_name):
    """The card's 2017-03-14 ruling: "If all targets become illegal, including
    the target opponent for the life-gaining effect, Fiery Justice doesn't
    resolve.\""""
    game = _justice_table(catalog_by_name)
    one = game.players[1].battlefield[0]
    game.queue_from_hand(
        0, "Fiery Justice", target_player_index=2, divided_targets=[(1, 0, 5)],
    )

    game.players[2].battlefield.append(Permanent(card=catalog_by_name["Ivory Mask"]))
    game.remove_from_battlefield(one)
    resolve_stack(game)

    assert [player.life for player in game.players] == [20, 20, 20]
    assert any("every target is illegal (608.2b)" in line for line in game.log), game.log


def test_dwarven_catapult_divides_among_every_creature_of_the_opponent_named(catalog_by_name):
    """"…divided evenly, rounded down, among all creatures target opponent
    controls." The opponent is the target; the creatures are counted as it
    resolves and share X — none of them is a target the caster picks, so none
    can be left out to take the whole of it."""
    game = _table(
        boards=([], [_body("One", toughness=4)],
                [_body("TwoA", toughness=4), _body("TwoB", toughness=4)]),
        hands=([catalog_by_name["Dwarven Catapult"]], [], []),
    )

    result = game.cast_from_hand(0, "Dwarven Catapult", target_player_index=2, x_value=5)
    resolve_stack(game)

    assert result.supported, result.details
    assert [p.damage_marked for p in game.players[2].battlefield] == [2, 2]
    assert [p.damage_marked for p in game.players[1].battlefield] == [0]


# --- The AI names the opponent by what the count comes to ---------------------

def _ai_table(by_name, boards, hand, graveyards=((), (), ())):
    lands = [by_name[name] for name in ("Swamp", "Swamp", "Forest", "Forest", "Island",
                                        "Island", "Mountain", "Mountain", "Plains", "Plains")]
    game = _table(boards=(list(boards[0]) + lands, *boards[1:]),
                  hands=(hand, [], []), graveyards=graveyards)
    game.players[0].hand = list(hand)
    game.enforce_mana_costs = True
    game.active_player_index = 0
    return game


def test_the_ai_names_the_opponent_reap_counts_most_on(catalog_by_name):
    from engine.ai_policy import choose_cast_action

    game = _ai_table(
        catalog_by_name,
        boards=([], [], [_body(f"B{index}", colors=("B",)) for index in range(3)]),
        hand=[catalog_by_name["Reap"]],
        graveyards=([catalog_by_name[name] for name in ("Hill Giant", "Grizzly Bears", "Craw Wurm")], [], []),
    )

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Reap"
    assert action.target_player_index == 2
    assert len(action.target_graveyard_indices) == 3


def test_the_ai_names_the_opponent_superior_numbers_counts_least_on(catalog_by_name):
    """Aimed at seat 1's 3/3: counted against seat 1's three creatures it
    deals 1, against seat 2's one it deals 3 and kills it."""
    from engine.ai_policy import choose_cast_action

    game = _ai_table(
        catalog_by_name,
        boards=([_body(f"M{index}") for index in range(4)],
                [_body("Mid", power=3, toughness=3), _body("S1a"), _body("S1b")],
                [_body("S2a")]),
        hand=[catalog_by_name["Superior Numbers"]],
    )

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Superior Numbers"
    assert action.target_player_index == 2


# --- The census ---------------------------------------------------------------

_SEAT_WORDS = re.compile(r"\btarget (?:player|opponent)s?\b", re.I)
_TRIGGER_LINE = re.compile(r"^(when|whenever|at the beginning|at end)", re.I)

#: Announcements whose line prints more seat words than their spec announces.
#: Empty since round kg: a new entry is a card a target seat reaches that no
#: announcement carries — the finding this census is for.
_UNANNOUNCED_REMAINDER: set = set()


def _announced_seats(spec) -> int:
    if not spec:
        return 0
    roles = spec_roles(spec)
    if roles:
        seats = sum(1 for role in roles if role_is_seat(role))
    else:
        seats = 1 if spec_offers_a_player(spec) and spec.get("kind") != "divided" else 0
    return seats + (1 if spec.get(ANNOUNCED_SEAT) else 0)


def _spell_text(card) -> str:
    lines = []
    for line in (card.oracle_text or "").split("\n"):
        stripped = re.sub(r"\([^)]*\)", "", line).strip()
        if not stripped or _TRIGGER_LINE.match(stripped):
            continue
        if ":" in stripped.split(".")[0] and "{" in stripped.split(":")[0]:
            continue
        lines.append(stripped)
    return " ".join(lines)


def _announcements(card, program):
    if program.instructions and card.primary_type in ("instant", "sorcery") and not program.modes:
        yield "cast", _spell_text(card), lambda: derive_cast_spec(card, program)
    for index, ability in enumerate(program.activated_abilities):
        if ability.instruction is not None:
            yield (f"act{index}", ability.source_line.split(":", 1)[-1],
                   lambda ability=ability: derive_activation_spec(ability))
    for index, trigger in enumerate(program.triggered_abilities):
        if trigger.instruction is None:
            continue
        modes = modal_trigger_modes(trigger.instruction)
        if modes:
            # "Whenever enchanted artifact becomes tapped, choose one — • This
            # Aura deals 1 damage to target player or planeswalker. • Target
            # player gains 1 life." (Relic Bind.) The mode is chosen and then
            # *that mode's* target (CR 700.2a, 603.3d), so each mode is its own
            # announcement, read off its own label.
            for position, mode in enumerate(modes):
                yield (f"trig{index}.{position}", mode.get("label") or "",
                       lambda mode=mode: modal_trigger_mode_spec(mode))
            continue
        yield (f"trig{index}", trigger.source_line,
               lambda trigger=trigger: derive_instruction_spec([trigger.instruction]))


def test_every_printed_target_seat_is_announced():
    """Over both manifest roles: an announcement printing "target
    player/opponent" announces that many seats — a seat spec, a seat role, or
    a seat beside its own slot (``target_descriptions.ANNOUNCED_SEAT``).

    Validated backwards: run on the round's base (``c42aec75``) it names
    eleven — Drafna's Restoration, Gaea's Blessing, Dwell on the Past, Krosan
    Reclamation, Reap, Superior Numbers, Carpet of Flowers, Instigator, Fiery
    Justice, Dwarven Catapult and Relic Bind — the last read whole there and
    mode by mode here. (Keeper of the Dead announced its seat
    and left its *creature* to the handler: that is the slot half,
    ``test_sequence_target_roles``' seat-and-object ratchet.)"""
    examined = 0
    unannounced = set()
    for card, program in compiled_units(load_cards(manifest_set_paths(include_measured=True))):
        if not program.supported:
            continue
        for label, text, spec_of in _announcements(card, program):
            printed = len(_SEAT_WORDS.findall(re.sub(r"\([^)]*\)", "", text or "")))
            if not printed:
                continue
            examined += 1
            if printed > _announced_seats(spec_of()):
                unannounced.add(f"{card.name}#{label}")

    assert examined >= 250, f"examined {examined} announcements printing a target seat"
    assert unannounced == _UNANNOUNCED_REMAINDER, (
        f"new: {sorted(unannounced - _UNANNOUNCED_REMAINDER)}; "
        f"now announced: {sorted(_UNANNOUNCED_REMAINDER - unannounced)}"
    )
