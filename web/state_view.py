"""The whole-state payload: the one JSON document a client polls.

:func:`_serialize_state` assembles it from every layer below — the serialization
leaves, the pregame / turn-step / combat prompts, the seat and outcome answers —
and does it *per viewer*, because a hand is hidden from everyone but its owner
and a prompt belongs to the seat that owes it. The playability computations live
here as well: nothing else asks them, and "what can I play right now" is a
question about the view, not about the turn.

There is **one** of those, asked of two zones. :func:`_card_castable_now` is the
whole question — timing, targets, mana — and the hand and the command zone
differ only in what their zone adds to the cost (nothing; CR 903.8's commander
tax). Answering the command zone separately would be a second opinion about
castability, and the two would drift the first time a timing gate moved.

**Two functions, and the difference is the point.** :func:`_serialize_state`
reads the game and returns JSON — it does not move a card, lock a division or
settle an ante. :func:`build_state` is what a route calls: it settles what the
game owes (``game_flow.settle_before_observation``) and *then* reads.

They used to be one function, and the one they were was the reading one. Ante
transfer and an AI's Raging River lock ran inside it, so ``GET /state`` moved
cards between players and nothing in the name said so. The settling still has to
happen before a client looks — see that function for why neither is deletable —
but it happens somewhere it can be seen, and the serializer is now a function
you can call to ask what the game looks like without changing the answer.

The session *view* fields (``cleanup_selected_indices``,
``untap_selected_indices``, ``untap_required_lands``) are still normalized in
the serializer, deliberately: they are the viewer's own pending selection, owned
by the ``Session`` rather than the ``Game``, and clamping them to what is
currently legal is part of rendering the prompt rather than a change to the
game. ``_serialize_state`` is a read *of the game*, which is the property that
was missing.
"""

from __future__ import annotations

import json
import re

from dataclasses import dataclass

from engine import Game
from engine.hand_locks import locked_hand_indices
from engine.cast_permissions import playable_from_zones
from engine.special_actions import (available_permanent_special_actions,
                                    available_special_actions)
from engine.cast_prohibitions import cast_prohibition
from engine.cast_timing import casts_at_instant_speed
from engine.classifier import classify_card
from engine.faces import face_cards
from engine.models import PlayerState
from engine.activation_zones import HAND
from engine.cycling import expand_cycling_line
from engine.mixins.stack.activation import hand_activation_cost
from engine.oracle import compile_card_oracle
from engine.cost_modifiers import (cost_reduction_for_cast, reduce_cost,
                                   spell_cost_tax, spell_symbol_tax)
from engine.cast_costs import additional_costs
from engine.targeting import (derive_cast_spec, spec_roles,
                              usable_activated_abilities)
from engine.untap_restrictions import permanent_in_limited_scope

from .prompts import PromptContext, render_prompts
from .session_store import Session

from .presence import seat_is_connected
from .runtime import store
from .seats import _build_rematch_info, _seat_type, _winner
from .serialization import (
    _serialize_card_summary,
    _serialize_modes,
    _serialize_player,
    _serialize_stack_item,
)
from .catalog import CATALOG_BY_NAME
from .pregame import _build_pregame_info
from .turn_steps import (
    _build_optional_trigger_info,
    _build_upkeep_mana_prevention_info,
    _build_upkeep_pay_info,
    _cleanup_discard_requirement,
    _clear_cleanup_selection,
    _optional_trigger_pending,
    _untap_land_selection_requirement,
    _upkeep_pay_pending,
)
from .combat_prompts import (
    _build_band_blocker_assignment_info,
    _build_banding_assignment_info,
    _build_camouflage_info,
    _build_multiblock_assignment_info,
    _build_raging_river_info,
)
from .game_flow import settle_before_observation


def _serialize_reveal_events(game: Game) -> list[dict]:
    """The reveal feed (CR 701.20, ``Game.record_reveal``), with each card name
    resolved to its catalog art so the client can show the revealed faces. A
    reveal is public by definition, so every viewer — spectators included —
    gets the same list. A name outside the catalog (a debug-injected card)
    keeps its entry with no art; the client falls back to a text placeholder."""
    events: list[dict] = []
    for event in game.reveal_events:
        cards = []
        for name in event["cards"]:
            entry = CATALOG_BY_NAME.get(name.casefold())
            cards.append({
                "name": name,
                "image_uri": entry.get("image_uri") if entry else None,
                "large_image_uri": entry.get("large_image_uri") if entry else None,
            })
        seat = event["seat"]
        events.append({
            "id": event["id"],
            "seat": seat,
            "player_name": (
                game.players[seat].name if 0 <= seat < len(game.players) else "Unknown"
            ),
            "cards": cards,
        })
    return events


