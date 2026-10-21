"""Flashback (CR 702.34).

CR 702.34a: "'Flashback [cost]' means 'You may cast this card from your
graveyard if the resulting spell is an instant or sorcery spell by paying
[cost] rather than paying its mana cost' and 'If the flashback cost was paid,
exile this card instead of putting it anywhere else any time it would leave
the stack.' Casting a spell using its flashback ability follows the rules for
paying alternative costs in rules 601.2b and 601.2f–h."

Three things the engine already had and had never joined — a permission to
cast from a zone (CR 601.3), an alternative cost that permission requires
(CR 118.9b) and a destination for the card as it leaves the stack — which is
why most of this file is a **census** rather than a list of cases: every card
in the pool printing the keyword is cast from a graveyard and held to what the
same card does cast from a hand, and every way the pool has of taking a spell
off the stack is tried against a flashed-back one.

The pool is both manifest roles. A measured set is exactly the population the
keyword has to be right about when it ships — and the day this file was
written, every card printing it was in one.
"""
from __future__ import annotations

import random
import re
from functools import lru_cache

import pytest

import engine.handlers.stack as stack_handlers
from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units, whole_card
from engine.cast_permissions import (expire_end_of_turn, grant_permission,
                                     permission_for, playable_from_zones)
from engine.flashback import (FLASHBACK_RULES_TEXT, expand_flashback_line,
                              flashback_claims_line, has_flashback,
                              is_flashback_line, printed_flashback_cost,
                              unread_flashback_line)
from engine.mana_payment import mana_cost_from_symbols
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle, expand_card_lines
from engine.targeting import CAST_FROM_GRAVEYARD, derive_cast_spec
from tests.helpers import _damage_dealt, _nosick, declare_attack, resolve_stack


# ---------------------------------------------------------------------------
# The pool, the board and the announcement
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _pool() -> dict:
    """Every card of both manifest roles by name, first printing winning."""
    names: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            names.setdefault(card.name, card)
    return names


@lru_cache(maxsize=None)
def _flashback_names() -> tuple[str, ...]:
    return tuple(sorted(
        name for name, card in _pool().items()
        if printed_flashback_cost(card) is not None
    ))


def _mk(name: str, mana_cost: str, type_line: str, oracle_text: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost=mana_cost, cmc=1.0, type_line=type_line,
        oracle_text=oracle_text, colors=("R",), color_identity=("R",),
        keywords=(), produced_mana=(), raw={},
    )


#: The X every census cast of a card printing {X} announces, and pays at.
_CENSUS_X = 2


def _pay(player, cost: str, short: int = 0) -> None:
    """Put exactly *cost* in *player*'s pool (generic as colourless), less
    *short* units — so a cast that succeeds leaves nothing behind and a cast
    one mana short has nothing to make it up from. An {X} is priced at
    :data:`_CENSUS_X`, the value :func:`_announce` announces."""
    wanted = mana_cost_from_symbols(
        re.sub(r"\{X\}", "{%d}" % _CENSUS_X, cost, flags=re.I)
    ) or {}
    pool = {symbol: 0 for symbol in "WUBRGC"}
    for symbol, count in wanted.items():
        pool["C" if symbol == "generic" else symbol] += count
    for symbol in "CWUBRG":
        if short and pool[symbol] >= short:
            pool[symbol] -= short
            break
    player.mana_pool.update(pool)


def _board(card=None, *, zone: str | None = None) -> Game:
    """A mirrored two-seat board on which every flashback card in the pool has
    a legal announcement and an effect a snapshot can see.

    Each side: a tapped Grizzly Bears (so an untap shows), a Serra Angel (so a
    sweep that reads flying has one of each), a Sol Ring and a Forest; a
    graveyard of a creature card, a sorcery card and a land card; a library a
    basic land can be found in; one card in hand to discard.

    *card* goes into seat 0's *zone* — and into a graveyard **first**, under
    the cards a graveyard-target spell would choose, so the slot it announces
    is one its own departure moves (see the last section of this file).
    """
    by_name = _pool()
    players = []
    for name in ("P1", "P2"):
        battlefield = [
            _nosick(Permanent(card=by_name[n]))
            for n in ("Grizzly Bears", "Serra Angel", "Sol Ring", "Forest")
        ]
        battlefield[0].tapped = True
        players.append(PlayerState(
            name=name, battlefield=battlefield,
            graveyard=[by_name[n] for n in ("Grizzly Bears", "Mind Rot", "Forest")],
            library=[by_name[n] for n in ("Forest", "Grizzly Bears", "Forest", "Sol Ring")],
            hand=[by_name["Island"]],
        ))
    game = Game(players=players)
    game.enforce_mana_costs = True
    if card is not None and zone == "hand":
        game.players[0].hand.append(card)
    elif card is not None and zone == "graveyard":
        game.players[0].graveyard.insert(0, card)
    return game


def _something_to_counter(game) -> None:
    """Seat 1 puts a Grizzly Bears on the stack, for a counterspell to name."""
    game.players[1].hand.append(_pool()["Grizzly Bears"])
    game.players[1].mana_pool["G"] = 2
    assert game.queue_from_hand(1, "Grizzly Bears").supported


def _something_in_combat(game) -> None:
    """Seat 1 attacks with what it can (its Serra Angel), for a spell that
    names "target attacking or blocking creature" (Spirit Flare).

    The mirrored board is a main phase with nothing fighting, so a role that
    only a creature in combat can fill had nothing to announce — the census
    assumed every flashback card's targets were on the board before any
    combat, which held until Torment printed one that is not. The fight is
    real (``declare_attack``: seat 1's turn, declare blockers, damage still to
    be dealt) and it is set up before the "before" snapshot, on both boards
    alike."""
    declare_attack(game, 1)


#: A colour word used as a colour word, on a permanent that does nothing by
#: itself: Black Knight's "protection from white".
_REWRITTEN = ("Black Knight", "W", "B")


