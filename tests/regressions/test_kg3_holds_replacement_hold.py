"""Census: a CR 614 replacement offered during a resolution holds its stack
object, and suspends the steps behind its event — every kind on the queue.

The prompt queue held a resolution until its last answer (CR 608.2: an object
stays on the stack until it has finished resolving; CR 117.3b: nobody receives
priority meanwhile). The replacement queue (``engine/replacement_choices.py``)
did not. Its offers were never stamped with the object resolving as they were
made, ``choices_for_stack_item`` read only the prompt queue, and the answer ran
outside the envelope that releases an object — so, measured at the base of
round ``kg3``:

* Blood of the Martyr's "you may have that damage dealt to you instead" was
  answered after Shock had "resolved and moved to graveyard";
* Mind Twist finished resolving before Library of Leng's destination choice;
* Mox Diamond's spell had left the stack while its discard toll was owed;
* and, the second half, an owed offer did not suspend the resolution it was
  made in: Catalog ("Draw two cards, then discard a card") under Obstinate
  Familiar asked for its discard with both draws undecided, and Breathstealer's
  Crypt never revealed a card whose draw another replacement had offered.

For every kind registered on the CR 614 queue (``CHOICE_RESOLVERS``) a shipped
card makes the offer to an **interactive** seat from inside a resolving spell,
and the board asks: (a) while the offer is owed, is the object on the stack,
held, and is the offer one of the decisions it waits on; (b) has the log
claimed the resolution finished; (c) once every decision is answered, has the
object left the stack, having finished resolving. A draw's offer is made under
Catalog, so the same board asks (d): did the discard behind the draw wait for
the draw to be decided.

Validated backwards at the bottom: with the queue's reader switched back to
the prompt queue alone, or the CR 614 queue left out of what suspends a loop,
the census names every board.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pytest
from fastapi.testclient import TestClient

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.mixins.stack.choices.queue import PendingChoicesMixin
from engine.models import Permanent
from engine.replacement_choices import CHOICE_RESOLVERS
from web.app import app, store

_CARDS = {card.name: card for card in load_catalog()}
client = TestClient(app)


def card(name: str):
    return _CARDS[name]


def perm(name: str) -> Permanent:
    permanent = Permanent(card=card(name))
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def names(cards) -> list[str]:
    return [c.name for c in cards]


def duel(*, hands=((), ()), boards=((), ()), libraries=None, graveyards=None) -> Game:
    """Both seats interactive (every human seat on the web is), seat 0 active
    in its precombat main phase with priority, mana not enforced."""
    libraries = libraries or (("Island",) * 8, ("Island",) * 8)
    graveyards = graveyards or ((), ())
    players = [
        PlayerState(
            name=f"P{seat}",
            hand=[card(n) for n in hands[seat]],
            library=[card(n) for n in (libraries[seat] if seat < len(libraries) else ("Island",) * 8)],
            graveyard=[card(n) for n in (graveyards[seat] if seat < len(graveyards) else ())],
            battlefield=[perm(n) for n in boards[seat]],
        )
        for seat in range(2)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game._recompute_continuous_effects()
    game.start_priority_window(0)
    return game


def on_board(game: Game, seat: int, name: str) -> Permanent:
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


# ---------------------------------------------------------------------------
# One board per kind: a resolving spell makes the offer
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Board:
    kind: str
    card: str          # the card printing the replacement
    resolving: str     # the spell resolving as the offer is made
    arm: Callable[[], Game]
    draws: bool = False   # made under Catalog: (d) is asked too


BOARDS: dict[str, Board] = {}


def board(kind: str, card_name: str, resolving: str, *, draws: bool = False):
    def register(arm):
        assert kind not in BOARDS, kind
        BOARDS[kind] = Board(kind, card_name, resolving, arm, draws)
        return arm
    return register


@board("optional_damage_redirect", "Blood of the Martyr", "Shock")
def _blood_of_the_martyr():
    game = duel(hands=(("Blood of the Martyr", "Shock"), ()), boards=((), ("Grizzly Bears",)))
    game.cast_from_hand(0, "Blood of the Martyr")
    game.cast_from_hand(0, "Shock", target_permanent_ids=[
        on_board(game, 1, "Grizzly Bears").permanent_id
    ])
    return game


@board("leng_discard", "Library of Leng", "Mind Twist")
def _library_of_leng():
    game = duel(hands=(("Mind Twist",), ("Shock", "Grizzly Bears")), boards=((), ("Library of Leng",)))
    game.cast_from_hand(0, "Mind Twist", target_player_index=1, x_value=2)
    return game


@board("entry_discard_toll", "Mox Diamond", "Mox Diamond")
def _mox_diamond():
    game = duel(hands=(("Mox Diamond", "Forest"), ()))
    game.cast_from_hand(0, "Mox Diamond")
    return game


@board("commander_zone_change", "Gadrak, the Crown-Scourge (a commander)", "Unsummon")
def _a_commander_is_returned_to_hand():
    """CR 903.9b, the half that is a replacement and so is offered as the
    spell resolves: "if a commander would be put into its owner's hand …".
    (A dying commander is 903.9a's state-based action, offered at the check
    after the resolution, with nothing resolving to hold.)"""
    from engine.commander import COMMANDER

    gadrak = card("Gadrak, the Crown-Scourge")
    game = Game(
        players=[
            PlayerState(name="P0", library=[card("Mountain")] * 8, hand=[card("Unsummon")]),
            PlayerState(name="P1", library=[card("Mountain")] * 8),
        ],
        commander_variant=COMMANDER,
    )
    game.designate_commander(0, gadrak)
    game.designate_commander(1, card("Azusa, Lost but Seeking"))
    game.players[0].command_zone = [gadrak]
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.start_priority_window(0)
    game.cast_from_hand(0, gadrak.name, from_zone="command")
    game.cast_from_hand(0, "Unsummon", target_permanent_ids=[on_board(game, 0, gadrak.name).permanent_id])
    return game


def _catalog_under(boards=(), *, library=None, graveyard=(), armed=()) -> Game:
    game = duel(
        hands=(("Catalog", "Shock"), ()),
        boards=(tuple(boards), ()),
        libraries=(tuple(library or ("Grizzly Bears", "Forest", "Island", "Swamp", "Mountain")),
                   ("Island",) * 8),
        graveyards=(tuple(graveyard), ()),
    )
    game.players[0].sideboard = [card("Hill Giant"), card("Shock")]
    for name, kwargs in armed:
        artifact = on_board(game, 0, name)
        game.activate_permanent_ability(
            0, name, permanent_index=game.battlefield_index_of(artifact), **kwargs,
        )
        game._settle()
    game.cast_from_hand(0, "Catalog")
    return game


@board("skip_draw", "Obstinate Familiar", "Catalog", draws=True)
def _obstinate_familiar():
    return _catalog_under(("Obstinate Familiar",))


@board("pile_top_draw", "Parallel Thoughts", "Catalog", draws=True)
def _parallel_thoughts():
    """Scourge, still under ``measured`` when this row was written, so the
    enchantment is read off its own set file rather than the shipped catalog;
    its pile is the record its entry trigger writes, made here directly."""
    from engine.card_loader import load_cards, manifest_set_path
    from engine.linked_exile import link_exiled_card

    thoughts = next(
        c for c in load_cards(manifest_set_path("SCG", include_measured=True))
        if c.name == "Parallel Thoughts"
    )
    game = duel(
        hands=(("Catalog", "Shock"), ()),
        libraries=(("Grizzly Bears", "Forest", "Island", "Swamp", "Mountain"),
                   ("Island",) * 8),
    )
    permanent = Permanent(card=thoughts)
    game.players[0].battlefield.append(permanent)
    for name in ("Hill Giant", "Shock"):
        game.players[0].exile.append(card(name))
        link_exiled_card(permanent, card(name), 0, face_down=True)
    game._recompute_continuous_effects()
    game.cast_from_hand(0, "Catalog")
    return game


@board("opponent_library_draw", "Shared Fate", "Catalog", draws=True)
def _shared_fate():
    """Mirrodin, still under ``measured`` when this row was written, so the
    enchantment is read off its own set file. Three seats, because the offer
    — whose library the drawer exiles from — is made only to a drawer with
    two or more opponents."""
    from engine.card_loader import load_cards, manifest_set_path

    fate = next(
        c for c in load_cards(manifest_set_path("MRD", include_measured=True))
        if c.name == "Shared Fate"
    )
    players = [
        PlayerState(
            name=f"P{seat}",
            hand=[card("Catalog"), card("Shock")] if seat == 0 else [],
            library=[card("Island")] * 8,
        )
        for seat in range(3)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1, 2}
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game._put_permanent_onto_battlefield(0, Permanent(card=fate), None)
    game._recompute_continuous_effects()
    game.start_priority_window(0)
    game.cast_from_hand(0, "Catalog")
    return game


@board("draw_becomes_counter", "Pursuit of Knowledge", "Catalog", draws=True)
def _pursuit_of_knowledge():
    return _catalog_under(("Pursuit of Knowledge",))


@board("reveal_until_kind_draw", "Abundance", "Catalog", draws=True)
def _abundance():
    return _catalog_under(("Abundance",))


@board("return_from_graveyard_instead_of_draw", "Forbidden Crypt", "Catalog", draws=True)
def _forbidden_crypt():
    return _catalog_under(("Forbidden Crypt",), graveyard=("Shock", "Grizzly Bears", "Forest"))


@board("lamp_draw", "Aladdin's Lamp", "Catalog", draws=True)
def _aladdins_lamp():
    return _catalog_under(("Aladdin's Lamp",), armed=(("Aladdin's Lamp", {"x_value": 2}),))


@board("outside_game_draw", "Ring of Ma'rûf", "Catalog", draws=True)
def _ring_of_maruf():
    return _catalog_under(("Ring of Ma'rûf",), armed=(("Ring of Ma'rûf", {}),))


# ---------------------------------------------------------------------------
# What is asked of every board
# ---------------------------------------------------------------------------

def _held(game: Game, name: str):
    return next((item for item in game.stack if item.card.name == name), None)


def _owed_offers(game: Game, kind: str) -> list:
    return [c for c in game.pending_replacement_choices if c.kind == kind]


def _answer_one(game: Game) -> bool:
    """Answer the oldest decision owed, with the default its kind gives — the
    CR 614 queue first, through its own answer path."""
    if game.pending_replacement_choices:
        choice = game.pending_replacement_choices[0]
        return game.resolve_replacement_choice(
            choice.player_index, choice.default_option, kind=choice.kind
        )
    owed = [choice for _spec, choice in game.iter_pending_prompts()]
    if owed:
        game.auto_resolve_choice(owed[0])
        return True
    return False


def faults(b: Board) -> list[str]:
    """Every way *b*'s resolution went on around its owed offer."""
    game = b.arm()
    problems: list[str] = []
    offers = _owed_offers(game, b.kind)
    if not offers:
        return [f"no {b.kind} offer owed: {game.log[-5:]}"]
    held = _held(game, b.resolving)
    # (a) the object waits on the stack for the offer
    if held is None:
        problems.append(f"(a) {b.resolving} is not on the stack while {b.kind} is owed")
    else:
        if not held.resolution_held:
            problems.append(f"(a) {b.resolving} is on the stack but not held")
        waiting_on = game.choices_for_stack_item(held)
        if not any(offer is owed for offer in offers for owed in waiting_on):
            problems.append(f"(a) {b.resolving} does not wait on the {b.kind} offer")
    # (b) nothing has claimed the resolution is over
    for line in game.log:
        if line.startswith(f"{b.resolving} finished resolving") or line.startswith(
            f"{b.resolving} resolved and moved to"
        ):
            problems.append(f"(b) the log already says {line!r}")
    # (d) under Catalog: the discard behind the draws waits for them
    if b.draws and game.pending_choice_of("discard") is not None:
        problems.append("(d) the discard behind the draw was asked before the draw was decided")
    # Every decision answered, one at a time; the object stays while one of
    # its offers is owed, and only the last answer lets it go.
    for _ in range(20):
        if held is not None and _owed_offers(game, b.kind) and _held(game, b.resolving) is None:
            problems.append(f"(a) {b.resolving} left the stack with a {b.kind} offer still owed")
            break
        if b.draws and _owed_offers(game, b.kind) and game.pending_choice_of("discard") is not None:
            problems.append("(d) a discard was asked with a draw still undecided")
            break
        if not _answer_one(game):
            break
    # (c) it finished, once, at the end
    if _held(game, b.resolving) is not None:
        problems.append(f"(c) {b.resolving} is still on the stack with nothing owed")
    if not any(line.startswith(f"{b.resolving} finished resolving") for line in game.log):
        problems.append(f"(c) {b.resolving} never finished resolving: {game.log[-4:]}")
    return problems