def _seat_deck_colors(game: Game, seat: int) -> list[str]:
    """Color identity of a seat's deck, derived from its (pre-deal) library —
    works uniformly for random/saved/personal decks and for host/AI/joined-guest
    seats alike, since this is only ever read while the lobby is still open."""
    colors: set[str] = set()
    for card in game.players[seat].library:
        match = CATALOG_BY_NAME.get(card.name.casefold())
        if match:
            colors.update(match["color_identity"])
    return [c for c in ("W", "U", "B", "R", "G") if c in colors]


def _seat_deck_display_name(session: Session, seat: int) -> str:
    if session.mode == "free_for_all":
        name = session.seat_deck_names[seat] if seat < len(session.seat_deck_names) else None
    elif seat == 0:
        name = session.host_deck_name
    else:
        name = session.guest_deck_name
    return name or "Random Deck"


def _can_afford_with_pool(pool: dict, cost: dict, player: PlayerState) -> bool:
    """Check whether `pool` can pay `cost` without mutating either."""
    # "You may spend mana as though it were mana of any color." (Chromatic
    # Orrery.) Asked through the engine's own arithmetic rather than answered
    # again here: this function is already a second reading of
    # `_pay_mana_cost_directly`, and a second reading that knows about one of
    # the two spending permissions greys out a card the engine would happily
    # cast.
    if player.spends_mana_as_any_color:
        from engine.mana_payment import fungible_colors_headroom

        return fungible_colors_headroom(pool, cost) is not None

    temp = dict(pool)
    for sym in ("W", "U", "B", "G", "C"):
        if temp.get(sym, 0) < cost.get(sym, 0):
            return False

    available_red = temp.get("R", 0)
    if player.can_spend_white_as_red:
        available_red += temp.get("W", 0)
    if available_red < cost.get("R", 0):
        return False

    temp["W"] -= cost.get("W", 0)
    temp["U"] -= cost.get("U", 0)
    temp["B"] -= cost.get("B", 0)
    temp["G"] -= cost.get("G", 0)
    temp["C"] -= cost.get("C", 0)

    red_to_pay = cost.get("R", 0)
    from_red = min(temp.get("R", 0), red_to_pay)
    temp["R"] = temp.get("R", 0) - from_red
    red_to_pay -= from_red
    if red_to_pay > 0:
        if not player.can_spend_white_as_red or temp.get("W", 0) < red_to_pay:
            return False
        temp["W"] -= red_to_pay

    generic = cost.get("generic", 0)
    if generic > 0:
        available = sum(max(0, temp.get(s, 0)) for s in ("C", "W", "U", "B", "R", "G"))
        if available < generic:
            return False

    return True


@dataclass(frozen=True)
class _CastingWindow:
    """The seat-wide half of "what can I play right now": the mana this seat
    could produce and the turn-structure facts a timing gate reads.

    Built once per seat, because every card the seat might cast is tested
    against the same one — a card in hand and a commander in the command zone
    (CR 903.8) differ only in what their zone adds to the cost.
    """

    potential_pool: dict[str, int]
    may_play_land: bool
    current_turn: int
    is_main_phase: bool
    stack_empty: bool


def _casting_window(session: Session, player_index: int) -> _CastingWindow | None:
    """The window *player_index* is casting into, or None when they cannot
    begin a cast at all — a blocking prompt is open, or they do not have
    priority."""
    game = session.game
    player = game.players[player_index]

    # Bail under blocking UI states where casting is not possible
    if session.pregame_phase is not None:
        return None
    if _cleanup_discard_requirement(session) > 0:
        return None
    if _untap_land_selection_requirement(session) > 0:
        return None
    if _upkeep_pay_pending(session):
        return None
    if _optional_trigger_pending(session):
        return None
    if session.island_sanctuary_pending:
        return None
    if game.pending_search_library is not None:
        return None
    if game.pending_choice_of("search_destination") is not None:
        return None
    if game.pending_reorder_library is not None:
        return None

    if not game.has_priority(player_index):
        return None

    # Potential mana = current pool + what each untapped land could produce
    potential_pool: dict[str, int] = dict(player.mana_pool)
    for perm in game.controlled_by(player_index):
        # ``has_type`` (CR 613 layer 4), not the printed line: what makes mana
        # here is whatever is a land *now*.
        if not perm.tapped and perm.has_type("land"):
            for color in perm.effective_produced_mana:
                sym = color.upper()
                potential_pool[sym] = potential_pool.get(sym, 0) + 1

    return _CastingWindow(
        potential_pool=potential_pool,
        may_play_land=game._may_play_another_land(player_index),
        current_turn=session.current_turn,
        is_main_phase=game.current_phase == "main",
        stack_empty=not game.stack,
    )


#: CR 601.2b's answer for the highlight: every optional additional cost
#: declined. "Castable now" is the cheapest cast the card allows, so the gates
#: below are asked about that announcement — never mutated, so one mapping
#: serves every call.
_NO_OFFERS: dict = {}