def _something_to_rewrite(game, card, zone: str) -> dict:
    """Seat 1 gets a Black Knight, and a colour-word text change (Alter
    Reality) is announced at it replacing white with black.

    A text change rewrites words that are on the permanent and nothing else
    (CR 612.2), and the mirrored board prints no colour word anywhere — so
    Alter Reality aimed at whatever its picker offered first changed nothing,
    and this census could not tell that from a spell that does nothing. The
    words are named the way a headless cast names them (``old_color`` /
    ``new_color``), and the Knight is announced only once its own picker has
    offered it."""
    name, old, new = _REWRITTEN
    game.players[1].battlefield.append(_nosick(Permanent(card=_pool()[name])))
    spec = game.cast_target_spec(0, card, from_zone=zone)
    entry = next(
        entry for entry in spec.get("valid_targets") or ()
        if entry.get("kind") == "permanent" and entry["seat"] == 1 and entry["name"] == name
    )
    knight = game.permanent_at(1, entry["index"])
    return {
        "target_permanent_ids": [knight.permanent_id], "target_player_index": 1,
        "old_color": old, "new_color": new,
    }


def _rewrites_color_words(card) -> bool:
    return any(
        instruction.kind == "mark_text_modified" and instruction.payload.get("mode") == "color_word"
        for instruction in compile_card_oracle(card).instructions
    )


def _role_refs(game, entries: list) -> list[dict]:
    """The first path through a roles picker (each entry's ``next`` is the
    list for the role after it), as ``target_role_refs``."""
    refs = []
    while entries:
        entry = entries[0]
        if entry.get("kind") == "permanent":
            refs.append({"permanent_id": game.permanent_at(entry["seat"], entry["index"]).permanent_id})
        elif entry.get("kind") == "player":
            refs.append({"seat": entry["seat"]})
        else:
            raise AssertionError(f"a role this census cannot announce: {entry}")
        entries = entry.get("next") or []
    return refs


def _announce(game, card, zone: str) -> dict:
    """:func:`_announce_targets`, and an X for a card printing {X}.

    "Flashback {X}{R}{R}" over "{X}{R}" (Flaming Gambit, Torment): the census
    announced no X, paid no X and so cast every X spell for 0 — which for a
    card whose X is its whole effect is a cast that moves nothing. CR 601.2b
    announces X with the cast, so both casts announce :data:`_CENSUS_X` and
    :func:`_pay` prices the {X} at it.
    """
    if _acts_on_creature_tokens(card):
        _creature_tokens_to_act_on(game)
    keywords = _announce_targets(game, card, zone)
    cost = printed_flashback_cost(card)
    if "{X}" in (card.mana_cost or "").upper() or "{X}" in ((cost.mana if cost else "") or "").upper():
        keywords = {**keywords, "x_value": _CENSUS_X}
    return keywords


#: "For each creature token on the battlefield, its controller creates a token
#: that's a copy of that creature." (Parallel Evolution, Torment.) A card whose
#: effect is about creature tokens already on the battlefield, by its printed
#: words — the mirrored board has none.
_ACTS_ON_CREATURE_TOKENS = re.compile(r"creature tokens? on the battlefield", re.I)


def _acts_on_creature_tokens(card) -> bool:
    return bool(_ACTS_ON_CREATURE_TOKENS.search(card.oracle_text or ""))


def _creature_tokens_to_act_on(game) -> None:
    """Each seat gets a 1/1 green Squirrel creature token, for a card that
    acts on the creature tokens on the battlefield (Parallel Evolution).

    The mirrored board holds no token, so a correct Parallel Evolution copied
    nothing and the census read it as a card that does nothing ("resolved and
    nothing moved") — the Alter Reality row's kind exactly: a board that
    cannot show what the card does. Put down on both boards alike, before the
    "before" snapshot, so the hand cast and the flashed-back one compare the
    same thing. A token is a token by its *permanent*: the matcher asks
    ``Permanent.metadata["is_token"]``, which the engine's own token maker sets
    (``handlers/board_misc``); ``tokens.make_token_card`` marks the card, which is
    what a token is once the permanent is gone."""
    from engine.tokens import make_token_card

    for seat in (0, 1):
        game.players[seat].battlefield.append(_nosick(Permanent(card=make_token_card(
            "Squirrel Token", 1, 1, "Creature — Squirrel", colors=("G",),
        ), metadata={"is_token": True})))


def _announce_targets(game, card, zone: str) -> dict:
    """The first target *card*'s own picker offers, as cast keywords.

    Off ``cast_target_spec`` for the zone the cast leaves — the list a client
    is handed for that copy of the card — so what is announced is something
    the engine itself said was legal, formed before the code under test runs.
    """
    if derive_cast_spec(card, compile_card_oracle(card), from_zone=zone) is None:
        return {}
    if _rewrites_color_words(card):
        return _something_to_rewrite(game, card, zone)
    spec = game.cast_target_spec(0, card, from_zone=zone)
    if spec.get("kind") == "stack":
        _something_to_counter(game)
        spec = game.cast_target_spec(0, card, from_zone=zone)
    if spec.get("kind") == "roles":
        if not spec.get("valid_targets") and any(
            role.get("any_states") for role in spec.get("roles") or ()
        ):
            _something_in_combat(game)
            spec = game.cast_target_spec(0, card, from_zone=zone)
        refs = _role_refs(game, spec.get("valid_targets") or [])
        if refs:
            return {"target_role_refs": refs}
    if spec.get("kind") == "divided":
        # The whole amount at the opposing player: a lawful division of one.
        return {"divided_targets": [(1, None, int(spec["division_total"]))]}
    # The opposing side first, for a player or a permanent: "deals 3 damage to
    # any target, you gain 3 life" aimed at its own caster moves nothing, and
    # the census below has to be able to see that a cast did something. A
    # graveyard card keeps the picker's order, which starts in the caster's
    # own pile — the pile the spell itself is leaving.
    offered = sorted(
        spec.get("valid_targets") or [],
        key=lambda entry: entry.get("kind") != "graveyard" and entry.get("seat") != 1,
    )
    for entry in offered:
        kind = entry.get("kind")
        if kind == "permanent":
            permanent = game.permanent_at(entry["seat"], entry["index"])
            return {
                "target_permanent_ids": [permanent.permanent_id],
                "target_player_index": entry["seat"],
            }
        if kind == "player":
            return {"target_player_index": entry["seat"]}
        if kind == "graveyard":
            return {
                "target_player_index": entry["seat"],
                "target_permanent_index": entry["index"],
            }
        if kind == "stack":
            return {"target_stack_index": len(game.stack) - 1 - entry["stack_index"]}
    raise AssertionError(f"the board offers {card.name} nothing to announce: {spec}")


