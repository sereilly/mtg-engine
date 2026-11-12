"""Census: every damage call outside ``engine/handlers`` asks CR 616.1e's
question, and answering it resumes the rest of the work.

CR 616.1: when two or more prevention or replacement effects would modify how
one event affects a player or an object, the affected player — or the
affected object's controller — chooses one to apply (616.1e), and the process
repeats (616.1f); several players choosing at once choose in APNAP order (its
last sentence). ``tests/regressions/test_kg_damage_loop_order_census.py``
drives every damage loop in the handlers; this drives every damage call
outside them, one board per site, each through its real entry point — an
upkeep step, a prompt's answer, a land play, a land tapped for mana, an Aura
resolving, a redirect applied inside another event.

The recipient that asks holds two applicable prevention effects from two
sources (a "prevent the next 3" pool and a counting pool, whose order is
visible afterwards) and its controller, seat 0, is interactive. Each case
checks:

* the default seat is not asked, and its run is the reference board;
* the interactive seat **is** asked — and, where the event is one of several,
  every recipient in front of it (in APNAP order) has been dealt to and the
  ones behind it not yet;
* answering with the first option — the default — leaves exactly the
  reference board and log, with nothing owed;
* answering with the second option is honoured: the recipient that asked
  differs, and every other recipient is still dealt to.

On the base (69dbbebc) every one of these was dealt without asking — and
Cyclone's sweep walked the seats in seat order, not APNAP.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.aura_attachment import attach_aura
from engine.card_loader import load_catalog
from engine.game_types import OracleExecutionContext
from engine.models import Permanent
from engine.oracle import OracleInstruction, compile_card_oracle
from engine.shields import add_shield, make_counting_pool, make_numeric_pool, shields_on
from tests.helpers import resolve_stack

_POOL = {card.name: card for card in load_catalog()}


def _instructions(value):
    if isinstance(value, OracleInstruction):
        yield value
        for sub in (value.payload or {}).values():
            yield from _instructions(sub)
    elif isinstance(value, (tuple, list)):
        for sub in value:
            yield from _instructions(sub)
    elif isinstance(value, dict):
        for sub in value.values():
            yield from _instructions(sub)


def _instruction(name: str, kind: str | None = None) -> OracleInstruction:
    """The first instruction of *name*'s program (of *kind*, if given)."""
    program = compile_card_oracle(_POOL[name])
    roots = list(program.instructions)
    roots += [a.instruction for a in program.activated_abilities if a.instruction]
    roots += [t.instruction for t in program.triggered_abilities if t.instruction]
    for root in roots:
        for found in _instructions(root):
            if kind is None or found.kind == kind:
                return found
    raise AssertionError(f"{name} compiles to no {kind!r} instruction")


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------


def _game(interactive: bool, active: int = 0, *, enforce: bool = False) -> Game:
    game = Game(players=[
        PlayerState(f"P{index}", library=[_POOL["Island"]] * 8) for index in range(2)
    ])
    game.enforce_mana_costs = enforce
    game.interactive_seats = {0} if interactive else set()
    game.begin_turn_bookkeeping(active)
    game.resolve_untap_step(active)
    return game