def _card_castable_now(
    session: Session,
    player_index: int,
    card,
    window: _CastingWindow,
    *,
    extra_generic: int = 0,
    hand_index: int | None = None,
) -> bool:
    """Whether *card* could be cast or played right now — timing, targets and
    mana (the pool plus what untapped lands could add).

    ``extra_generic`` is what casting it from *this* zone adds to the cost:
    CR 903.8's commander tax for the command zone, nothing for the hand. Which
    zones the seat may cast from is the caller's question rather than this
    one's — the hand is CR 601.3 and the command zone is CR 903.8, two
    different rules whose cards then face the same gates.

    ``hand_index`` is which copy, and it matters to one gate: CR 118.9's
    alternative cost may be paid *rather than* the mana cost, and CR 601.2a
    withholds the spell itself from the hand that pays it.
    """
    game = session.game
    player = game.players[player_index]

    # CR 709.3a: "Only the chosen half is evaluated to see if it can be cast."
    # A split card is castable when either half is, and every gate below is
    # asked of the half — its type for timing, its targets, its cost.
    faces = face_cards(card)
    if faces:
        return any(
            _card_castable_now(
                session, player_index, face, window,
                extra_generic=extra_generic, hand_index=hand_index,
            )
            for face in faces
        )

    classification = classify_card(card)
    if not classification.supported:
        return False

    # CR 601.3: a prohibited spell cannot begin to be cast — and CR 305.1's
    # twin for a land that may not be played — so it is not castable *now*
    # however well the timing, the targets and the mana line up. The one
    # predicate the cast path refuses with (`engine/cast_prohibitions.py`), so
    # a card that glows is one the click will not be refused for. Asked of the
    # half for a split card (the recursion above), which is CR 709.3a.
    if cast_prohibition(game, player_index, card) is not None:
        return False

    # CR 702.8b: flash casts any time an instant could be cast, so both timing
    # gates ask instant-or-flash rather than the type line alone — through the
    # one derivation, so the picker and the action cannot disagree.
    instant_speed = casts_at_instant_speed(card, game, player_index)

    # Non-instant-speed spells require it to be your turn
    if player_index != window.current_turn and not instant_speed:
        return False

    # Sorcery-speed: must be main phase with empty stack on your turn
    # (planeswalkers per CR 306.1).
    if card.primary_type in {"land", "sorcery", "creature", "artifact", "enchantment", "planeswalker"} and not instant_speed:
        if player_index != window.current_turn or not window.is_main_phase or not window.stack_empty:
            return False

    # Card-specific timing restriction
    if "cast this spell only during your declare attackers step" in card.oracle_text.lower():
        if game.current_step != "declare_attackers" or game.active_player_index != player_index:
            return False

    # Blaze of Glory: only during combat before blockers are declared.
    if "cast this spell only during combat before blockers are declared" in card.oracle_text.lower():
        if game.current_phase != "combat" or game.current_step not in (
            "beginning_of_combat",
            "declare_attackers",
        ):
            return False

    # False Orders / similar: only during the declare blockers step.
    if "cast this spell only during the declare blockers step" in card.oracle_text.lower():
        if game.current_phase != "combat" or game.current_step != "declare_blockers":
            return False

    # Target validation (aura enchant targets, removal targets, counter targets, etc.)
    if "Aura" in card.type_line:
        # An Aura is *always* targeted (CR 115.1b), so its arm in
        # ``_validate_cast_targets`` demands a named permanent — and this call
        # names none, which made the answer "no" for every Aura in every hand
        # and took the castable glow away from all ten of M21's. The question
        # the highlight actually asks is "is there anything it could enchant?",
        # and that is the picker's own enumeration, run through the very arm
        # that would judge the cast.
        if not game.cast_target_spec(player_index, card).get("valid_targets"):
            return False
    elif card.primary_type in ("instant", "sorcery") and spec_roles(
        derive_cast_spec(
            card, compile_card_oracle(card), optional_cost_payments=_NO_OFFERS,
        )
    ):
        # A spell naming several **roles** ("Return target creature to its
        # owner's hand. Then return another target creature…", Withdraw) is in
        # the Aura's position exactly: ``_validate_cast_targets`` counts the
        # targets named against the roles, this call names none, and so the
        # answer was "requires 2 targets" for every roles spell in every hand
        # — ten shipped cards that never glowed on a board holding a full
        # chain of legal targets. The question is the Aura's too: is there a
        # chain the picker would offer?
        if not game.cast_target_spec(player_index, card).get("valid_targets"):
            return False
    else:
        # ``_NO_OFFERS``: castable *now* means castable at its cheapest, with
        # every optional cost declined (CR 601.2b) — and CR 702.33g makes that
        # a different announcement from the card's every arm. An unkicked
        # Falling Timber names one creature; read as the whole card it named
        # two, and never glowed.
        target_ok, _ = game._validate_cast_targets(
            card, player_index, None, optional_cost_payments=_NO_OFFERS,
        )
        if not target_ok:
            return False
        # …and CR 601.2c's "no legal target exists", through the predicate the
        # cast path itself refuses with. The arms above ask it of the kinds
        # they name; a spell whose first instruction is a wrapper ("Destroy
        # target artifact or enchantment. Draw two cards.") reached none of
        # them, so it glowed on an empty board and the click was then refused.
        if game.no_legal_cast_target_refusal(
            player_index, card, optional_cost_payments=_NO_OFFERS,
        ) is not None:
            return False

    # CR 601.2h: "As an additional cost to cast this spell, sacrifice a
    # creature." (Village Rites, Death Bomb.) A printed cost the board cannot
    # pay is a spell that cannot be cast, through the gate the cast path
    # refuses with — 27 shipped spells glowed with nothing to pay with and
    # every click was refused. Only the costs every zone charges (a cost
    # naming a zone belongs to a cast from that zone, which this function is
    # not told), and only the mandatory ones: an offer nobody takes is not a
    # price. An announced X reads as 0 here, as it does for the mana below.
    printed_costs = tuple(
        cost for cost in additional_costs(card) if cost.from_zone is None
    )
    if printed_costs and game._unpayable_additional_cost(
        player_index, card, printed_costs,
        spell_hand_index=hand_index, from_zone="hand", taken=_NO_OFFERS,
    ) is not None:
        return False

    # Land play restriction: CR 305.2's one per turn, plus whatever the
    # allowances on this seat's battlefield add (engine/land_play_allowance.py).
    if card.primary_type == "land" and not window.may_play_land:
        return False

    # Mana affordability for non-land cards
    if card.primary_type != "land" and game.enforce_mana_costs:
        # CR 601.2f, through the three functions the cast path and the AI's own
        # affordability read (``ai_policy._cost_for``) already call. What stood
        # here was ``3 if a permanent is named "Gloom" and the card is white``:
        # one card name, one hardcoded amount, one colour, and the printed
        # colours at that. The pool prints **28** cards this misses — twelve
        # more increases (Sphere of Resistance taxes every spell, so the whole
        # hand glowed and every click was refused), ten reductions and five
        # self-reductions (a Pearl Medallion out and the white spell that *is*
        # castable stays greyed), plus Derelor's coloured pip, which no amount
        # of generic arithmetic can see.
        tax, _taxing = spell_cost_tax(game, player_index, card)
        pips, _pip_taxing = spell_symbol_tax(game, player_index, card)
        reduction, _reducing = cost_reduction_for_cast(game, player_index, card)
        # Use x_value=0 so X spells are shown as playable (castable at X=0)
        cost = reduce_cost(
            game._parse_mana_cost(
                card.mana_cost,
                x_value=0,
                extra_generic=extra_generic + tax,
                extra_pips=pips,
            ),
            reduction,
        )
        if not _can_afford_with_pool(window.potential_pool, cost, player):
            # CR 118.9: an alternative cost is paid *rather than* the mana cost,
            # so a seat with no mana at all can still cast Force of Will off a
            # blue card and a life. Asked only once the mana answer is no, and
            # through the same enumeration the offer prompt reads — a highlight
            # that said "no" here would call five shipped cards uncastable on
            # exactly the boards they are famous for being cast from.
            return any(
                offer.get("kind") == "alternative" and offer.get("payable")
                for offer in game.cast_cost_offers(
                    player_index, card, spell_hand_index=hand_index,
                )
            )

    return True