#: The CR 614 queue's kinds, every one driven here. A registry that lost its
#: kinds, or a table that lost its boards, would pass by examining nothing.
#: Measured at round ``kg3``: 10 of 10.
_KINDS_FLOOR = 10


def test_every_kind_on_the_queue_is_driven():
    assert set(BOARDS) == set(CHOICE_RESOLVERS), (
        sorted(set(CHOICE_RESOLVERS) ^ set(BOARDS))
    )
    assert len(BOARDS) >= _KINDS_FLOOR


@pytest.mark.parametrize("kind", sorted(BOARDS))
def test_the_offer_holds_its_object_until_the_last_answer(kind):
    assert faults(BOARDS[kind]) == [], kind


def test_on_the_wire_the_spell_is_on_the_stack_while_the_offer_is_owed():
    """What a client is served while Blood of the Martyr's offer is owed:
    Shock, still resolving — and nothing once the answer lets it finish."""
    game = BOARDS["optional_damage_redirect"].arm()
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "H", "guest_name": "G",
        "host_colors": 2, "guest_colors": 2, "seed": 2600,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "G"})
    session = store.get(sid)
    session.pregame_phase = None
    session.current_turn = 0
    session.joined_seats = {0, 1}
    session.game = game

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    assert [entry["label"] for entry in state["stack"]] == ["Shock"]
    answered = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "optional_damage_redirect_confirm", "take_the_damage": True,
    })
    assert answered.status_code == 200, answered.text
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    assert state["stack"] == []
    assert game.players[0].life == 18
    assert "Shock finished resolving and moved to graveyard" in game.log


