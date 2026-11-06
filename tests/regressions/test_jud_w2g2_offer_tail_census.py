"""Census: the steps written behind an offer wait for its answer.

Judgment's wave 1 (W1G5) found Grip of Amnesia drawing its card before the
counter was decided: "Counter target spell unless its controller exiles all
cards from their graveyard. Draw a card." An ``optional_pay`` did not
suspend the loop it was a step of, so on the interactive path everything
written after a "you may …" / "… unless …" ran before the seat had answered.
CR 608.2c: the controller of a spell or ability follows its instructions in
the order written; CR 117.3b: nobody receives priority until the resolution
is over. The offer is one of those instructions.

So the census is over **every compiled program in the pool**, both manifest
roles: every loop in which a step that can arm an offer is followed by
another step. Each such site is run — the steps up to and including the
offer, then a probe where the rest of the loop would be — under interactive
seats, and asked whether the probe ran before the offer was answered. On the
tree W1G5 measured it ran early at every site the board reached (twelve, on
twelve cards); it runs once, after the answer, now.

The cards themselves are driven below on the real cast path, and the one new
interaction the suspension makes possible — a mana ability activated while an
offer is owed, which is how an offer priced in mana is paid (CR 605.3a) — is
driven too.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.game_types import OracleExecutionContext
from engine.handlers import EFFECT_HANDLERS
from engine.models import Permanent
from engine.oracle import OracleInstruction, compiled_units
from tests.helpers import resolve_stack

#: Every effect handler that arms an ``optional_pay`` (read off the handlers'
#: source: each calls ``arm_pending_choice("optional_pay", …)``).
_OFFER_KINDS = frozenset({
    "may", "unless_player_pays", "self_damage_unless_pay",
    "exchange_ownership_unless_paid", "ante_or_exchange_ownership",
    "random_reveal_ownership_exchange", "discard_revealed_unless_pay_life",
    "discard_revealed_matching_unless_pay_life", "transmute_by_sacrifice",
})
#: A step whose nested instructions run later, not in this resolution.
_DEFERRED_KINDS = frozenset({"create_delayed_trigger"})

#: The sites the census must find, and how many of them its board must reach.
#: Fourteen sites over fourteen cards at the time of writing; twelve reached
#: (Wand of Ith's offer waits on a random land reveal, Winter's Chill's on an
#: attacking creature it chose).
_SITES_FLOOR = 12
_REACHED_FLOOR = 10

_PROBE = "census_offer_tail_probe"


def _pool() -> dict:
    pool: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    return pool


_POOL = _pool()


def _contains_offer(step: OracleInstruction) -> bool:
    if step.kind in _OFFER_KINDS:
        return True
    if step.kind in _DEFERRED_KINDS:
        return False

    def walk(value) -> bool:
        if isinstance(value, OracleInstruction):
            return _contains_offer(value)
        if isinstance(value, (tuple, list)):
            return any(walk(v) for v in value)
        if isinstance(value, dict):
            return any(walk(v) for v in value.values())
        return False

    return walk(step.payload or {})


def _loops_in(value):
    """Every tuple of instructions a ``_run`` loop walks, anywhere in *value*."""
    if isinstance(value, OracleInstruction):
        for sub in (value.payload or {}).values():
            yield from _loops_in(sub)
    elif isinstance(value, (tuple, list)):
        if value and all(isinstance(v, OracleInstruction) for v in value):
            yield tuple(value)
        for v in value:
            yield from _loops_in(v)
    elif isinstance(value, dict):
        for sub in value.values():
            yield from _loops_in(sub)


def _is_spell(card) -> bool:
    return "Instant" in card.type_line or "Sorcery" in card.type_line


def _sites():
    """(card, unit, the steps before the offer, the offer) for every loop in
    which an offer has a step behind it. A permanent's ``instructions`` is a
    mirror of its lines, not a program, so only an instant's or sorcery's is
    read as one (``_select_executable_instruction``)."""
    sites = []
    for card, program in compiled_units(_POOL.values()):
        if not program.supported:
            continue
        units = []
        if program.instructions and _is_spell(card):
            units.append(("spell", tuple(
                step for step in program.instructions if step.kind != "spell_pattern"
            )))
        for index, ability in enumerate(program.activated_abilities):
            if ability.supported and ability.instruction is not None:
                units.append((f"activated[{index}]", (ability.instruction,)))
        for index, ability in enumerate(program.triggered_abilities):
            if ability.supported and ability.instruction is not None:
                units.append((f"triggered[{index}]", (ability.instruction,)))
        for unit, top in units:
            for steps in _loops_in(list(top)):
                for index, step in enumerate(steps[:-1]):
                    if _contains_offer(step):
                        sites.append((card, unit, steps[:index], step))
    return sites


def _board() -> Game:
    names = (
        "Grizzly Bears", "Hill Giant", "Ornithopter", "Lightning Bolt",
        "Counterspell", "Divine Offering", "Disenchant", "Serra Angel",
        "Stone Rain", "Forest", "Island", "Mountain", "Swamp", "Plains",
    )
    cards = [_POOL[name] for name in names]

    def player(name: str) -> PlayerState:
        return PlayerState(
            name, library=list(cards) * 2, hand=list(cards), graveyard=list(cards),
        )

    game = Game(players=[player("P1"), player("P2")])
    game.enforce_mana_costs = False
    for seat in (0, 1):
        game.players[seat].sideboard = list(cards)
        for land in ("Forest", "Island", "Mountain", "Swamp", "Plains") * 2:
            game._put_permanent_onto_battlefield(seat, Permanent(card=_POOL[land]), None)
        for name in ("Grizzly Bears", "Hill Giant", "Ornithopter"):
            creature = Permanent(card=_POOL[name])
            creature.metadata["summoning_sickness_turn"] = -99
            game._put_permanent_onto_battlefield(seat, creature, None)
    game.interactive_seats = {0, 1}
    game.start_turn(0)
    game.stack.clear()
    game.pending_choices.clear()
    return game


def _owed_offers(game) -> list:
    return [
        choice for choice in game.pending_choices
        if choice.kind == "optional_pay" and not choice.data.get("_answered")
    ]


def test_every_step_behind_an_offer_waits_for_its_answer(monkeypatch):
    runs: list[int] = []

    def probe(game, instruction, context):
        runs.append(len(_owed_offers(game)))
        return True, "resolved"

    monkeypatch.setitem(EFFECT_HANDLERS, _PROBE, probe)

    sites = _sites()
    assert len(sites) >= _SITES_FLOOR, f"the census found only {len(sites)} sites"
    early, unanswered, reached = [], [], []
    for card, unit, before, offer in sites:
        game = _board()
        runs.clear()
        source = None
        if not _is_spell(card):
            source = Permanent(card=card)
            game._put_permanent_onto_battlefield(0, source, None)
            game.stack.clear()
            game.pending_choices.clear()
        creature = next(p for p in game.controlled_by(1) if p.is_creature)
        # A spell of theirs on the stack, for "counter target spell unless …".
        game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
        context = OracleExecutionContext(
            caster=game.players[0], target=game.players[1], card=card,
            source_permanent=source, target_permanent_id=[creature.permanent_id],
            stack_target=game.stack[-1] if game.stack else None,
            trigger_context={"event_subject_player": 1, "event_subject_controller": 1},
        )
        game._execute_oracle_instruction(
            OracleInstruction("sequence", "", {"steps": (
                *before, offer, OracleInstruction(_PROBE, "", {}),
            )}),
            context,
        )
        if not _owed_offers(game):
            continue
        reached.append(card.name)
        if runs:
            early.append(f"{card.name} [{unit}]")
        for _ in range(10):
            owed = _owed_offers(game)
            if not owed:
                break
            assert game.confirm_optional_pay(owed[0].player_index, accept=False)
        if runs != [0]:
            unanswered.append(f"{card.name} [{unit}]: the probe ran {runs}")

    assert len(reached) >= _REACHED_FLOOR, (
        f"the board reached the offer at only {len(reached)} sites: {reached}"
    )
    assert not early, (
        "a step written behind an offer ran before the offer was answered "
        f"(CR 608.2c): {early}"
    )
    assert not unanswered, (
        "the steps behind an answered offer did not run exactly once: "
        f"{unanswered}"
    )


def _grip_table():
    game = Game(players=[
        PlayerState(
            "Caster", library=[_POOL["Forest"]] * 20,
            hand=[_POOL["Grip of Amnesia"]],
        ),
        PlayerState(
            "Opponent", library=[_POOL["Forest"]] * 20,
            hand=[_POOL["Lightning Bolt"]],
            graveyard=[_POOL["Grizzly Bears"]] * 3,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game.start_turn(0)
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    game.queue_from_hand(0, "Grip of Amnesia", target_stack_index=0)
    game.resolve_top_of_stack(pause_for_choices=True)
    return game


@pytest.mark.parametrize("accept", [True, False])
def test_grip_of_amnesia_draws_only_after_the_counter_is_decided(accept):
    game = _grip_table()
    caster, opponent = game.players
    grip = game.stack[-1]
    assert grip.card.name == "Grip of Amnesia" and grip.resolution_held
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("optional_pay", 1)
    ]
    # Asked, and nothing behind the question has happened yet.
    assert caster.hand == []
    assert f"{caster.name} drew 1 card(s) (Grip of Amnesia)" not in game.log

    assert game.confirm_optional_pay(1, accept=accept)
    resolve_stack(game)

    assert len(caster.hand) == 1
    assert game.resume_stack == [] and not game.effect_suspended
    log = game.log
    drew = log.index(f"{caster.name} drew 1 card(s) (Grip of Amnesia)")
    binned = log.index("Grip of Amnesia resolved and moved to graveyard")
    finished = log.index("Grip of Amnesia finished resolving")
    # CR 608.2c then CR 608.2n: the draw, then the card to the graveyard, and
    # only then is the resolution over (the object left the stack before the
    # draw while the answer released it).
    assert drew < binned < finished
    assert any(card.name == "Grip of Amnesia" for card in caster.graveyard)
    if accept:
        # The graveyard was the price, and the Bolt was not countered.
        assert len(opponent.exile) == 3
        assert [card.name for card in opponent.graveyard] == ["Lightning Bolt"]
        assert caster.life == 17
    else:
        assert len(opponent.graveyard) == 4  # three Bears and the countered Bolt
        assert caster.life == 20


def test_twitch_draws_after_its_caster_chooses_whether_to_tap():
    """"You may tap or untap target artifact, creature, or land. Draw a card."
    The caster decides blind of the card (CR 608.2c)."""
    game = Game(players=[
        PlayerState("Caster", library=[_POOL["Island"]] * 10, hand=[_POOL["Twitch"]]),
        PlayerState("Opponent", library=[_POOL["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    bears = Permanent(card=_POOL["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, bears, None)
    game.start_turn(0)
    game.queue_from_hand(0, "Twitch", target_permanent_ids=[bears.permanent_id])
    game.resolve_top_of_stack(pause_for_choices=True)
    caster = game.players[0]
    assert [c.kind for c in game.pending_choices] == ["optional_pay"]
    assert caster.hand == [] and not bears.tapped

    assert game.confirm_optional_pay(0, accept=True)
    resolve_stack(game)
    assert bears.tapped
    assert [card.name for card in caster.hand] == ["Island"]


def test_605_3a_a_mana_ability_tapped_to_pay_an_offer_resolves_at_once():
    """An offer priced in mana is answered by tapping for it — the seat's own
    mana abilities are what the spec admits while it is owed. The offer
    suspends its resolution; the mana ability is not part of that resolution
    and resolves immediately (CR 605.3a), drawback and all."""
    game = Game(players=[
        PlayerState(
            "Caster", library=[_POOL["Forest"]] * 20,
            hand=[_POOL["Grip of Amnesia"]],
        ),
        PlayerState(
            "Opponent", library=[_POOL["Forest"]] * 20,
            hand=[_POOL["Lightning Bolt"]],
            graveyard=[_POOL["Grizzly Bears"]] * 3,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    springs = Permanent(card=_POOL["Sulfurous Springs"])
    game._put_permanent_onto_battlefield(1, springs, None)
    game.start_turn(0)
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    game.queue_from_hand(0, "Grip of Amnesia", target_stack_index=0)
    game.resolve_top_of_stack(pause_for_choices=True)
    opponent = game.players[1]
    assert [c.kind for c in game.pending_choices] == ["optional_pay"]

    assert game.tap_land_for_mana(
        1, "Sulfurous Springs", chosen_color="B", permanent_id=springs.permanent_id,
    )
    assert opponent.mana_pool["B"] == 1
    assert opponent.life == 19, "the painland's damage waited for the offer"
    # …and the offer still waits, with the steps behind it.
    assert game.players[0].hand == []

    assert game.confirm_optional_pay(1, accept=False)
    resolve_stack(game)
    assert opponent.life == 19
    assert len(game.players[0].hand) == 1
    assert game.resume_stack == []


def test_forgotten_lore_cannot_choose_itself_on_a_table_nobody_holds():
    """A shipped card the suspension fixed (Ice Age; found by sim_fingerprint).

    "Target opponent chooses a card in your graveyard. You may pay {G}. If you
    do, repeat this process … Then put the last chosen card into your hand."
    CR 608.2n puts the spell into its owner's graveyard as the *last* step of
    its resolution. On a table that holds nothing for an answer (an AI or
    headless game), the {G} offer did not stop the resolution, so Forgotten
    Lore went to the graveyard between the rounds — and the next round's pick
    offered the opponent Forgotten Lore itself, which then went back to its
    caster's hand. The seeded ICE game did exactly that."""
    game = Game(players=[
        PlayerState(
            "Caster", library=[_POOL["Forest"]] * 5,
            hand=[_POOL["Forgotten Lore"]], graveyard=[_POOL["Balduvian Bears"]],
        ),
        PlayerState("Opponent", library=[_POOL["Forest"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    caster = game.players[0]
    caster.mana_pool["G"] = 1  # floating, so the seat's default pays the {G}

    assert game.cast_from_hand(0, "Forgotten Lore", target_player_index=1).supported
    for _ in range(10):
        if not game.pending_choices:
            break
        game.auto_resolve_pending_choices()
    resolve_stack(game)

    assert caster.mana_pool["G"] == 0, "the {G} was paid and the process repeated"
    assert [card.name for card in caster.hand] == ["Balduvian Bears"]
    assert [card.name for card in caster.graveyard] == ["Forgotten Lore"]
    assert game.resume_stack == []