def _compute_playable_hand_indices(session: Session, player_index: int) -> list[int]:
    """Return hand indices the player can legally cast right now (considering timing,
    mana already in pool plus potential mana from untapped lands, and restrictions)."""
    window = _casting_window(session, player_index)
    if window is None:
        return []
    # A card that is in hand and may not be played at all (Firestorm Phoenix's
    # rider) is not highlighted, for the same reason the engine refuses the
    # cast: the restriction is about *how many* copies may be played, so it is
    # read as a set of positions rather than as a fact about the card.
    locked = locked_hand_indices(session.game, player_index)
    return [
        i
        for i, card in enumerate(session.game.players[player_index].hand)
        if i not in locked
        and _card_castable_now(session, player_index, card, window, hand_index=i)
    ]


def _compute_castable_hand_faces(session: Session, player_index: int) -> dict[int, list[str]]:
    """For each split card in hand, the names of the halves castable right now
    (CR 709.3a) — by hand position, the same key the playable list uses.

    The playable list answers "may this card be cast"; a split card is two
    spells with two answers, and the prompt that offers its halves greys the
    one this board cannot cast. Empty for a hand with no multi-face card, which
    is every hand until the first one is dealt.
    """
    window = _casting_window(session, player_index)
    if window is None:
        return {}
    locked = locked_hand_indices(session.game, player_index)
    found: dict[int, list[str]] = {}
    for index, card in enumerate(session.game.players[player_index].hand):
        faces = face_cards(card)
        if not faces:
            continue
        found[index] = [
            face.name
            for face in faces
            if index not in locked
            and _card_castable_now(session, player_index, face, window, hand_index=index)
        ]
    return found