def _put(game: Game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_POOL[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    resolve_stack(game)
    game.pending_choices.clear()
    game.pending_replacement_choices.clear()
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _arm_two(recipient) -> None:
    """Two applicable prevention effects from two sources: a plain pool and a
    pool that puts a +1/+1 counter down for each point it absorbs, each deep
    enough for any one event here. Either may apply first (CR 616.1e), and
    which did is visible afterwards."""
    add_shield(recipient, make_numeric_pool(10, source_name="Plain Pool"))
    add_shield(recipient, make_counting_pool(10, "+1/+1", source_name="Counting Pool"))


def _snap(game: Game, thing) -> tuple:
    shields = tuple(sorted((s.kind, s.amount) for s in shields_on(thing)))
    if isinstance(thing, PlayerState):
        return ("player", thing.name, thing.life, shields)
    return (
        thing.card.name, game.is_on_battlefield(thing),
        thing.damage_marked, int(thing.metadata.get("plus_counters", 0) or 0),
        shields,
    )


def _execute(game, name, instruction, **context) -> None:
    context.setdefault("caster", game.players[0])
    context.setdefault("target", game.players[0])
    game._execute_oracle_instruction(
        instruction, OracleExecutionContext(card=_POOL[name], **context),
    )


def _ping(game, sorcerer: Permanent, target, permanent=None) -> None:
    """Seat 1's Prodigal Sorcerer deals 1 damage to *target* (a player, or
    *permanent*): the ordinary handler, which asks its own question."""
    context = {"caster": game.players[1], "target": target, "source_permanent": sorcerer}
    if permanent is not None:
        context["target_permanent_id"] = [permanent.permanent_id]
    _execute(game, "Prodigal Sorcerer", _instruction("Prodigal Sorcerer", "deal_damage"), **context)


# ---------------------------------------------------------------------------
# One driver per site: build the board, return (recipients in the order they
# are dealt to, the index of the one that asks, the run)
# ---------------------------------------------------------------------------


def _witches_default(game):
    """``effects._apply_opponent_damage_choice`` through the prompt's default:
    the activator's opponent is not asked, so its pick (the activator's face —
    nothing of theirs would die to 1) is made as it is armed, inside the
    handler, after the first half — and both halves, one split sentence, are
    then dealt in APNAP order (kg4 `dealings`): the activator's face, the
    active player's, first."""
    witches = _put(game, 0, "Cuombajj Witches")
    _arm_two(game.players[0])
    return [game.players[0], game.players[1]], 0, lambda: _execute(
        game, "Cuombajj Witches",
        _instruction("Cuombajj Witches", "deal_damage_and_opponent_choice"),
        target=game.players[1], source_permanent=witches,
    )


def _witches_first_half_asks(game):
    """The handler's first half asks, and the opponent's default — dealt the
    moment it is armed — must wait for the answer (one resumable loop)."""
    witches = _put(game, 0, "Cuombajj Witches")
    _arm_two(game.players[0])
    return [game.players[0]], 0, lambda: _execute(
        game, "Cuombajj Witches",
        _instruction("Cuombajj Witches", "deal_damage_and_opponent_choice"),
        target=game.players[0], source_permanent=witches,
    )


def _arcanix(game):
    """``choices/card_names._resolve_name_then_reveal_top``: a miss deals 2."""
    arcanix = _put(game, 0, "Vexing Arcanix")
    _arm_two(game.players[0])

    def run():
        _execute(
            game, "Vexing Arcanix", _instruction("Vexing Arcanix", "name_then_reveal_top"),
            source_permanent=arcanix,
        )
        assert game.confirm_name_then_reveal_top(0, "Black Lotus")

    return [game.players[0]], 0, run


def _ogress(game):
    """``choices/optional_pay._apply_optional_pay_decline``: declined, 3."""
    ogress = _put(game, 0, "Hasran Ogress")
    _arm_two(game.players[0])

    def run():
        _execute(
            game, "Hasran Ogress", _instruction("Hasran Ogress", "self_damage_unless_pay"),
            source_permanent=ogress,
        )
        assert game.confirm_optional_pay(0, accept=False)

    return [game.players[0]], 0, run


def _cyclone(game):
    """``upkeep_effects._wind_sweep``: seat 1's Cyclone, paid. APNAP: seat 1
    and its creature, then seat 0 and its two — the first of which asks."""
    cyclone = _put(game, 1, "Cyclone")
    _put(game, 1, "Forest")
    theirs = _put(game, 1, "Grizzly Bears")
    asker = _put(game, 0, "Grizzly Bears")
    behind = _put(game, 0, "Grizzly Bears")
    _arm_two(asker)
    return (
        [game.players[1], theirs, game.players[0], asker, behind], 3,
        lambda: game.resolve_upkeep(1, human_choices={cyclone.permanent_id: True}),
    )


def _cursed_land(game):
    """``upkeep_effects`` "upkeep of enchanted land's controller" damage."""
    land = _put(game, 0, "Island")
    aura = _put(game, 1, "Cursed Land")
    attach_aura(aura, land)
    _arm_two(game.players[0])
    return [game.players[0]], 0, lambda: game.resolve_upkeep(0)


def _force_of_nature(game):
    """``upkeep_effects`` pay-or-damage, declined: 8 to its controller."""
    force = _put(game, 0, "Force of Nature")
    _arm_two(game.players[0])
    return [game.players[0]], 0, lambda: game.resolve_upkeep(
        0, human_choices={force.permanent_id: False},
    )


def _fastbond(game):
    """``stack/permanent_spell_resolution._resolve_permanent_spell``'s extra-land
    rider: the second land."""
    _put(game, 0, "Fastbond")
    game.players[0].hand.extend([_POOL["Forest"], _POOL["Forest"]])
    game.enter_next_turn_phase("beginning")
    assert game.cast_from_hand(0, "Forest").supported
    _arm_two(game.players[0])
    return [game.players[0]], 0, lambda: game.cast_from_hand(0, "Forest")


def _manabarbs(game):
    """``land_tapped_for_mana._resolve_tapped_land_trigger_step``."""
    _put(game, 1, "Manabarbs")
    mountain = _put(game, 0, "Mountain")
    _arm_two(game.players[0])
    return [game.players[0]], 0, lambda: game.tap_land_for_mana(
        0, "Mountain", permanent_id=mountain.permanent_id,
    )


def _earthbind(game):
    """``oracle_instructions._apply_aura_effect``'s Earthbind branch."""
    flyer = _put(game, 0, "Scryb Sprites")
    _arm_two(flyer)
    game.players[1].hand.append(_POOL["Earthbind"])

    def run():
        game.cast_from_hand(
            1, "Earthbind", target_player_index=0,
            target_permanent_ids=[flyer.permanent_id],
        )
        # One resolution, not ``resolve_stack``: that answers what holds the
        # stack, and a question held there is what is being looked for.
        game.resolve_top_of_stack()

    return [flyer], 0, run


def _eye_for_an_eye(game):
    """``effects._apply_mirror_damage``: seat 1's Eye for an Eye sends seat 0's
    ping back to seat 0."""
    sorcerer = _put(game, 0, "Prodigal Sorcerer")
    _execute(
        game, "Eye for an Eye", _instruction("Eye for an Eye"), caster=game.players[1],
        target=game.players[1],
    )
    _arm_two(game.players[0])
    context = {"caster": game.players[0], "target": game.players[1], "source_permanent": sorcerer}
    return [game.players[1], game.players[0]], 1, lambda: _execute(
        game, "Prodigal Sorcerer", _instruction("Prodigal Sorcerer", "deal_damage"), **context,
    )


def _martyrs(game):
    """``redirects._redirect_damage_to_bodyguard``: an artifact's damage to
    seat 0 is dealt to its untapped Martyrs of Korlis instead."""
    martyrs = _put(game, 0, "Martyrs of Korlis")
    launcher = _put(game, 1, "Rocket Launcher")
    _arm_two(martyrs)
    return [martyrs, game.players[0]], 0, lambda: _execute(
        game, "Rocket Launcher", _instruction("Rocket Launcher", "deal_damage"),
        caster=game.players[1], target=game.players[0], source_permanent=launcher,
    )


def _jade_monolith(game):
    """``redirects._apply_recorded_redirect`` (Jade Monolith's record): the
    creature's damage is dealt to seat 0 instead."""
    _put(game, 0, "Jade Monolith")
    bear = _put(game, 0, "Grizzly Bears")
    sorcerer = _put(game, 1, "Prodigal Sorcerer")
    assert game.activate_permanent_ability(
        0, "Jade Monolith", target_player_index=0,
        target_permanent_ids=[bear.permanent_id],
    ).supported
    resolve_stack(game)
    _arm_two(game.players[0])
    return [game.players[0], bear], 0, lambda: _ping(game, sorcerer, game.players[0], bear)


def _personal_incarnation(game):
    """``redirects._redirect_one_damage_to_owner``: one point to its owner."""
    incarnation = _put(game, 0, "Personal Incarnation")
    sorcerer = _put(game, 1, "Prodigal Sorcerer")
    assert game.activate_permanent_ability(0, "Personal Incarnation").supported
    resolve_stack(game)
    _arm_two(game.players[0])
    return (
        [game.players[0], incarnation], 0,
        lambda: _ping(game, sorcerer, game.players[0], incarnation),
    )


def _pariah(game):
    """``redirects._apply_recorded_redirect`` (an Aura's static record): seat
    0's damage is dealt to the creature Pariah enchants instead."""
    bear = _put(game, 0, "Grizzly Bears")
    pariah = _put(game, 0, "Pariah")
    attach_aura(pariah, bear)
    sorcerer = _put(game, 1, "Prodigal Sorcerer")
    _arm_two(bear)
    return [bear, game.players[0]], 0, lambda: _ping(game, sorcerer, game.players[0])


def _blood_of_the_martyr(game):
    """``redirects._resolve_optional_damage_redirect``: seat 0 takes the Shock
    aimed at its Grizzly Bears (which it would kill), and is asked about its
    own shields."""
    bear = _put(game, 0, "Grizzly Bears")
    _execute(game, "Blood of the Martyr", _instruction("Blood of the Martyr"))
    _arm_two(game.players[0])

    def run():
        _execute(
            game, "Shock", _instruction("Shock", "deal_damage"), caster=game.players[1],
            target=game.players[0], target_permanent_id=[bear.permanent_id],
        )
        if game.pending_replacement_choices:
            assert game.resolve_replacement_choice(0, 0, kind="optional_damage_redirect")

    return [game.players[0], bear], 0, run


#: (label, driver, active seat, enforce mana costs)
_CASES = (
    ("prompt: opponent_damage default (Cuombajj Witches)", _witches_default, 0, False),
    ("handler: Cuombajj Witches' first half asks", _witches_first_half_asks, 0, False),
    ("prompt: name_then_reveal_top miss (Vexing Arcanix)", _arcanix, 0, False),
    ("prompt: optional_pay decline (Hasran Ogress)", _ogress, 0, False),
    ("upkeep: Cyclone's sweep, APNAP", _cyclone, 1, False),
    ("upkeep: enchanted land's controller (Cursed Land)", _cursed_land, 0, False),
    ("upkeep: pay or damage (Force of Nature)", _force_of_nature, 0, False),
    ("land play: the extra-land rider (Fastbond)", _fastbond, 0, True),
    ("land tapped for mana (Manabarbs)", _manabarbs, 0, False),
    ("Aura entry (Earthbind)", _earthbind, 0, False),
    ("mirror (Eye for an Eye)", _eye_for_an_eye, 0, False),
    ("redirect: bodyguard (Martyrs of Korlis)", _martyrs, 0, False),
    ("redirect: Jade Monolith", _jade_monolith, 0, False),
    ("redirect: one point to its owner (Personal Incarnation)", _personal_incarnation, 0, False),
    ("redirect: an Aura's static record (Pariah)", _pariah, 0, False),
    ("redirect: an optional record, taken (Blood of the Martyr)", _blood_of_the_martyr, 0, False),
)


def _run(driver, active, enforce, *, interactive: bool):
    game = _game(interactive, active, enforce=enforce)
    recipients, asker, run = driver(game)
    before = [_snap(game, r) for r in recipients]
    mark = len(game.log)
    run()
    return game, recipients, asker, before, mark


def _answer(game, option: int) -> None:
    choice = game.pending_choice_of("effect_order")
    assert game.resolve_pending_choice("effect_order", choice.player_index, option_index=option)


def _answer_all(game, first: int) -> None:
    _answer(game, first)
    while game.pending_choice_of("effect_order") is not None:
        _answer(game, 0)


def _lines(game, mark: int) -> list[str]:
    """What the effect wrote, without the questions, their answers, and the
    line a held resolution writes as it is released."""
    return [
        line for line in game.log[mark:]
        if "which effect applies first" not in line
        and not (line.startswith("P") and " applies " in line and line.endswith(" first"))
        and " may take the " not in line
        and not line.endswith(" finished resolving")
    ]


def test_every_damage_call_outside_the_handlers_asks_and_resumes():
    unasked, early, unfinished, unhonoured, inert = [], [], [], [], []
    for label, driver, active, enforce in _CASES:
        ref, recipients, asker, before, mark = _run(driver, active, enforce, interactive=False)
        dealt = [_snap(ref, r) for r in recipients]
        if dealt[asker] == before[asker]:
            inert.append(label)
            continue
        assert not ref.pending_choices, f"{label}: a default seat was asked"
        ref.check_state_based_actions()
        reference = [_snap(ref, r) for r in recipients]
        ref_lines = _lines(ref, mark)

        game, recipients, asker, _, mark = _run(driver, active, enforce, interactive=True)
        asked = [c for c in game.pending_choices if c.kind == "effect_order"]
        if not asked:
            unasked.append(label)
            continue
        assert asked[0].player_index == 0, label
        now = [_snap(game, r) for r in recipients]
        expected = dealt[:asker] + before[asker:]
        if now != expected or len(asked) != 1:
            early.append(f"{label}: {now} != {expected} ({len(asked)} asked)")
            continue
        _answer_all(game, 0)
        game.check_state_based_actions()
        after = [_snap(game, r) for r in recipients]
        if after != reference:
            unfinished.append(f"{label}: {after} != {reference}")
        if game.resume_stack or game.pending_choices or game.stack:
            unfinished.append(
                f"{label}: {len(game.resume_stack)} step(s) owed, "
                f"{[c.kind for c in game.pending_choices]} queued, "
                f"{len(game.stack)} on the stack"
            )
        # As a multiset: an asked event reports after the answer, so its line
        # can follow a line the default run wrote after it (Eye for an Eye's
        # mirror reports after the ping it mirrors). Every line, once.
        if sorted(_lines(game, mark)) != sorted(ref_lines):
            unfinished.append(f"{label}: wrote {_lines(game, mark)}, not {ref_lines}")

        other, recipients, asker, _, _ = _run(driver, active, enforce, interactive=True)
        _answer_all(other, 1)
        other.check_state_based_actions()
        honoured = [_snap(other, r) for r in recipients]
        if honoured[asker] == reference[asker] or (
            honoured[:asker] + honoured[asker + 1:]
            != reference[:asker] + reference[asker + 1:]
        ):
            unhonoured.append(f"{label}: {honoured} vs {reference}")

    findings = {
        "the run never reached the recipient that should ask (a dead driver)": inert,
        "dealt to a recipient with two applicable effects without asking its "
        "controller (CR 616.1e)": unasked,
        "the recipients behind the one that asked were dealt to before the "
        "answer, or the ones in front of it (APNAP) were not": early,
        "the work did not finish after the answer": unfinished,
        "the second option was not honoured": unhonoured,
    }
    assert not any(findings.values()), "\n".join(
        f"{what}: {rows}" for what, rows in findings.items() if rows
    )
    # A floor on what was examined.
    assert len(_CASES) >= 16


def test_an_opponents_target_choice_answered_by_a_person_asks_the_damaged_seat():
    """``effects._resolve_opponent_damage_choice``: seat 1 activates Cuombajj
    Witches, seat 0 is the opponent who picks the second target and picks its
    own face, which holds two shields. The answer to the target prompt deals
    the damage, and that event asks seat 0 which shield applies first."""
    game = _game(True, 1)
    witches = _put(game, 1, "Cuombajj Witches")
    _arm_two(game.players[0])
    _execute(
        game, "Cuombajj Witches",
        _instruction("Cuombajj Witches", "deal_damage_and_opponent_choice"),
        caster=game.players[1], target=game.players[1], source_permanent=witches,
    )
    assert game.pending_choice_of("opponent_damage", 0) is not None
    assert game.confirm_opponent_damage_choice(0, target_seat=0)
    asked = game.pending_choice_of("effect_order", 0)
    assert asked is not None
    untouched = {s.source_name: s.amount for s in shields_on(game.players[0])}
    assert untouched == {"Plain Pool": 10, "Counting Pool": 10}
    picked = "Counting Pool" if "counters" in asked.data["options"][1] else "Plain Pool"
    _answer(game, 1)
    left = {s.source_name: s.amount for s in shields_on(game.players[0])}
    assert left == {**untouched, picked: 9}
    assert game.players[0].life == 20
    assert not game.pending_choices and not game.resume_stack
    assert any("(opponent's choice)" in line for line in game.log)