def _settle(game) -> None:
    """Resolve the stack and answer what the resolution asked (a discard, a
    library search) with the registry's own defaults."""
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game.auto_resolve_pending_replacement_choices()
    resolve_stack(game)


def _where(game, card) -> list[str]:
    """Every zone holding *card* — by identity, so a second copy would show."""
    found = []
    for seat, player in enumerate(game.players):
        for zone in ("hand", "graveyard", "exile", "library"):
            found += [f"P{seat + 1}.{zone}"] * sum(
                1 for held in getattr(player, zone) if held is card
            )
    found += ["stack"] * sum(1 for item in game.stack if item.card is card)
    return found


def _snapshot(game, card) -> tuple:
    """Everything a flashback card in this pool can change, bar where the card
    itself is.

    The damage probes come last and are part of the answer: a prevention
    shield (Embolden, Moment's Peace) is visible only as damage that did not
    arrive, so each seat is dealt 3 of each kind and what got through is
    recorded. So is each permanent's text as layer 3 leaves it: a text change
    (Alter Reality) is visible nowhere else.
    """
    def names(zone) -> list[str]:
        return sorted(held.name for held in zone if held is not card)

    seats = []
    for seat, player in enumerate(game.players):
        board = sorted(
            (
                perm.card.name, perm.effective_power, perm.effective_toughness,
                perm.tapped, perm.damage_marked,
                tuple(k for k in ("haste", "trample") if game._has_keyword(perm, k)),
                bool(perm.metadata.get("cant_be_regenerated_this_turn")),
                perm.effective_card.oracle_text,
            )
            for perm in game.controlled_by(seat)
        )
        seats.append((
            player.life, names(player.hand), names(player.graveyard),
            names(player.exile), names(player.library), board,
        ))
    grants = sorted(
        (permission.cards[0].name, permission.cost.mana, permission.duration)
        for permission in game.cast_permissions
        if permission.cards and permission.cost is not None
    )
    probes = tuple(
        (_damage_dealt(game, player, 3), _damage_dealt(game, player, 3, combat=True))
        for player in game.players
    )
    # W1G7 (TOR): a one-turn rule a resolving spell leaves on the game —
    # Flash of Defiance's "can't block this turn" — is in no zone, on no
    # permanent and in no shield, so without this the census read it as a
    # spell that moved nothing.
    rules = tuple(
        repr(entry)
        for entry in game.blocking_restrictions_until_eot + game.attack_restrictions_until_eot
    )
    return (tuple(seats), tuple(game.extra_phases_remaining()), tuple(grants), probes, rules)


def _cast_and_settle(card, zone: str):
    """Cast *card* out of seat 0's *zone* on a fresh board, for exactly what
    that cast costs. Returns ``(game, result, snapshot before)``."""
    random.seed(7)   # a library search shuffles; both casts must shuffle alike
    game = _board(card, zone=zone)
    keywords = _announce(game, card, zone)
    before = _snapshot(game, card)
    cost = card.mana_cost if zone == "hand" else printed_flashback_cost(card).mana
    _pay(game.players[0], cost)
    result = game.cast_from_hand(0, card.name, from_zone=zone, **keywords)
    _settle(game)
    return game, result, before


#: What an ``AlternativeCost`` charges beside its mana that this census can
#: predict, by field. Every other field must hold its default.
_PREDICTED_CHARGES = ("pay_life",)
_NOT_A_CHARGE = ("phrase", "mana", "keyword")


def _less_what_the_flashback_cost_charged(after_hand: tuple, card) -> tuple:
    """The hand cast's snapshot, less what the flashback cost takes beyond its
    mana: what the flashed-back cast must leave.

    Torment prints "Flashback—{1}{G}, Pay 3 life." (Acorn Harvest, Crippling
    Fatigue, Deep Analysis, Flash of Defiance, Spirit Flare). Until it was
    measured every flashback cost in the pool was mana alone and this census
    compared the two boards whole — so three cards that pay their 3 life
    correctly read as 17 life where the hand cast read 20. The comparison
    assumed less than the pool holds; the 3 life is the cost (CR 118.9,
    CR 119.4), and seat 0 is the payer. A charge this census cannot predict
    fails here by name rather than as a board that merely differs.
    """
    from dataclasses import fields

    cost = printed_flashback_cost(card)
    unpredicted = {
        field.name: getattr(cost, field.name) for field in fields(cost)
        if field.name not in _PREDICTED_CHARGES + _NOT_A_CHARGE
        and getattr(cost, field.name) != field.default
    }
    assert not unpredicted, f"{card.name}'s flashback cost also charges {unpredicted}"
    seats, *rest = after_hand
    life, *zones = seats[0]
    return ((life - cost.pay_life, *zones), *seats[1:]), *rest


# ---------------------------------------------------------------------------
# The rewrite (CR 702.34a's first sentence)
# ---------------------------------------------------------------------------

@pytest.mark.cr("702.34a")
def test_702_34a_a_flashback_line_is_rewritten_into_the_rule_s_own_sentence():
    printed = (
        "Flashback {4}{R} (You may cast this card from your graveyard for its "
        "flashback cost. Then exile it.)"
    )
    assert is_flashback_line(printed)
    rewritten = expand_flashback_line(printed)
    assert rewritten == FLASHBACK_RULES_TEXT.format(cost="{4}{R}")
    assert flashback_claims_line(rewritten)
    # The keyword is gone by the time any reader sees the card, and the cost
    # that sentence names is an alternative cost paid in mana.
    firebolt = _pool()["Firebolt"]
    assert rewritten in expand_card_lines(firebolt)
    cost = printed_flashback_cost(firebolt)
    assert (cost.mana, cost.keyword) == ("{4}{R}", "flashback")
    assert unread_flashback_line("\n".join(expand_card_lines(firebolt))) is None