_ABILITY_REMINDER = re.compile(r"\([^)]*\)")


def _ability_cost_text(printed_line: str) -> str:
    """The cost clause of a printed ability line — what the button is named by.

    "Cycling {2} ({2}, Discard this card: Draw a card.)" is the whole of what a
    cycling card prints, and "{1}{U}, Discard this card: Look at the top two
    cards of your library. Put one of them into your hand and the other into
    your graveyard." is the whole of Waker of Waves' — neither fits on a button.
    The half a player is choosing by is the price, so the reminder text goes and
    what is left before the first colon is the label. A keyword line has no
    colon once its reminder is stripped and is already the price, so it survives
    whole ("Cycling {2}").
    """
    stripped = " ".join(_ABILITY_REMINDER.sub("", printed_line or "").split()).strip()
    head, sep, _tail = stripped.partition(": ")
    return (head if sep else stripped).rstrip(".")


def _printed_ability_line(card, ability) -> str:
    """The printed line *ability* was compiled from, or its compiled text.

    An ability's ``source_line`` is what the compiler read, which for a cycling
    keyword is the CR 702.29a expansion rather than "Cycling {2}". The button
    names the card as printed, so the printed line is walked through the same
    rewrite and compared — never matched against the expansion's English.
    """
    wanted = (ability.source_line or "").strip()
    for line in (card.oracle_text or "").split("\n"):
        if (expand_cycling_line(line) or line).strip() == wanted:
            return line.strip()
    return wanted


def _compute_hand_abilities(session: Session, player_index: int) -> list[dict]:
    """The activated abilities *player_index* may use from their **hand**.

    Cycling (CR 702.29a) and every other ability CR 113.6j puts in a hand,
    one entry per (hand card, ability). Read off
    ``usable_activated_abilities(program, zone=HAND)`` — the same list
    ``Game.activate_from_hand`` indexes with the ``ability_index`` these entries
    carry, so the button and the action name the same ability by construction.

    **This list is why the mechanic is reachable at all.** The engine has been
    able to activate an ability from a hand since Waker of Waves shipped, and
    the browser had no gesture for it: no hand card carries the affordance
    (clicking one is a cast) and no action kind existed. A supported card no
    player can use is the Roots class, and Urza's Saga lands 34 more of them on
    it.

    ``payable`` is the same question the castable-hand highlight asks — the
    pool plus what the untapped lands could add — because a button offered on a
    board that cannot pay for it is a button that does nothing. It is a flag
    rather than a filter so the affordance is *visible* while unaffordable,
    which is what a cycling card in an opening hand should look like.
    """
    game = session.game
    player = game.players[player_index]
    window = _casting_window(session, player_index)
    entries: list[dict] = []
    for hand_index, card in enumerate(player.hand):
        program = compile_card_oracle(card)
        for ability_index, ability in enumerate(
            usable_activated_abilities(program, zone=HAND)
        ):
            # The cost as CR 601.2f computes it, not as it is printed: a
            # Fluctuator on the board makes a Cycling {2} free, and a button
            # reporting it unaffordable while the engine would let it through
            # is the Roots class with the sign flipped. The same reader
            # ``Game.activate_from_hand`` charges, so the button and the
            # payment cannot disagree.
            required = hand_activation_cost(
                game, player_index, card, ability
            )[0]
            payable = True
            if game.enforce_mana_costs and any(required.values()):
                payable = window is not None and _can_afford_with_pool(
                    window.potential_pool, dict(required), player
                )
            entries.append({
                "hand_index": hand_index,
                "ability_index": ability_index,
                "name": card.name,
                # The line as **printed**, not as the compiler rewrote it: a
                # cycling card says "Cycling {2}" and the button should too.
                # Found by walking the printed lines through the same rewrite
                # rather than by pattern-matching the expansion's English —
                # the move ``oracle._printed_line_for`` makes for equip.
                "text": _printed_ability_line(card, ability),
                # What the button is named by: the price, not the whole
                # sentence. The full line stays in `text` for the tooltip.
                "cost_text": _ability_cost_text(_printed_ability_line(card, ability)),
                "payable": payable,
            })
    return entries


def _compute_playable_command_indices(session: Session, player_index: int) -> list[int]:
    """The same answer for the seat's own command zone: which commanders they
    could cast right now (CR 903.8), by the test a card in hand gets — so the
    board highlights a castable commander exactly as it highlights a castable
    card in hand.

    CR 903.8's tax is part of what that cast costs, so a commander recast twice
    stops being highlighted once the tax outruns the mana on the board. That is
    the whole reason this is not the constant the commander's *permission* is:
    ``castable_from_zones`` says the seat may cast it from there at all, which
    is true for as long as it sits in the zone.
    """
    game = session.game
    window = _casting_window(session, player_index)
    if window is None:
        return []
    return [
        i
        for i, card in enumerate(game.players[player_index].command_zone)
        if game.may_cast_from_command_zone(player_index, card)
        and _card_castable_now(
            session, player_index, card, window,
            extra_generic=game.commander_tax(player_index, card),
        )
    ]