# ---------------------------------------------------------------------------
# The fused draws: a step behind a draw inside one handler
# ---------------------------------------------------------------------------

def test_breathstealers_crypt_reveals_the_card_another_replacements_answer_drew():
    """Breathstealer's Crypt's draw goes back through the seam, where Obstinate
    Familiar offers to skip it. Answered "draw", the card arrives — and is
    revealed and taxed. Run straight through, the hand had not grown when the
    Crypt looked, and the creature was kept for free."""
    game = duel(
        hands=(("Catalog",), ()),
        boards=(("Obstinate Familiar", "Breathstealer's Crypt"), ()),
        libraries=(("Grizzly Bears", "Hill Giant", "Swamp", "Mountain"), ("Island",) * 8),
    )
    game.cast_from_hand(0, "Catalog")
    order = game.pending_choice_of("effect_order", 0)
    assert order is not None
    crypt_first = next(
        i for i, label in enumerate(order.data["options"]) if "Crypt" in label
    )
    assert game.resolve_pending_choice("effect_order", 0, option_index=crypt_first)
    assert _owed_offers(game, "skip_draw")
    assert game.confirm_skip_draw(0, False)

    assert "P0 drew and revealed Grizzly Bears (Breathstealer's Crypt)" in game.log
    taxed = game.pending_choice_of("discard_unless_pay_life", 0)
    assert taxed is not None and taxed.data.get("card_name") == "Grizzly Bears"
    assert _held(game, "Catalog") is not None