@pytest.mark.cr("702.34a")
def test_702_34a_a_sentence_about_flashback_costs_is_not_a_flashback_line():
    """"Flashback costs you pay cost {2} less." (Catalyst Stone) opens on the
    word and is a static ability about other cards' costs — read as a keyword
    line it would be a cost nothing can charge, and the card would be refused
    for a line another table implements in full."""
    for line in _pool()["Catalyst Stone"].oracle_text.split("\n"):
        assert not is_flashback_line(line), line
        assert expand_flashback_line(line) is None


@pytest.mark.cr("702.34a")
@pytest.mark.parametrize("line, why", [
    ("Flashback {X}{R}", "an X no announcement supplies"),
    ("Flashback—Dance a jig.", "a clause the cost reader cannot charge"),
    ("Flashback—{1}{G}, Dance a jig.", "one unread clause refuses the whole cost"),
])
def test_702_34a_a_flashback_cost_nothing_can_charge_refuses_the_card(line, why):
    """A spell is supported when any of its lines is, so a keyword line the
    rewrite could not read would simply be dropped — which is what all 27 of
    Odyssey's were before the rewrite existed. The gate names it instead."""
    card = _mk("Test Unread", "{R}", "Instant", f"Test Unread deals 1 damage to any target.\n{line}")
    program = compile_card_oracle(card)
    assert not program.supported, why
    assert "flashback" in program.reason and line.rstrip(".") in program.reason


@pytest.mark.cr("702.34a")
def test_702_34a_being_castable_twice_is_not_evidence_the_card_does_anything():
    """The claim is about how the card may be cast, not about what the spell
    does: a flashback card whose effect line nothing reads stays unsupported."""
    card = _mk("Test Hollow", "{R}", "Sorcery", "Frobnicate the wibble.\nFlashback {1}{R}")
    program = compile_card_oracle(card)
    assert not program.supported
    assert "flashback" not in program.reason


@pytest.mark.cr("702.34a")
def test_702_34a_a_permanent_is_not_held_up_by_a_flashback_line():
    """The claim is in ``oracle._TIMING_ONLY_CLAIMS`` for the reason the two
    beside it are: it says how a card may be cast, and on a permanent whose
    only line is that, there is nothing anyone could point at as the card
    working. (No such card is printed — the keyword "appears on some instants
    and sorceries" — which is why the mechanism is asked of an invented one.)"""
    from engine.oracle import _TIMING_ONLY_CLAIMS, _compile_card_oracle

    assert "flashback" in _TIMING_ONLY_CLAIMS
    program = _compile_card_oracle(
        "Test Relic", "artifact", "Flashback {1}{R}", (), "normal", False,
    )
    assert not program.supported, program.reason
    assert "no ability of this permanent is implemented" in program.reason


@pytest.mark.cr("702.34a")
def test_702_34a_every_flashback_card_in_the_pool_is_read():
    """The floor under every census below, and the keyword's own claim: each
    card printing the word compiles, carries the claim, and says what it
    costs. Twenty-eight on the day Odyssey was measured."""
    names = _flashback_names()
    assert len(names) >= 28, names
    for name in names:
        card = _pool()[name]
        program = compile_card_oracle(card)
        assert program.supported, (name, program.reason)
        assert any(
            instruction.kind == "derived_static_rule" and instruction.value == "flashback"
            for instruction in program.instructions
        ), name
        assert has_flashback(card)
    # Every unit whose text compiles — a half of a split card is where its
    # keyword line would be printed.
    printing_the_word = [
        unit.name for unit in compilation_units(_pool().values())
        if any(is_flashback_line(line) for line in (unit.oracle_text or "").split("\n"))
    ]
    assert sorted(printing_the_word) == list(names), "a flashback line nothing reads"


# ---------------------------------------------------------------------------
# The census: every flashback card, cast both ways
# ---------------------------------------------------------------------------

@pytest.mark.cr("702.34a", "601.2a", "608.2n")
@pytest.mark.parametrize("name", _flashback_names())
def test_702_34a_flashed_back_a_card_does_what_it_does_from_hand_and_is_exiled(name):
    """Cast from a hand for its mana cost and from a graveyard for its
    flashback cost on two identical boards, the two casts leave the same game
    behind — every zone, every permanent, every shield — except for where the
    card is: its owner's graveyard after the first, exile after the second.

    The comparison is the whole card's text, driven by whatever its own picker
    offers. It does not say what the card *should* do (the per-set files do);
    it says the half that was missing does all of it. The one difference
    allowed is what the flashback cost itself charges beyond mana (Torment's
    "Pay 3 life").
    """
    card = _pool()[name]
    from_hand, cast, before = _cast_and_settle(card, "hand")
    assert cast.supported, cast.details
    assert _where(from_hand, card) == ["P1.graveyard"]
    assert not any(from_hand.players[0].mana_pool.values()), "the mana cost was not what was paid"
    after_hand = _snapshot(from_hand, card)
    # Not vacuous: the cast changed something a snapshot can see.
    assert after_hand != before, f"{name} resolved and nothing moved"

    flashed, cast, _ = _cast_and_settle(card, "graveyard")
    assert cast.supported, cast.details
    assert _where(flashed, card) == ["P1.exile"]
    assert not any(flashed.players[0].mana_pool.values()), "the flashback cost was not what was paid"
    assert _snapshot(flashed, card) == _less_what_the_flashback_cost_charged(after_hand, card)


@pytest.mark.cr("702.34a", "601.2h")
@pytest.mark.parametrize("name", _flashback_names())
def test_702_34a_a_flashback_cost_that_cannot_be_paid_is_a_spell_that_is_not_cast(name):
    """One mana short of the flashback cost — even where that is enough for the
    card's *mana* cost — the cast is refused with nothing spent and the card
    still in the graveyard."""
    card = _pool()[name]
    game = _board(card, zone="graveyard")
    keywords = _announce(game, card, "graveyard")
    stack_before = len(game.stack)
    _pay(game.players[0], printed_flashback_cost(card).mana, short=1)
    pool_before = dict(game.players[0].mana_pool)
    result = game.cast_from_hand(0, name, from_zone="graveyard", **keywords)
    assert not result.supported
    assert "flashback cost" in result.details
    assert _where(game, card) == ["P1.graveyard"]
    assert game.players[0].mana_pool == pool_before
    assert len(game.stack) == stack_before