def parse_optional_cost_payments(raw: str | None) -> dict[str, int] | None:
    """CR 601.2b's part-answered offer map, as it arrives on a query string.

    The picker re-asks for a spec after every click, because both numbers it
    needs move with the answer: how many times each *remaining* offer is still
    payable (raising one spends mana the others can no longer have), and how
    many targets the announcement now names (Primitive Justice destroys one
    artifact plus another per {1}{R} and per {1}{G} paid). Sending the answer so
    far is what makes those recomputable server-side rather than re-derived in
    the browser — which for the target count would be a fourth reader of
    ``oracle_types.cost_target_count``'s two dict keys.

    Junk is dropped rather than refused. This map is a **picker hint**: it sizes
    what the browser offers, and the cast itself is gated by the engine against
    the map the *action* carries, so the worst a malformed hint can do is offer
    the wrong range and have the cast refused with nothing spent.
    """
    if not raw:
        return None
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(decoded, dict):
        return None
    payments = {
        str(key): int(value)
        for key, value in decoded.items()
        if isinstance(value, (int, float)) and int(value) > 0
    }
    return payments or None


def build_card_target_spec(
    session: Session,
    card,
    seat: int,
    *,
    from_zone: str = "hand",
    hand_index: int | None = None,
    optional_cost_payments: str | None = None,
) -> dict:
    """One card's cast-time announcement, for a client that is about to make it.

    The same spec a hand card carries in the polled state, asked for a card the
    state does not carry one for — the Debug Menu's free cast, whose card comes
    from a session-less catalog search — and asked *again* mid-announcement,
    once CR 601.2b's optional prices have been part-answered.
    """
    return {
        "name": card.name,
        "target_spec": session.game.cast_target_spec(
            seat, card, from_zone=from_zone, spell_hand_index=hand_index,
            optional_cost_payments=parse_optional_cost_payments(
                optional_cost_payments
            ),
        ),
        "modes": _serialize_modes(card, session.game, seat),
        # Whether more than one of those modes may be chosen (CR 700.2d). The
        # client fetches the spec before it opens the mode prompt, so this is
        # where the prompt learns to be a multi-select.
        "modes_at_least": compile_card_oracle(card).modes_at_least,
    }


def build_state(session: Session, viewer_seat: int | None) -> dict:
    """Settle what the game owes, then read it. What a route calls.

    The order is the contract: an AI's Raging River division and a decided
    game's ante have to be settled *before* the payload is built, or the client
    renders a prompt that is waiting on itself. See
    ``game_flow.settle_before_observation``.
    """
    settle_before_observation(session)
    return _serialize_state(session, viewer_seat)


