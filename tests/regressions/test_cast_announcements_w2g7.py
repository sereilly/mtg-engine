"""Regression (INV W2G7): what a cast may announce, asked of the whole pool.

Two halves of CR 601.2c that the engine answered on some callers and not in
itself.

**A spell that must name a target cannot be cast at nothing.** The cast path
asked "is there anything to aim at?" in a per-kind arm keyed on the spell's
*first* instruction, so the question reached eleven instruction kinds and no
spell whose first instruction is a wrapper. "Destroy target artifact or
enchantment. Draw two cards." on an empty board was announced, paid for,
destroyed nothing and drew two; Disenchant — the same first sentence, alone —
was refused. The browser's picker and the AI's proposal filter both declined
these, which is how a rule comes to be enforced on two callers and not in the
engine: every headless caller, and every test, could cast them.
``legality.no_legal_cast_target_refusal`` is the one predicate now, and the
AI and the castable highlight ask it.

**An Aura named by ``permanent_id`` alone is a complete announcement.** Every
Aura in the pool was refused "requires a target" when its host was named the
way this engine asks for (CLAUDE.md: "address a permanent by its id, not its
slot"), because the Aura arm of the cast gate and the attachment at resolution
both read a slot. ``Game.announced_target_slot`` derives it from the id.

Both sweeps carry a floor on what they examined: "nothing wrong" over a sweep
that reached nothing is a true statement about nothing.
"""

from __future__ import annotations

import re

from engine import Game, PlayerState
from engine.ai_policy import _can_cast_with_targets
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import face_cards
from engine.handlers._common import attached_host
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec, spec_is_a_cost, spec_roles
from tests.helpers import _mk_card, _nosick, resolve_stack


def _w2g7_pool() -> dict:
    """Every spell in both manifest roles, a split card as its halves."""
    pool: dict = {}
    for card in load_cards(manifest_set_paths(include_measured=True)):
        for spell in face_cards(card) or [card]:
            pool.setdefault(spell.name, spell)
    return pool