@pytest.mark.cr("702.34a", "701.6a")
@pytest.mark.parametrize("name", _flashback_names())
def test_702_34a_a_flashed_back_spell_that_is_countered_is_exiled(name):
    card = _pool()[name]
    game = _board(card, zone="graveyard")
    keywords = _announce(game, card, "graveyard")
    _pay(game.players[0], printed_flashback_cost(card).mana)
    assert game.queue_from_hand(0, name, from_zone="graveyard", **keywords).supported
    item = next(i for i, obj in enumerate(game.stack) if obj.card is card)
    assert game.stack[item].flashback and game.stack[item].cast_from_zone == "graveyard"
    game.players[1].hand.append(_pool()["Counterspell"])
    game.players[1].mana_pool["U"] = 2
    assert game.cast_from_hand(1, "Counterspell", target_stack_index=item).supported
    _settle(game)
    assert _where(game, card) == ["P1.exile"]


# ---------------------------------------------------------------------------
# Whose card, from where, under which permission (CR 601.3, CR 118.9)
# ---------------------------------------------------------------------------

@pytest.mark.cr("702.34a", "601.3")
def test_702_34a_only_its_owner_may_flash_a_card_back():
    """"You may cast this card from **your** graveyard": the permission is the
    card's owner's (a graveyard is an owner's zone, CR 404.1) and nobody
    else's — and nobody's at all once the card is anywhere else."""
    firebolt = _pool()["Firebolt"]
    game = _board(firebolt, zone="graveyard")
    assert permission_for(game, 0, firebolt, "graveyard").cost.mana == "{4}{R}"
    assert permission_for(game, 1, firebolt, "graveyard") is None
    assert [entry["name"] for entry in playable_from_zones(game, 0)] == ["Firebolt"]
    assert playable_from_zones(game, 1) == []
    # In exile it is a card with a keyword that functions somewhere else.
    game.players[0].graveyard.remove(firebolt)
    game.players[0].exile.append(firebolt)
    assert permission_for(game, 0, firebolt, "exile") is None
    assert playable_from_zones(game, 0) == []


@pytest.mark.cr("702.34a")
def test_702_34a_only_an_instant_or_sorcery_spell_is_cast_with_flashback():
    """"…if the resulting spell is an instant or sorcery spell." A permanent
    card printing the line is not read as castable from a graveyard."""
    card = _mk("Test Revenant", "{R}", "Creature — Spirit", "Flashback {1}{R}")
    game = _board(card, zone="graveyard")
    assert permission_for(game, 0, card, "graveyard") is None
    result = game.cast_from_hand(0, "Test Revenant", from_zone="graveyard")
    assert not result.supported and "601.3" in result.details


@pytest.mark.cr("702.34a", "608.2n")
def test_702_34a_cast_from_hand_a_flashback_card_goes_to_the_graveyard_and_waits():
    firebolt = _pool()["Firebolt"]
    game = _board(firebolt, zone="hand")
    _pay(game.players[0], "{R}")
    assert game.cast_from_hand(0, "Firebolt", target_player_index=1).supported
    assert _where(game, firebolt) == ["P1.graveyard"]
    entry, = playable_from_zones(game, 0)
    assert (entry["zone"], entry["name"], entry["cost_mana"], entry["cost_keyword"]) == (
        "graveyard", "Firebolt", "{4}{R}", "flashback",
    )
    # …and the card it becomes there can be flashed back (CR 400.7: a new
    # object, with the keyword it prints).
    _pay(game.players[0], "{4}{R}")
    assert game.cast_from_hand(0, "Firebolt", target_player_index=1, from_zone="graveyard").supported
    assert _where(game, firebolt) == ["P1.exile"]
    assert game.players[1].life == 16


@pytest.mark.cr("702.34a", "118.9a")
def test_702_34a_cast_through_another_permission_it_is_not_a_flashback_cast():
    """A graveyard another effect has opened is a different way to cast the
    card: it costs its mana cost, the flashback cost was not paid, and nothing
    of the keyword's exiles it. The caster who wants the flashback instead
    announces the alternative cost (CR 601.2b)."""
    firebolt = _pool()["Firebolt"]
    game = _board(firebolt, zone="graveyard")
    grant_permission(
        game, player_index=0, zone="graveyard", mode="cast", cards=None,
        duration="end_of_turn", source_name="Test Opened Graveyard",
    )
    # The entry the client is shown is the other permission's: no price on it.
    entry, = [e for e in playable_from_zones(game, 0) if e["name"] == "Firebolt"]
    assert entry["source"] == "Test Opened Graveyard" and "cost" not in entry
    _pay(game.players[0], "{R}")
    cast = game.queue_from_hand(0, "Firebolt", target_player_index=1, from_zone="graveyard")
    assert cast.supported, cast.details
    assert not game.stack[-1].flashback
    _settle(game)
    assert _where(game, firebolt) == ["P1.graveyard"]

    _pay(game.players[0], "{4}{R}")
    cast = game.queue_from_hand(
        0, "Firebolt", target_player_index=1, from_zone="graveyard",
        alternative_cost=True,
    )
    assert cast.supported, cast.details
    assert game.stack[-1].flashback
    _settle(game)
    assert _where(game, firebolt) == ["P1.exile"]
    assert not any(game.players[0].mana_pool.values())