def _serialize_state(session: Session, viewer_seat: int | None) -> dict:
    """The payload for one viewer. Reads the game; never changes it.

    Callers that are serving a client want :func:`build_state` instead — this
    one deliberately does not settle, so that "what does the game look like"
    can be asked without altering the answer.
    """
    win = _winner(session)

    cleanup_info = None
    cleanup_required = _cleanup_discard_requirement(session)
    untap_required = _untap_land_selection_requirement(session)
    if viewer_seat == session.current_turn and cleanup_required > 0:
        valid_indices = [
            idx
            for idx in sorted(set(session.cleanup_selected_indices))
            if 0 <= idx < len(session.game.players[viewer_seat].hand)
        ]
        session.cleanup_selected_indices = valid_indices
        session.cleanup_required_discards = cleanup_required
        cleanup_info = {
            "required_count": cleanup_required,
            "selected_indices": valid_indices,
            "selected_count": len(valid_indices),
        }
    else:
        _clear_cleanup_selection(session)

    untap_info = None
    untap_required = _untap_land_selection_requirement(session)
    if viewer_seat == session.current_turn and untap_required > 0:
        # Which permanent types are constrained (Winter Orb → lands, Smoke →
        # creatures, Damping Field → artifacts, Static Orb → every permanent).
        # Read before the candidate list rather than after it, because it is
        # what says whether a candidate belongs on that list at all.
        untap_options = session.game.get_untap_land_selection_options(session.current_turn) or {}
        untap_limits = untap_options.get("limits") or {}
        battlefield = session.game.players[viewer_seat].battlefield
        # ``permanent_in_limited_scope`` — the same predicate the untap step
        # itself and ``web/action_turn.py`` ask, so the list the board offers
        # and the list the engine accepts are one answer. This re-validation
        # used to read ``card.primary_type in ("land", "creature")``, which is
        # the printed line *and* only two of the four scopes a limit may name:
        # under **Damping Field** the engine offered three tapped artifacts and
        # the wire carried an empty candidate list beside ``max_count: 1``, so
        # the player was told to untap one artifact and given nothing to click
        # — and the pruned list was written straight back onto the session, so
        # the action handler then refused the click too. **Static Orb**'s
        # "permanent" scope is not a card type at all.
        valid_candidates = [
            idx
            for idx in sorted(set(session.untap_candidate_indices))
            if 0 <= idx < len(battlefield)
            and battlefield[idx].tapped
            and any(
                permanent_in_limited_scope(battlefield[idx], scope)
                for scope in untap_limits
            )
        ]
        session.untap_candidate_indices = valid_candidates

        valid_selected = [idx for idx in sorted(set(session.untap_selected_indices)) if idx in set(valid_candidates)]
        if len(valid_selected) > untap_required:
            valid_selected = valid_selected[:untap_required]
        session.untap_selected_indices = valid_selected
        session.untap_required_lands = untap_required
        untap_info = {
            "max_count": untap_required,
            "candidate_indices": valid_candidates,
            "selected_indices": valid_selected,
            "selected_count": len(valid_selected),
            # One entry per constrained card type — Winter Orb's land, Smoke's
            # creature, Damping Field's artifact. It was two named fields, and
            # a third type meant a third field here, in the action handler and
            # in the browser.
            "limits": untap_options.get("limits") or {},
        }

    # Every prompt a seat owes, rendered by web/prompts.py from the one registry
    # in engine/pending_choices.py. This used to be a per-card cascade here: a
    # block of visibility rules and a payload builder for each of eighteen
    # prompts, with nothing checking that a newly armed prompt got one.
    prompt_payloads = render_prompts(
        PromptContext(
            game=session.game,
            viewer_seat=viewer_seat,
            serialize_card=_serialize_card_summary,
            seat_type=lambda seat: _seat_type(session, seat),
        )
    )

    # Time Vault: the begin-of-turn "skip your turn to untap" decision, shown only
    # to the active human player while they decide.
    time_vault_info = None
    if (
        session.time_vault_pending
        and viewer_seat == session.current_turn
        and _seat_type(session, session.current_turn) != "ai"
    ):
        time_vault_info = {"permanents": list(session.time_vault_pending)}

    # Combat legality: which creatures may legally attack (declare-attackers step)
    # and every legal blocker→attacker pairing (declare-blockers step), computed by
    # the engine so the UI offers exactly the assignments the engine would accept.
    combat_state = session.game.get_combat_state()
    game = session.game
    if game.current_turn_phase == "combat" and game.current_step == "declare_attackers":
        combat_state["legal_attacker_indices"] = game.legal_attacker_indices(game.active_player_index)
    else:
        combat_state["legal_attacker_indices"] = []
    # CR 802.4: aggregate legal blocker assignments across every defending
    # player this combat (2+ in FFA), not just a single pre-picked one. Blocker
    # indices are only unambiguous within one defender's battlefield, so tag
    # each pair with which defender it belongs to.
    combat_state["legal_blocker_assignments"] = [
        {**pair, "defending_player_index": defender_index}
        for defender_index in sorted(game.combat_defending_players())
        for pair in game.legal_blocker_assignments(defender_index)
    ]

    return {
        "session_id": session.id,
        "mode": session.mode,
        # CR 407.1: whether this game is played for ante. Drives the ante pile in
        # the board UI and tells a joining player which decks they may bring.
        "playing_for_ante": session.playing_for_ante,
        # The constructed format this game is played under (a key of
        # web/deck_legality.py's FORMATS). The session id names it too — that is
        # what a player reads *before* joining; this is the same answer from the
        # server, for a client that is already in the game.
        "format": session.game_format,
        # CR 903.1 / 903.12a: "commander", "brawl", or null for an ordinary
        # game. Drives the command zone in the board UI, the commander-damage
        # tracker, and whether the client offers a cast from the command zone.
        "commander_variant": session.game.commander_variant,
        "status": session.status,
        "current_phase": session.game.current_phase,
        "current_turn_phase": session.game.current_turn_phase,
        "current_step": session.game.current_step,
        "current_turn": session.current_turn,
        "current_turn_is_extra": session.game.current_turn_is_extra,
        "turn_number": session.game.turn,
        "priority_player": session.game.priority_player_index,
        "priority_pass_count": session.game.priority_pass_count,
        "joined_seats": sorted(session.joined_seats),
        # Joined human seats whose player has lost their connection (their
        # event stream has been gone past web/presence.py's grace period).
        # The remaining players' clients show the "waiting for them to
        # rejoin" dialog off this; the Join page's rejoin picker reads the
        # per-seat ``connected`` flags below.
        "disconnected_seats": sorted(session.disconnected_seats),
        "seat_types": session.seat_types,
        "lobby": {
            "game_started": session.game_started,
            "open_seats": store.open_human_seats(session),
            "total_seats": len(session.game.players),
            "joined_count": len(session.joined_seats),
            "seats": [
                {
                    "seat": i,
                    "joined": i in session.joined_seats,
                    # Live presence, not the grace-delayed disconnect flag: the
                    # Join page's rejoin picker disables "connected" seats, and
                    # it must disable exactly the seats /rejoin would refuse —
                    # both ask whether a stream is open right now. (An AI seat
                    # has no stream; being at the table is its presence.)
                    "connected": (
                        i in session.joined_seats
                        and (
                            session.seat_types.get(i) == "ai"
                            or seat_is_connected(session.id, i)
                        )
                    ),
                    "is_ai": session.seat_types.get(i) == "ai",
                    "name": session.game.players[i].name if i in session.joined_seats else None,
                    "deck_name": (
                        _seat_deck_display_name(session, i) if i in session.joined_seats else None
                    ),
                    "colors": (
                        _seat_deck_colors(session.game, i) if i in session.joined_seats else []
                    ),
                }
                for i in range(len(session.game.players))
            ],
        },
        # NOTE (frontend FFA pass): this used to be a hardcoded 2-entry list
        # (session.game.players[0]/[1]), which silently truncated Free-For-All
        # sessions (3-4 players) to 2 players in the serialized state. Generalized
        # to loop over every seat; identical output for the existing 2-player modes.
        "players": [
            _serialize_player(
                session.game.players[i], viewer_seat, i, session.game,
                _compute_playable_hand_indices(session, i) if viewer_seat == i else [],
                _compute_playable_command_indices(session, i) if viewer_seat == i else [],
                _compute_castable_hand_faces(session, i) if viewer_seat == i else {},
            )
            for i in range(len(session.game.players))
        ],
        "stack": [_serialize_stack_item(item, session.game) for item in reversed(session.game.stack)],
        "combat": combat_state,
        "log": session.game.log,
        # Cards revealed to all players (CR 701.20) — an event feed the client
        # diffs by id to float the revealed faces over the board.
        "reveal_events": _serialize_reveal_events(session.game),
        "winner": win,
        "rematch": _build_rematch_info(session, viewer_seat),
        "cleanup_discard": cleanup_info,
        "untap_land_selection": untap_info,
        "optional_untap": (
            {"permanents": list(session.optional_untap_pending)}
            if session.optional_untap_pending and viewer_seat == session.current_turn
            else None
        ),
        "upkeep_pay": _build_upkeep_pay_info(session, viewer_seat),
        "upkeep_mana_prevention": _build_upkeep_mana_prevention_info(session, viewer_seat),
        "optional_trigger": _build_optional_trigger_info(session, viewer_seat),
        "banding_assignment": _build_banding_assignment_info(session, viewer_seat),
        "band_blocker_assignment": _build_band_blocker_assignment_info(session, viewer_seat),
        "multiblock_blocker_assignment": _build_multiblock_assignment_info(session, viewer_seat),
        "raging_river": _build_raging_river_info(session, viewer_seat),
        "camouflage": _build_camouflage_info(session, viewer_seat),
        "island_sanctuary_pending": session.island_sanctuary_pending and viewer_seat == session.current_turn,
        "time_vault": time_vault_info,
        "pregame": _build_pregame_info(session, viewer_seat),
        # CR 601.3 permissions: what the viewer may currently cast or play from
        # their graveyard or exile (engine/cast_permissions.py). Empty for a
        # spectator — a permission belongs to a seat.
        "castable_from_zones": (
            playable_from_zones(session.game, viewer_seat)
            if viewer_seat is not None
            else []
        ),
        # CR 116 special actions: what the viewer may do with a card in hand
        # right now without using the stack (engine/special_actions.py). One
        # entry per (hand card, kind), through the same refusal the action
        # asks — a card offered here and refused by the action would be a
        # button that does nothing. Empty for a spectator, for the reason the
        # permissions above are: an action belongs to a seat.
        # …and CR 116.2c/116.2d's half of the same rule, offered by a
        # *permanent* rather than by a card in hand ("You may pay {R} to end
        # this effect", Tempest's Licids). One list, because the client's
        # question is "what may I do without the stack?" and the answer does
        # not change shape with the zone — each entry names either a
        # `hand_index` or a `permanent_id`.
        # CR 113.6j: an activated ability whose cost can only be paid from a
        # hand — cycling (CR 702.29a), Waker of Waves. Beside the special
        # actions above and for the same reason they are there: a hand card
        # carries no affordance but "cast", so an ability activated from one
        # needs a control of its own. Unlike them it *does* use the stack; what
        # it shares is the zone. Empty for a spectator — an activation belongs
        # to a seat.
        "hand_abilities": (
            _compute_hand_abilities(session, viewer_seat)
            if viewer_seat is not None
            else []
        ),
        "special_actions": (
            available_special_actions(session.game, viewer_seat)
            + available_permanent_special_actions(session.game, viewer_seat)
            if viewer_seat is not None
            else []
        ),
        **prompt_payloads,
    }