def test_sindbad_reveals_the_card_its_draws_offer_drew():
    """Sindbad: "Draw a card and reveal it. If it isn't a land card, discard
    it." Under Obstinate Familiar the draw is offered first; answered "draw",
    the card is revealed and, a creature, discarded."""
    game = duel(
        boards=(("Sindbad", "Obstinate Familiar"), ()),
        libraries=(("Grizzly Bears", "Forest", "Island"), ("Island",) * 8),
    )
    sindbad = on_board(game, 0, "Sindbad")
    game.activate_permanent_ability(0, "Sindbad", permanent_index=game.battlefield_index_of(sindbad))
    game._settle()
    assert _owed_offers(game, "skip_draw")
    assert not any("drew nothing to reveal" in line for line in game.log)
    assert game.confirm_skip_draw(0, False)

    assert "Sindbad: P0 drew and revealed Grizzly Bears" in game.log
    assert names(game.players[0].graveyard) == ["Grizzly Bears"]
    assert game.players[0].hand == []


# ---------------------------------------------------------------------------
# Backwards: the defect put back
# ---------------------------------------------------------------------------

def _prompt_queue_only(self, item):
    return [c for c in self.pending_choices if c.data.get("_stack_item") is item]


def test_with_the_reader_on_the_prompt_queue_alone_the_census_names_every_board(monkeypatch):
    monkeypatch.setattr(PendingChoicesMixin, "choices_for_stack_item", _prompt_queue_only)
    named = {kind for kind, b in BOARDS.items() if faults(b)}
    assert named == set(BOARDS), sorted(set(BOARDS) - named)


def test_with_the_offers_left_out_of_what_suspends_the_draws_run_on(monkeypatch):
    from engine.pending_choices import spec_for

    def prompt_queue_suspensions(self):
        return tuple(
            choice for choice in self.pending_choices
            if spec_for(choice.kind).suspends and not choice.data.get("_answered")
        )

    monkeypatch.setattr(PendingChoicesMixin, "owed_suspensions", prompt_queue_suspensions)
    named = {
        kind for kind, b in BOARDS.items()
        if b.draws and any(fault.startswith("(d)") for fault in faults(b))
    }
    drawn = {kind for kind, b in BOARDS.items() if b.draws}
    assert len(drawn) >= 6
    assert named == drawn, sorted(drawn - named)