@pytest.mark.cr("118.9d", "601.2f")
def test_118_9d_cost_increases_and_reductions_apply_to_the_flashback_cost():
    """"Start with the mana cost or alternative cost you're paying, add any
    cost increases, then apply any cost reductions." Sphere of Resistance
    makes Firebolt's flashback {5}{R}; the printed mana cost is not what is
    taxed and not what is paid."""
    firebolt = _pool()["Firebolt"]
    game = _board(firebolt, zone="graveyard")
    game._put_permanent_onto_battlefield(
        1, Permanent(card=_pool()["Sphere of Resistance"]), None
    )
    _pay(game.players[0], "{4}{R}")
    refused = game.cast_from_hand(0, "Firebolt", target_player_index=1, from_zone="graveyard")
    assert not refused.supported and _where(game, firebolt) == ["P1.graveyard"]
    _pay(game.players[0], "{5}{R}")
    assert game.cast_from_hand(0, "Firebolt", target_player_index=1, from_zone="graveyard").supported
    assert not any(game.players[0].mana_pool.values())
    assert _where(game, firebolt) == ["P1.exile"]


@pytest.mark.cr("118.9c")
def test_118_9c_a_flashed_back_spell_keeps_its_printed_mana_cost_on_the_stack():
    """An alternative cost changes what is paid, not the spell's mana cost:
    Roar of the Wurm is a seven-mana spell on the stack however it was cast."""
    from engine.targeting import stack_object_mana_value

    roar = _pool()["Roar of the Wurm"]
    game = _board(roar, zone="graveyard")
    _pay(game.players[0], "{3}{G}")
    assert game.queue_from_hand(0, "Roar of the Wurm", from_zone="graveyard").supported
    item = game.stack[-1]
    assert item.card.mana_cost == "{6}{G}"
    assert stack_object_mana_value(item) == 7


@pytest.mark.cr("702.34a", "118.9")
def test_702_34a_a_flashback_cost_may_be_more_than_mana():
    """Torment prints "Flashback—{1}{G}, Pay 3 life." This test was written
    before Torment was measured, so an invented card holds the shape (the
    census above now casts the printed ones): the mana is charged as mana and
    the rest through the alternative-cost reader every other printed
    alternative cost goes through, gate and payment included."""
    card = _mk(
        "Test Lifeback", "{R}", "Instant",
        "Test Lifeback deals 1 damage to any target.\nFlashback—{1}{R}, Pay 3 life.",
    )
    assert compile_card_oracle(card).supported
    cost = printed_flashback_cost(card)
    assert (cost.mana, cost.pay_life, cost.keyword) == ("{1}{R}", 3, "flashback")

    game = _board(card, zone="graveyard")
    _pay(game.players[0], "{1}{R}")
    assert game.cast_from_hand(0, "Test Lifeback", target_player_index=1, from_zone="graveyard").supported
    assert (game.players[0].life, game.players[1].life) == (17, 19)
    assert _where(game, card) == ["P1.exile"]

    game = _board(card, zone="graveyard")
    game.players[0].life = 2
    _pay(game.players[0], "{1}{R}")
    refused = game.cast_from_hand(0, "Test Lifeback", target_player_index=1, from_zone="graveyard")
    assert not refused.supported and "601.2h" in refused.details
    assert game.players[0].life == 2 and game.players[0].mana_pool["R"] == 1
    assert _where(game, card) == ["P1.graveyard"]


# ---------------------------------------------------------------------------
# "Any time it would leave the stack"
# ---------------------------------------------------------------------------

#: Cards known to take a spell off the stack to somewhere that is **not** a
#: graveyard, by where they send it. The census below finds its own
#: population; these are what it must have found among them.
_REDIRECTS = {"Memory Lapse": "library", "Unsubstantiate": "hand"}


def _stack_removers() -> list:
    """Every supported instant in the pool whose announcement may name a spell
    on the stack: the population that could take a flashed-back spell off it.
    Compilation units, so the half of a split card that counters is one.

    By the picker's own word (``stack`` / ``also_stack`` /
    ``spell_or_permanent``), so a card printing a new way to remove a spell is
    in this list the day it compiles. Modal spells are left to their own
    tests; a card that then turns out not to remove anything (a Fork, a
    Deflection) is still held to the invariant, which is about where the
    flashed-back card ends up whatever happened to it.
    """
    found = []
    for unit in compilation_units(_pool().values()):
        if unit.primary_type != "instant":
            continue
        program = compile_card_oracle(unit)
        if not program.supported or program.modes:
            continue
        spec = derive_cast_spec(unit, program) or {}
        if spec.get("kind") in ("stack", "spell_or_permanent") or spec.get("also_stack"):
            found.append(unit)
    return sorted(found, key=lambda unit: unit.name)


def _flash_back_and_respond(responder):
    """Seat 0 flashes Firebolt back at seat 1; seat 1 answers with *responder*
    (a card, or the half of one it is cast as) aimed at it. Returns
    ``(game, firebolt, was it cast)``."""
    firebolt = _pool()["Firebolt"]
    game = _board(firebolt, zone="graveyard")
    game.enforce_mana_costs = False
    assert game.queue_from_hand(0, "Firebolt", target_player_index=1, from_zone="graveyard").supported
    game.players[1].hand.append(whole_card(responder))
    answered = game.queue_from_hand(1, responder.name, target_stack_index=0, x_value=1)
    _settle(game)
    return game, firebolt, answered.supported


@pytest.mark.cr("702.34a", "608.2n", "701.6a")
def test_702_34a_nothing_in_the_pool_sends_a_flashed_back_spell_anywhere_but_exile():
    """"If the flashback cost was paid, exile this card instead of putting it
    anywhere else any time it would leave the stack." Every instant in the
    pool that can name a spell is cast at a flashed-back Firebolt, and whatever
    it did — countered it, bounced it, tucked it, copied it, or nothing —
    the card is in exactly one place afterwards and that place is exile.
    """
    removers = _stack_removers()
    assert len(removers) >= 60, f"only {len(removers)} cards examined"
    cast = stopped = 0
    wrong = []
    for responder in removers:
        game, firebolt, answered = _flash_back_and_respond(responder)
        cast += answered
        stopped += answered and not any(
            line.startswith("Firebolt resolved") for line in game.log
        )
        if _where(game, firebolt) != ["P1.exile"]:
            wrong.append(f"{responder.name}: Firebolt is in {_where(game, firebolt)}")
    assert not wrong, wrong
    # The sweep was not vacuous: most of these were really cast (54 of 72 on
    # the day it was written), and a good number of them really took the spell
    # off the stack before it resolved (28).
    assert cast >= 50, cast
    assert stopped >= 25, stopped
    examined = {responder.name for responder in removers}
    for name in _REDIRECTS:
        assert name in examined, f"{name} is no longer in the census"