def _w2g7_empty_board(card, *, bf0=(), bf1=(), graveyard=()) -> Game:
    """Seat 0 holding *card*, on its own turn, with only what is passed."""
    filler = _mk_card(name="Filler", type_line="Land")
    game = Game(players=[
        PlayerState(
            "A", library=[filler] * 10, hand=[card], graveyard=list(graveyard),
            battlefield=[_nosick(Permanent(card=c)) for c in bf0],
        ),
        PlayerState(
            "B", library=[filler] * 10,
            battlefield=[_nosick(Permanent(card=c)) for c in bf1],
        ),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    return game


# ---------------------------------------------------------------------------
# The anecdote: the shape wave 1 found it on
# ---------------------------------------------------------------------------


_W2G7_TWO_SENTENCES = _mk_card(
    name="W2G7 Demolition Notes", mana_cost="{2}{W}", type_line="Instant",
    oracle_text="Destroy target artifact or enchantment. Draw two cards.",
)


def test_w2g7_a_two_sentence_removal_spell_cannot_be_cast_at_nothing():
    """The invented card from wave 1's census: a `sequence` first, so it
    reached no arm of ``_validate_cast_targets`` and was a two-card cantrip."""
    game = _w2g7_empty_board(_W2G7_TWO_SENTENCES)

    result = game.cast_from_hand(0, _W2G7_TWO_SENTENCES.name)

    assert not result.supported
    assert "no valid target" in result.details
    # Refused at the announcement: nothing spent, nothing moved, nothing drawn.
    assert [card.name for card in game.players[0].hand] == [_W2G7_TWO_SENTENCES.name]
    assert not game.stack
    assert len(game.players[0].library) == 10


def test_w2g7_the_same_spell_with_something_to_destroy_still_resolves():
    """The other direction: the gate asks the board, it does not ban the card."""
    relic = _mk_card(name="W2G7 Relic", type_line="Artifact")
    game = _w2g7_empty_board(_W2G7_TWO_SENTENCES, bf1=[relic])
    target = game.players[1].battlefield[0]

    result = game.cast_from_hand(
        0, _W2G7_TWO_SENTENCES.name, target_permanent_ids=[target.permanent_id]
    )
    resolve_stack(game)

    assert result.supported, result.details
    assert not game.players[1].battlefield
    assert len(game.players[0].hand) == 2


def test_w2g7_dismantling_blow_is_refused_kicked_or_not_with_nothing_to_destroy(set_pool):
    """The card wave 1 found it on. The kicker buys the *draw*, not the target:
    its destroy is unconditional, so no announcement of it is legal here."""
    from engine.cast_costs import kicker_cost

    blow = set_pool("INV")["Dismantling Blow"]
    kicker = kicker_cost(blow.oracle_text)
    for payments in (None, {}, {kicker: 1}):
        game = _w2g7_empty_board(blow)
        result = game.cast_from_hand(0, blow.name, optional_cost_payments=payments)
        assert not result.supported, (payments, result.details)
        assert [card.name for card in game.players[0].hand] == [blow.name]
        assert len(game.players[0].library) == 10, "the kicked half drew anyway"


# ---------------------------------------------------------------------------
# The pool: every targeted instant and sorcery, on a board with no target
# ---------------------------------------------------------------------------

_W2G7_REMINDER = re.compile(r"\([^)]*\)")
#: The printed spellings that let an announcement name nobody (CR 601.2c).
#: Read off the **card text** on purpose: the gate decides from the compiled
#: program, and a sweep that asked the program too would be the gate checking
#: its own arithmetic.
_W2G7_ZERO_IS_LEGAL = re.compile(
    r"up to (?:one|two|three|four|five|six|seven|x|\d+) (?:other |another )?target"
    r"|any number of (?:other )?target"
    r"|\bx target\b"
    r"|each of x target\b",
    re.I,
)


#: The first printed target phrase, with whatever quantifier introduces it.
_W2G7_FIRST_TARGET = re.compile(
    r"(?:up to \w+ (?:other |another )?|any number of (?:other )?|each of x |\bx )?target",
    re.I,
)


def _w2g7_printed(card) -> str:
    return _W2G7_REMINDER.sub("", card.oracle_text or "")


def test_w2g7_no_spell_in_the_pool_is_cast_bare_at_an_empty_board_unless_its_text_allows_it():
    """Every non-modal instant and sorcery whose **picker** is empty on an
    empty board, cast naming nothing.

    The picker's own spec (``derive_cast_spec``) says which spells ask for
    something; the card's printed words say which of them may be announced at
    nothing. An accepted cast has to be one of, and the list is the whole of
    what the gate leaves alone:

    * a target **on the stack** alone — the stack gates' question, not this
      one's (seventeen cards today, counted so the number is seen to fall);
    * a spell that does not print the word "target" at all — a *source of your
      choice* (CR 609.7a), or a choice the spell offers at resolution
      (Experimental Overload);
    * "up to N target", "any number of target", "X target" — zero is legal.
    """
    examined = refused = 0
    on_the_stack: list[str] = []
    unexplained: list[str] = []
    still_proposed: list[str] = []
    over_refused: list[str] = []
    for spell in _w2g7_pool().values():
        type_line = spell.type_line.lower()
        if "instant" not in type_line and "sorcery" not in type_line:
            continue
        program = compile_card_oracle(spell)
        if not program.supported or program.modes:
            continue
        spec = derive_cast_spec(spell, program)
        if spec is None or spec.get("kind") in ("none", "modal") or spec_roles(spec):
            continue
        game = _w2g7_empty_board(spell)
        if game._enumerate_targets(0, spell, dict(spec), for_cast=True):
            continue  # a player is always there: "any target", "target player"
        examined += 1
        result = game.cast_from_hand(0, spell.name)
        if not result.supported:
            refused += 1
            assert [card.name for card in game.players[0].hand] == [spell.name], (
                f"{spell.name} was refused and left the hand anyway"
            )
            # The policy may not propose what the engine has just declined.
            if _can_cast_with_targets(_w2g7_empty_board(spell), 0, spell):
                still_proposed.append(spell.name)
            # …and the other direction: "no valid target" is not a reason to
            # refuse an announcement the card lets name nobody. Only the first
            # printed target counts — Primal Might's "up to one" is its second.
            first = _W2G7_FIRST_TARGET.search(_w2g7_printed(spell))
            if (
                "no valid target" in result.details
                and first is not None
                and _W2G7_ZERO_IS_LEGAL.fullmatch(first.group(0))
            ):
                over_refused.append(spell.name)
            continue
        text = _w2g7_printed(spell)
        if spec.get("kind") == "stack":
            on_the_stack.append(spell.name)
        elif "target" not in text.lower() or _W2G7_ZERO_IS_LEGAL.search(text):
            pass
        else:
            unexplained.append(spell.name)

    assert not unexplained, (
        f"{len(unexplained)} of {examined} targeted spells were cast naming "
        f"nothing, on a board with no legal target: {sorted(unexplained)[:15]}"
    )
    assert not still_proposed, (
        f"the AI still proposes {len(still_proposed)} casts the engine refuses "
        f"for want of a target: {sorted(still_proposed)[:15]}"
    )
    # Seven when this was written — Aether Tide, Avalanche, Distorting Wake,
    # Phyrexian Purge, Scapegoat, Scorched Earth, Tidal Surge, Word of Binding
    # less the one a cost refused first — every one by a per-kind arm written
    # for a one-target spell.
    assert not over_refused, (
        f"{len(over_refused)} spells that may name no target were refused for "
        f"having none to name: {sorted(over_refused)}"
    )
    # 433 examined and 378 refused when this was written; without the gate 196
    # are, so 182 casts at nothing were legal before it.
    assert examined > 380, f"the sweep only examined {examined} spells"
    assert refused > 330, f"only {refused} bare casts were refused"
    # A target that can only be on the stack is INV W2G3's gate
    # (`cast_stack_target_refusal`), not this predicate's. On this branch
    # alone seventeen such spells were still castable bare on an empty stack
    # and the ceiling stood at 17; the two branches met at the wave-2
    # integration, the list emptied, and the ceiling followed it down.
    assert not on_the_stack, sorted(on_the_stack)


def test_w2g7_the_sweep_sees_the_defect_when_the_gate_is_switched_off(monkeypatch):
    """The census validated backwards: without the gate, the same question
    names the known shape. A sweep that cannot fail is not a guard."""
    from engine.legality import LegalityMixin

    monkeypatch.setattr(
        LegalityMixin, "no_legal_cast_target_refusal",
        lambda self, *args, **kwargs: None,
    )
    game = _w2g7_empty_board(_W2G7_TWO_SENTENCES)

    result = game.cast_from_hand(0, _W2G7_TWO_SENTENCES.name)

    assert result.supported, "the per-kind arms were never what refused this"
    assert len(game.players[0].hand) == 2, "…and it drew its two cards"


# ---------------------------------------------------------------------------
# Zero is a legal number of targets — the arms that forgot
# ---------------------------------------------------------------------------


def test_w2g7_up_to_three_targets_is_castable_at_none(catalog_by_name):
    """"Tap up to three target creatures without flying." (Tidal Surge.) The
    tap arm refused it for an empty board; the AI, whose reader knew "up to",
    proposed it every turn and was refused every turn."""
    surge = catalog_by_name["Tidal Surge"]
    game = _w2g7_empty_board(surge)

    assert _can_cast_with_targets(game, 0, surge)
    result = game.cast_from_hand(0, surge.name)
    resolve_stack(game)

    assert result.supported, result.details
    assert [card.name for card in game.players[0].graveyard] == [surge.name]


def test_w2g7_any_number_of_targets_is_castable_at_none(catalog_by_name):
    """"Destroy any number of target creatures." (Phyrexian Purge.)"""
    purge = catalog_by_name["Phyrexian Purge"]
    game = _w2g7_empty_board(purge)

    result = game.cast_from_hand(0, purge.name)
    resolve_stack(game)

    assert result.supported, result.details
    assert game.players[0].life == 20, "three life per target, and there were none"


def test_w2g7_x_targets_are_owed_only_once_x_is_announced(catalog_by_name):
    """"Tap X target creatures." (Word of Binding.) X may be zero, so an
    empty board is castable at X=0 —
    and is not at X=2, which promises two targets that do not exist."""
    binding = catalog_by_name["Word of Binding"]

    game = _w2g7_empty_board(binding)
    assert game.cast_from_hand(0, binding.name, x_value=0).supported

    game = _w2g7_empty_board(binding)
    result = game.cast_from_hand(0, binding.name, x_value=2)
    assert not result.supported
    assert "no valid target" in result.details
    assert [card.name for card in game.players[0].hand] == [binding.name]


# ---------------------------------------------------------------------------
# A spell's target named by id: the two gates that read only the slot
# ---------------------------------------------------------------------------


def test_w2g7_untap_target_permanent_by_id_does_not_ask_the_other_battlefield(catalog_by_name):
    """"Untap target permanent." (Burst of Energy.) The tap arm judged the
    *default* seat's battlefield — the opponent's — so a cast aimed by id at
    the caster's own land was refused whenever the opponent controlled nothing."""
    burst = catalog_by_name["Burst of Energy"]
    land = _mk_card(name="W2G7 Field", type_line="Land")
    game = _w2g7_empty_board(burst, bf0=[land])
    field = game.players[0].battlefield[0]
    field.tapped = True

    result = game.cast_from_hand(0, burst.name, target_permanent_ids=[field.permanent_id])
    resolve_stack(game)

    assert result.supported, result.details
    assert not field.tapped, game.log


def test_w2g7_mana_value_x_is_asked_of_a_target_named_by_id(catalog_by_name):
    """"Destroy target artifact with mana value X. … deals X damage to that
    artifact's controller." (Detonate.) ``_x_implied_by_target`` read the slot
    alone, so by id the printed restriction was asked of nothing: X=4 at a
    zero-cost artifact destroyed it and dealt 4."""
    detonate = catalog_by_name["Detonate"]
    trinket = _mk_card(name="W2G7 Trinket", type_line="Artifact")  # mana value 0

    game = _w2g7_empty_board(detonate, bf1=[trinket])
    target = game.players[1].battlefield[0]
    result = game.cast_from_hand(
        0, detonate.name, target_permanent_ids=[target.permanent_id], x_value=4
    )
    assert not result.supported, "X=4 names no artifact with mana value 0"
    assert game.players[1].battlefield == [target]
    assert game.players[1].life == 20

    # …and an X nobody stated is the one the named target fixes.
    game = _w2g7_empty_board(detonate, bf1=[trinket])
    target = game.players[1].battlefield[0]
    result = game.cast_from_hand(0, detonate.name, target_permanent_ids=[target.permanent_id])
    resolve_stack(game)
    assert result.supported, result.details
    assert not game.players[1].battlefield
    assert game.players[1].life == 20


def test_w2g7_every_spell_aimed_by_id_at_its_casters_side_is_the_cast_by_slot():
    """The spell half of the Aura sweep below: every non-modal instant and
    sorcery that can name a permanent on its caster's own battlefield, aimed
    there by id alone, with the opposing board **empty** and then mirrored.

    Prophecy's sweep settled the seat an id names once the object is on the
    stack; this asks the step before — whether the announcement is *accepted*
    the same way by id as by slot. Six spells were refused by id (the tap arm)
    and two were accepted by id past a restriction the slot spelling is held
    to (Detonate, Kaervek's Purge).
    """
    measured, wrong = 0, []
    for card in _w2g7_pool().values():
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported or program.modes:
            continue
        spec = derive_cast_spec(card, program)
        if (
            spec is None or spec_roles(spec) or spec_is_a_cost(spec)
            or spec.get("source_of_choice") or spec.get("cost_spec")
            or spec.get("kind") in (
                "none", "modal", "hand_card", "graveyard_creature", "stack", "player",
            )
        ):
            continue
        x_value = 1 if "{X}" in (card.mana_cost or "") else None
        for mirrored in (False, True):
            def board():
                game = _w2g7_empty_board(
                    card, bf0=_w2g7_bait(), bf1=_w2g7_bait() if mirrored else ()
                )
                game.start_turn(0)
                game.current_phase = "main"
                return game

            offered = board()._enumerate_targets(0, card, dict(spec), for_cast=True)
            slot = next(
                (
                    entry["index"] for entry in offered
                    if entry.get("kind") == "permanent" and entry.get("seat") == 0
                ),
                None,
            )
            if slot is None:
                continue
            by_slot = board().queue_from_hand(
                0, card.name, target_player_index=0, target_permanent_index=slot,
                x_value=x_value,
            )
            game = board()
            by_id = game.queue_from_hand(
                0, card.name, x_value=x_value,
                target_permanent_ids=[game.permanent_at(0, slot).permanent_id],
            )
            measured += 1
            item = next((obj for obj in game.stack if obj.card.name == card.name), None)
            if by_slot.supported != by_id.supported:
                wrong.append(f"{card.name}: slot {by_slot.details!r}, id {by_id.details!r}")
            elif by_id.supported and item is not None and item.target_player_index != 0:
                wrong.append(f"{card.name}: announced at seat {item.target_player_index}")
    assert not wrong, (
        f"{len(wrong)} of {measured} spells answered differently to an id than "
        f"to the slot it names: {sorted(wrong)[:10]}"
    )
    # 644 when this was written.
    assert measured > 500, f"the sweep only examined {measured} announcements"


# ---------------------------------------------------------------------------
# An Aura announced by id alone
# ---------------------------------------------------------------------------


def _w2g7_creature(name: str):
    return _mk_card(name=name, type_line="Creature - Human", power=1, toughness=1)


def test_w2g7_an_aura_cast_by_id_alone_enchants_the_creature_it_named(catalog_by_name):
    """Mirrored boards, so a slot read off the wrong battlefield lands on the
    look-alike: the id names seat 0's creature and nothing names a seat."""
    aura = catalog_by_name["Holy Strength"]
    game = _w2g7_empty_board(
        aura, bf0=[_w2g7_creature("Mine")], bf1=[_w2g7_creature("Theirs")]
    )
    mine, theirs = game.players[0].battlefield[0], game.players[1].battlefield[0]

    result = game.cast_from_hand(0, aura.name, target_permanent_ids=[mine.permanent_id])
    resolve_stack(game)

    assert result.supported, result.details
    assert (mine.effective_power, mine.effective_toughness) == (2, 3), game.log
    assert (theirs.effective_power, theirs.effective_toughness) == (1, 1), game.log


def test_w2g7_an_aura_cast_by_id_alone_reaches_the_opposing_battlefield(catalog_by_name):
    aura = catalog_by_name["Holy Strength"]
    game = _w2g7_empty_board(
        aura, bf0=[_w2g7_creature("Mine")], bf1=[_w2g7_creature("Theirs")]
    )
    mine, theirs = game.players[0].battlefield[0], game.players[1].battlefield[0]

    result = game.cast_from_hand(0, aura.name, target_permanent_ids=[theirs.permanent_id])
    resolve_stack(game)

    assert result.supported, result.details
    assert (theirs.effective_power, theirs.effective_toughness) == (2, 3), game.log
    assert (mine.effective_power, mine.effective_toughness) == (1, 1), game.log


def test_w2g7_an_aura_named_by_id_follows_the_object_when_its_slot_moves(catalog_by_name):
    """The reason an id is the address (CR 400.7): the slot renumbers while the
    Aura waits on the stack, and the object does not."""
    aura = catalog_by_name["Holy Strength"]
    game = _w2g7_empty_board(
        aura, bf0=[_w2g7_creature("First"), _w2g7_creature("Named")]
    )
    first, named = game.players[0].battlefield

    result = game.queue_from_hand(0, aura.name, target_permanent_ids=[named.permanent_id])
    assert result.supported, result.details
    game.remove_from_battlefield(first)  # "Named" slides from slot 1 to slot 0
    resolve_stack(game)

    assert (named.effective_power, named.effective_toughness) == (2, 3), game.log


def test_w2g7_an_aura_named_by_an_id_it_cannot_enchant_is_still_refused(catalog_by_name):
    """Deriving the slot must not skip the arm: the enchant noun is still asked."""
    aura = catalog_by_name["Holy Strength"]
    land = _mk_card(name="W2G7 Field", type_line="Land")
    game = _w2g7_empty_board(aura, bf0=[land])

    result = game.cast_from_hand(
        0, aura.name, target_permanent_ids=[game.players[0].battlefield[0].permanent_id]
    )

    assert not result.supported
    assert "no valid target" in result.details
    assert [card.name for card in game.players[0].hand] == [aura.name]


def test_w2g7_an_aura_named_by_a_stale_id_is_refused_not_repointed(catalog_by_name):
    """An id that resolves to nothing names nothing. The refusal is the loud
    one it always was — never a fall back to whatever sits in slot 0."""
    aura = catalog_by_name["Holy Strength"]
    game = _w2g7_empty_board(aura, bf0=[_w2g7_creature("Gone"), _w2g7_creature("Bystander")])
    gone, bystander = game.players[0].battlefield
    stale = gone.permanent_id
    game.remove_from_battlefield(gone)

    result = game.cast_from_hand(0, aura.name, target_permanent_ids=[stale])

    assert not result.supported
    assert (bystander.effective_power, bystander.effective_toughness) == (1, 1)
    assert [card.name for card in game.players[0].hand] == [aura.name]


def _w2g7_bait() -> list:
    return [
        _mk_card(name="Bait Creature", type_line="Creature - Human Soldier", power=2, toughness=2),
        _mk_card(name="Bait Artifact", type_line="Artifact"),
        _mk_card(name="Bait Enchantment", type_line="Enchantment"),
        _mk_card(name="Bait Land", type_line="Land"),
        _mk_card(name="Bait Forest", type_line="Basic Land - Forest"),
        _mk_card(name="Bait Wall", type_line="Creature - Wall", power=0, toughness=4),
        _mk_card(name="Bait Golem", type_line="Artifact Creature - Golem", power=3, toughness=3),
    ]


def _w2g7_mirror(card) -> Game:
    game = _w2g7_empty_board(card, bf0=_w2g7_bait(), bf1=_w2g7_bait())
    game.start_turn(0)
    game.current_phase = "main"
    return game


def test_w2g7_every_shipped_aura_announced_by_id_alone_is_the_announcement_by_slot():
    """Every Aura in both manifest roles, one legal host per battlefield.

    Asserted on the **announcement**, for the reason Prophecy's activation
    sweep is: what the resolution reads is the stack item's seat and slot, and
    571 different Aura effects would be 571 chances to write the assertion the
    way the code already behaves. Queued, not cast, so the object is still
    there to look at.
    """
    measured, wrong = 0, []
    for card in _w2g7_pool().values():
        if card.primary_type in ("instant", "sorcery") or "Aura" not in card.type_line:
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        spec = derive_cast_spec(card, program)
        if (
            spec is None or spec_roles(spec) or spec_is_a_cost(spec)
            or spec.get("kind") in ("none", "modal", "hand_card", "graveyard_creature")
        ):
            continue
        offered = _w2g7_mirror(card)._enumerate_targets(0, card, dict(spec), for_cast=True)
        for seat in (0, 1):
            slot = next(
                (
                    entry["index"] for entry in offered
                    if entry.get("kind") == "permanent" and entry.get("seat") == seat
                ),
                None,
            )
            if slot is None:
                continue
            game = _w2g7_mirror(card)
            host = game.permanent_at(seat, slot)
            result = game.queue_from_hand(
                0, card.name, target_permanent_ids=[host.permanent_id]
            )
            measured += 1
            item = next(
                (obj for obj in game.stack if obj.card.name == card.name), None
            )
            if (
                not result.supported or item is None
                or (item.target_player_index, item.target_permanent_index) != (seat, slot)
            ):
                wrong.append(f"{card.name}@{seat}: {result.details}")
    assert not wrong, (
        f"{len(wrong)} of {measured} Aura casts named by id alone were refused "
        f"or announced at another slot: {sorted(wrong)[:12]}"
    )
    # 571 when this was written; every one was refused "requires a target".
    assert measured > 450, f"the sweep only examined {measured} announcements"


def test_w2g7_a_resolved_aura_named_by_id_is_attached_to_that_permanent(catalog_by_name):
    """One whole resolution behind the sweep's announcements: the host is read
    back off the Aura, by identity."""
    aura = catalog_by_name["Pacifism"]
    game = _w2g7_empty_board(
        aura, bf0=[_w2g7_creature("Mine")], bf1=[_w2g7_creature("Theirs")]
    )
    theirs = game.players[1].battlefield[0]

    assert game.cast_from_hand(0, aura.name, target_permanent_ids=[theirs.permanent_id]).supported
    resolve_stack(game)

    attached = next(p for p in game.all_permanents() if p.card.name == "Pacifism")
    assert attached_host(game, attached) is theirs