@pytest.mark.cr("702.34a", "614.1a")
def test_702_34a_the_census_sees_the_sites_that_send_a_spell_somewhere_else(monkeypatch):
    """The census validated backwards: with the two redirect sites' question
    answered "no", it names the cards this keyword is wrong about — a spell
    put on top of its owner's library, and one returned to its owner's hand."""
    import engine.flashback as flashback

    monkeypatch.setattr(stack_handlers, "leaves_stack_to_exile", lambda item: False)
    monkeypatch.setattr(flashback, "leaves_stack_to_exile", lambda item: False)
    for name, zone in _REDIRECTS.items():
        game, firebolt, answered = _flash_back_and_respond(_pool()[name])
        assert answered
        assert _where(game, firebolt) == [f"P1.{zone}"], name


@pytest.mark.cr("702.34a", "608.2b")
def test_702_34a_a_flashed_back_spell_removed_for_an_illegal_target_is_exiled():
    """CR 608.2b's spell that "doesn't resolve" is "put into its owner's
    graveyard" — and so, cast with flashback, exiled. Seize the Day's ruling
    in the same breath: no target, no extra phases."""
    seize = _pool()["Seize the Day"]
    game = _board(seize, zone="graveyard")
    game.enforce_mana_costs = False
    bears = next(p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears")
    assert game.queue_from_hand(
        0, "Seize the Day", from_zone="graveyard",
        target_permanent_ids=[bears.permanent_id], target_player_index=0,
    ).supported
    game.players[1].hand.append(_pool()["Terror"])
    assert game.cast_from_hand(
        1, "Terror", target_permanent_ids=[bears.permanent_id], target_player_index=0,
    ).supported
    _settle(game)
    assert any("608.2b" in line for line in game.log)
    assert _where(game, seize) == ["P1.exile"]
    assert game.extra_phases_remaining() == []


@pytest.mark.cr("702.34a", "702.27a")
def test_702_34a_exile_wins_over_a_buyback_that_was_also_paid():
    """Buyback returns the spell to its owner's hand "as it resolves"; flashback
    exiles it "instead of putting it anywhere else". Both paid, the hand is
    somewhere else."""
    card = _mk(
        "Test Buyflash", "{R}", "Instant",
        "Test Buyflash deals 1 damage to any target.\nBuyback {2}\nFlashback {1}{R}",
    )
    game = _board(card, zone="graveyard")
    _pay(game.players[0], "{3}{R}")
    cast = game.cast_from_hand(
        0, "Test Buyflash", target_player_index=1, from_zone="graveyard",
        optional_cost_payments={"{2}": 1},
    )
    assert cast.supported, cast.details
    assert not any(game.players[0].mana_pool.values()), "the buyback was charged on top"
    assert game.players[1].life == 19
    assert _where(game, card) == ["P1.exile"]


@pytest.mark.cr("702.34a", "707.10")
def test_707_10_a_copy_of_a_flashed_back_spell_is_just_a_copy():
    """A copy is not cast, so no flashback cost was paid for it — and it has
    no card to exile in any case. The original is exiled once, by its own
    resolution; the copy resolves and ceases to exist."""
    firebolt = _pool()["Firebolt"]
    game = _board(firebolt, zone="graveyard")
    game.enforce_mana_costs = False
    assert game.queue_from_hand(0, "Firebolt", target_player_index=1, from_zone="graveyard").supported
    game.players[0].hand.append(_pool()["Fork"])
    assert game.cast_from_hand(0, "Fork", target_stack_index=0).supported
    _settle(game)
    assert game.players[1].life == 16          # the spell and its copy
    assert _where(game, firebolt) == ["P1.exile"]


# ---------------------------------------------------------------------------
# Flashback granted, named and re-priced (Recoup, Tombfire, Catalyst Stone)
# ---------------------------------------------------------------------------

@pytest.mark.cr("702.34a", "611.2a")
def test_702_34a_a_granted_flashback_costs_the_card_s_mana_cost_and_ends_at_cleanup():
    """"Target sorcery card in your graveyard gains flashback until end of
    turn. The flashback cost is equal to its mana cost." (Recoup.)"""
    recoup, mind_rot = _pool()["Recoup"], _pool()["Mind Rot"]
    game = _board(recoup, zone="hand")
    slot = next(i for i, c in enumerate(game.players[0].graveyard) if c is mind_rot)
    _pay(game.players[0], "{1}{R}")
    assert game.cast_from_hand(
        0, "Recoup", target_player_index=0, target_permanent_index=slot,
    ).supported
    assert has_flashback(mind_rot, game=game, owner_seat=0)
    assert not has_flashback(mind_rot, game=game, owner_seat=1), "seat 1's copy was granted nothing"
    assert not has_flashback(mind_rot)
    granted = permission_for(game, 0, mind_rot, "graveyard")
    assert (granted.cost.mana, granted.cost.keyword, granted.duration) == (
        "{2}{B}", "flashback", "end_of_turn",
    )
    # Cast for that cost, it is a flashback cast like any other.
    _pay(game.players[0], "{2}{B}")
    assert game.cast_from_hand(0, "Mind Rot", target_player_index=1, from_zone="graveyard").supported
    _settle(game)
    assert _where(game, mind_rot).count("P1.exile") == 1
    assert "P1.graveyard" not in _where(game, mind_rot)

    # Unused, the grant ends with the turn (CR 514.2).
    game = _board(recoup, zone="hand")
    game.enforce_mana_costs = False
    assert game.cast_from_hand(0, "Recoup", target_player_index=0, target_permanent_index=slot).supported
    expire_end_of_turn(game)
    assert permission_for(game, 0, mind_rot, "graveyard") is None
    assert not has_flashback(mind_rot, game=game, owner_seat=0)


@pytest.mark.cr("702.34a")
def test_702_34a_cards_with_flashback_are_the_ones_that_print_it_or_were_granted_it():
    """"Target player exiles all cards with flashback from their graveyard."
    (Tombfire.) A card has flashback if it prints the keyword or an effect
    gave it one this turn — and the sweep takes both and nothing else."""
    by_name = _pool()
    game = _board(by_name["Tombfire"], zone="hand")
    game.enforce_mana_costs = False
    mine = game.players[0].graveyard
    mine.extend([by_name["Firebolt"], by_name["Recoup"]])
    grant_permission(
        game, player_index=0, zone="graveyard", mode="cast",
        cards=[by_name["Mind Rot"]], duration="end_of_turn", exile_instead=True,
        cost=printed_flashback_cost(by_name["Firebolt"]), source_name="Test Grant",
    )
    game.players[1].graveyard.append(by_name["Firebolt"])
    assert game.cast_from_hand(0, "Tombfire", target_player_index=0).supported
    assert sorted(c.name for c in game.players[0].exile) == ["Firebolt", "Mind Rot", "Recoup"]
    assert sorted(c.name for c in mine) == ["Forest", "Grizzly Bears", "Tombfire"]
    # The other player's graveyard was not the one chosen.
    assert [c.name for c in game.players[1].exile] == []
    assert "Firebolt" in [c.name for c in game.players[1].graveyard]


@pytest.mark.cr("601.2f", "118.9d", "118.7a")
def test_601_2f_a_modifier_scoped_to_flashback_costs_changes_nothing_else():
    """"Flashback costs you pay cost {2} less." / "Flashback costs your
    opponents pay cost {2} more." (Catalyst Stone.) The flashback cost and
    only that — the same card from a hand costs what it prints — for the
    Stone's controller and against everybody else."""
    by_name = _pool()
    firebolt = by_name["Firebolt"]

    def board(caster_zone: str) -> Game:
        game = _board(firebolt, zone=caster_zone)
        game._put_permanent_onto_battlefield(0, Permanent(card=by_name["Catalyst Stone"]), None)
        game.players[1].graveyard.insert(0, firebolt)
        return game

    game = board("graveyard")
    _pay(game.players[0], "{1}{R}")
    assert not game.cast_from_hand(0, "Firebolt", target_player_index=1, from_zone="graveyard").supported
    _pay(game.players[0], "{2}{R}")
    assert game.cast_from_hand(0, "Firebolt", target_player_index=1, from_zone="graveyard").supported
    assert not any(game.players[0].mana_pool.values())

    _pay(game.players[1], "{5}{R}")
    assert not game.cast_from_hand(1, "Firebolt", target_player_index=0, from_zone="graveyard").supported
    _pay(game.players[1], "{6}{R}")
    assert game.cast_from_hand(1, "Firebolt", target_player_index=0, from_zone="graveyard").supported
    assert not any(game.players[1].mana_pool.values())

    game = board("hand")
    _pay(game.players[0], "{R}")
    assert game.cast_from_hand(0, "Firebolt", target_player_index=1).supported
    assert not any(game.players[0].mana_pool.values())


# ---------------------------------------------------------------------------
# A spell cast out of the pile its own target is in (CR 601.2a before 601.2c)
# ---------------------------------------------------------------------------

@pytest.mark.cr("601.2a", "601.2c")
def test_601_2a_a_spell_cast_from_a_graveyard_is_not_a_card_in_it_to_be_targeted():
    """CR 601.2a moves the card to the stack first; CR 601.2c chooses targets
    two steps later. Coffin Purge flashed back out of a graveyard holding only
    itself has nothing to exile and cannot be cast — it was offered itself,
    announced at itself, paid for, and resolved having exiled nothing."""
    purge = _pool()["Coffin Purge"]
    game = Game(players=[PlayerState(name="P1", graveyard=[purge]), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    spec = game.cast_target_spec(0, purge, from_zone="graveyard")
    assert spec[CAST_FROM_GRAVEYARD] and spec["valid_targets"] == []
    for keywords in ({}, {"target_player_index": 0, "target_permanent_index": 0}):
        refused = game.cast_from_hand(0, "Coffin Purge", from_zone="graveyard", **keywords)
        assert not refused.supported, keywords
        assert _where(game, purge) == ["P1.graveyard"]
    # A second copy in the pile is a different card and a legal target, and so
    # is the same card in somebody else's graveyard.
    game.players[0].graveyard.append(purge)
    game.players[1].graveyard.append(purge)
    offered = game.cast_target_spec(0, purge, from_zone="graveyard")["valid_targets"]
    assert [(t["seat"], t["index"]) for t in offered] == [(0, 1), (1, 0)]


@pytest.mark.cr("601.2a", "601.2c")
@pytest.mark.parametrize("pile, named", [
    (["Morgue Theft", "Grizzly Bears", "Serra Angel"], "Grizzly Bears"),
    (["Morgue Theft", "Grizzly Bears", "Serra Angel"], "Serra Angel"),
    (["Grizzly Bears", "Morgue Theft", "Serra Angel"], "Serra Angel"),
    (["Grizzly Bears", "Morgue Theft", "Serra Angel"], "Grizzly Bears"),
    (["Grizzly Bears", "Serra Angel", "Morgue Theft"], "Serra Angel"),
])
def test_601_2c_a_graveyard_slot_is_the_one_the_caster_was_looking_at(pile, named):
    """The slot is announced against the pile with the spell still in it — the
    list the picker enumerated — and the card it names is the card that comes
    back, wherever in the pile the spell itself was."""
    by_name = _pool()
    game = Game(players=[
        PlayerState(name="P1", graveyard=[by_name[n] for n in pile]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    offered = game.cast_target_spec(0, by_name["Morgue Theft"], from_zone="graveyard")["valid_targets"]
    assert sorted(t["name"] for t in offered) == ["Grizzly Bears", "Serra Angel"]
    slot = next(t["index"] for t in offered if t["name"] == named)
    assert pile[slot] == named
    assert game.cast_from_hand(
        0, "Morgue Theft", from_zone="graveyard",
        target_player_index=0, target_permanent_index=slot,
    ).supported
    assert [c.name for c in game.players[0].hand] == [named]
