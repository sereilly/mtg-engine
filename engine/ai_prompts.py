"""The answers an AI seat gives part-way through a resolution, where the
prompt's default (``engine/pending_choices.py``) asks for a weighed one.

The registry's defaults (``mixins/stack/choices``) state the policy — take
gifts, pay tolls, make no trades — and ask these wherever an answer is worth
weighing rather than stating:

* **a library** — which card a search finds (:func:`choose_search_card`,
  :func:`choose_search_cards`), how a scry or a rearrangement leaves the top,
  which finds of a pile bought back a card at a time are kept
  (:func:`slow_pile_picks`) — each card weighed by what casting it would be
  worth (``ai_scoring._score_tutor_choice``);
* **a price** — whether a toll's penalty loses less than paying it
  (:func:`toll_decline_is_smaller_loss`), whether an offer's trade is worth
  taking (:func:`offer_trade_is_worth_taking`) or buys its own source's
  drawback, whether to decline one link of an "unless any player pays"
  chain, and whether a mana-priced "you may pay" may tap lands
  (:func:`optional_pay_may_tap_lands`);
* **a choice** — a modal trigger's mode (:func:`choose_trigger_mode`,
  CR 700.2b, rehearsed), a number named in secret (Goblin Game), whether to
  change a spell's targets (:func:`choose_target_change`), and the order a
  hand pick takes cards in (:func:`order_hand_pick`).

What each offer, toll and pile *does* is ``ai_prompt_readers``'. The
resolution paths import these from ``ai_policy``, which binds them for that
reason.
"""

from __future__ import annotations

from .ai_target_sides import ability_target_side, spell_target_side
from .ai_rehearsal import deliberating, rehearse, rehearsing
from .ai_prompt_readers import offer_trade, TollLoss, toll_branch_loss
from .ai_valuation import offer_buys_a_drawback_to_its_source
from .game import Game
from .models import CardDefinition
from .search_filters import search_matches, searched_seat
from .ai_payment import _cost_for, _plan_land_taps
from .ai_actions import hand_spells
from .ai_scoring import _score_tutor_choice, _permanent_value
from .ai_cast_gates import _can_cast_with_targets


def choose_trigger_mode(game: Game, choice, stated: int) -> int:
    """Which offered mode of a **modal triggered ability** a seat nobody asks
    takes (CR 700.2b): the one measured to do most, or *stated* — the
    registry's standing answer, the first mode that is not a price — when
    nothing measures more than it or no rehearsal can be run.

    The valuation the cast chooser weighs a spell's bullets with, asked of a
    trigger's: each offered mode is answered on a scratch copy of the game
    (``Game._resolve_mode_choice``, which records the mode and its default
    target on the ability), the ability resolves there, and the swings are
    compared (``ai_rehearsal.rehearse``). So Trufflesnout takes four life at
    three life and the counter at twenty, and Elder Gargaroth draws when a
    Beast is worth less to it than a card — where each took its first bullet
    whatever the board.

    The choice is made as the ability goes on the stack (CR 603.3c), which
    for an entry trigger is while the permanent's own spell is still
    resolving; the copy is cut loose from that (``detach``) and carries out
    the ability alone. "Nothing done" is the ability taken off the stack,
    which is what CR 700.2b does to one with no mode chosen.
    """
    item = choice.data.get("_trigger_item")
    options = tuple(choice.data.get("_options") or ())
    if item is None or len(options) < 2 or rehearsing():
        return stated

    def without(table, prompt) -> None:
        ability = prompt.data.get("_trigger_item")
        table.stack = [queued for queued in table.stack if queued is not ability]

    class _Answered:
        def __init__(self, supported: bool) -> None:
            self.supported = supported
            self.details = "" if supported else "the mode could not be chosen"

    best, best_swing = stated, None
    with deliberating():
        order = [stated, *(index for index in range(len(options)) if index != stated)]
        for index in order:
            rehearsal = rehearse(
                game, choice.player_index,
                lambda table, prompt, index=index: _Answered(
                    bool(table._resolve_mode_choice(prompt, index))
                ),
                leaves_hand=False, carried=choice, detach=True, without=without,
                label=(
                    f"{getattr(getattr(item, 'card', None), 'name', None) or 'a trigger'}"
                    f" (its triggered ability's mode {index})"
                ),
            )
            if rehearsal is None:
                return stated
            if not rehearsal.accepted:
                continue
            if best_swing is None or rehearsal.swing > best_swing + 1e-9:
                best, best_swing = index, rehearsal.swing
    return best


def choose_search_card(
    game: Game, player_index: int, data: dict
) -> tuple[str, int] | None:
    """Pick the ``(zone, index)`` of the best card a search may find, or None to
    fail to find (CR 701.23b).

    Both the zones and the restriction come from the armed choice rather than
    from a second reading of the card: the AI is then offered exactly the cards
    a human seat is offered, and ``search_matches`` is the only thing deciding
    what is findable. An AI that filtered differently would be a second opinion
    about what the effect finds — the same bug class as a second parse.
    """
    picks = choose_search_cards(game, player_index, data, 1)
    if not picks:
        return None
    return picks[0]["zone"], picks[0]["index"]


def choose_search_cards(
    game: Game, player_index: int, data: dict, count: int
) -> list[dict]:
    """The counted search's answer: up to *count* distinct picks, best first,
    each ``{"zone": ..., "index": ...}`` the way the resolver reads them.

    A printed name is consumed by the find that used it, exactly as the
    resolver will consume it — an AI that kept offering a used name would
    submit an answer the engine then refuses, which is the fail-to-find.
    """
    from .search_filters import (landing_seat, name_key, search_slots,
                                 slot_assignment)

    # The zone the search looks in, which is not always the chooser's own —
    # see `searched_seat`. An AI reading its own graveyard for a card the
    # effect takes from someone else's would answer with an index the resolver
    # then refuses, which is the fail-to-find.
    player = game.players[searched_seat(data, player_index)]
    working = dict(data)
    picks: list[dict] = []
    taken: set[tuple[str, int]] = set()
    # **Whose hand the finds are for.** A seat choosing cards that go to
    # somebody else's hand (Guided Passage: "an opponent chooses … you put the
    # chosen cards into your hand"; Jester's Mask's refilled hand) is choosing
    # what its opponent gets, and wants the *least* of what the phrase admits.
    # Read off the prompt's own seats rather than off a card: the finds land
    # where `landing_seat` says, and that is the whole of the question. A find
    # taken out of another seat's library for any other place — exile (Jester's
    # Cap), the chooser's own battlefield (Bribery) — is still the best card.
    destinations = list(working.get("destinations") or ()) or [
        working.get("destination", "hand")
    ]
    handing_over = (
        landing_seat(working, player_index) != player_index
        and all(place == "hand" for place in destinations)
    )
    sign = -1.0 if handing_over else 1.0
    if search_slots(working):
        # "a land card **of each basic land type**" (Gaea's Balance): one find
        # per printed description. Best card first, each kept only while the
        # cards kept so far can still all be given a description of their own
        # — `slot_assignment`, the resolver's own question, so this is an
        # answer it admits. Taking the best that still fits is exact here (the
        # sets that can be assigned are a matroid), so it is also as many
        # finds as the zones allow, which is what a floor asks for.
        entries = [
            (zone, index, card)
            for zone in tuple(working.get("zones", ("library",)))
            for index, card in enumerate(
                player.library if zone == "library" else player.graveyard
            )
            if search_matches(card, working)
        ]
        entries.sort(
            key=lambda entry: -sign * _score_tutor_choice(game, player_index, entry[2])
        )
        kept: list[tuple] = []
        for entry in entries:
            if len(kept) >= count:
                break
            trial = kept + [entry]
            if None not in slot_assignment(
                [card for _zone, _index, card in trial], working
            ):
                kept = trial
        return [{"zone": zone, "index": index} for zone, index, _card in kept]
    for _ in range(count):
        best: tuple[str, int] | None = None
        best_score = float("-inf")
        for zone in tuple(working.get("zones", ("library",))):
            cards = player.library if zone == "library" else player.graveyard
            for index, card in enumerate(cards):
                if (zone, index) in taken or not search_matches(card, working):
                    continue
                score = sign * _score_tutor_choice(game, player_index, card)
                if best is None or score > best_score:
                    best = (zone, index)
                    best_score = score
        if best is None:
            break
        zone, index = best
        card = (player.library if zone == "library" else player.graveyard)[index]
        taken.add(best)
        picks.append({"zone": zone, "index": index})
        among = list((working.get("restrictions") or {}).get("named_among") or ())
        if among:
            working["restrictions"] = {
                **(working.get("restrictions") or {}),
                "named_among": [n for n in among if name_key(n) != name_key(card.name)],
            }
    return picks


#: How many cards a seat nobody asks exiles into a pile that returns **one card
#: per activation** (`ai_prompt_readers.exiled_search_pile_comes_back_one_at_a_time`).
#: A weight: one activation a turn is the most such a pile gives back, and three
#: is about what the rest of a game has turns for.
SLOW_RETURN_PILE_SIZE = 3


def slow_pile_picks(game: Game, player_index: int, picks: list[dict]) -> list[dict]:
    """The picks a headless seat keeps of *picks* — every card an "any number"
    exile-search matched, as ``{"zone", "index"}`` — when the pile is bought
    back a card at a time: the `SLOW_RETURN_PILE_SIZE` it would most want to
    tutor for (`_score_tutor_choice`), in the order it was offered between
    equals.

    For ``_default_search_exile``. Skyship Weatherlight's default exiled every
    artifact and creature in the seat's library and then returned them at
    random for {4} each, which over a game is most of a deck's threats gone
    for good.
    """
    player = game.players[player_index]

    def card_at(pick: dict) -> CardDefinition:
        zone = player.library if pick.get("zone") == "library" else player.graveyard
        return zone[pick["index"]]

    ranked = sorted(
        enumerate(picks),
        key=lambda entry: (
            -_score_tutor_choice(game, player_index, card_at(entry[1])), entry[0],
        ),
    )
    kept = sorted(position for position, _pick in ranked[:SLOW_RETURN_PILE_SIZE])
    return [picks[position] for position in kept]


def choose_search_library_index(game: Game, player_index: int, card_type: str = "any") -> int | None:
    """Pick the library index of the best card to tutor for (e.g. Demonic Tutor).

    Returns None when no library card matches card_type (fail to find). The
    library-only view of ``choose_search_card``, kept because a caller that only
    ever searches a library should not have to spell out a zone list."""
    found = choose_search_card(game, player_index, {"card_type": card_type})
    return None if found is None else found[1]


def choose_reorder_library_order(
    game: Game, caster_index: int, target_index: int, top_count: int
) -> list[int]:
    """Decide how to rearrange the top cards of a library (e.g. Natural Selection).

    Returns a permutation of ``range(top_count)`` where element 0 is the original
    index of the card that should end up on top (the next card drawn).

    When reordering our own library we surface the most valuable card first so we
    draw it next; when reordering an opponent's library we bury their best cards by
    putting the least valuable one on top.
    """
    target = game.players[target_index]
    top = target.library[:top_count]

    # Score each card from the library owner's perspective — how good drawing it
    # would be for them.
    scored = [
        (index, _score_tutor_choice(game, target_index, card))
        for index, card in enumerate(top)
    ]
    surface_best_first = caster_index == target_index
    scored.sort(key=lambda item: item[1], reverse=surface_best_first)
    return [index for index, _ in scored]


def choose_secret_number(game: Game, player_index: int, minimum: int = 1) -> int:
    """The number a seat names in secret (Goblin Game): "Each player hides at
    least one item … Each player loses life equal to the number of items they
    revealed. The player who revealed the fewest items then loses half their
    life, rounded up."

    Every point named is a point of life, and the least pays half of what it
    has left. So there are two lines and the policy picks between them from
    the life totals, which are all a seat may know — **it never reads another
    seat's number**, and is asked before any exists:

    * **the quiet line** — name the floor. It costs the floor and, as the
      fewest or tied for it, half the rest: ``(life - floor) // 2`` is left.
    * **outbidding** — name the weakest rival's whole life total. That rival
      can only match it by naming all the life it has, so it is either the
      fewest or dead, and this seat keeps ``life - bid`` unhalved.

    Outbidding is taken only when it leaves strictly more than the quiet line
    does, which is the seat far enough ahead on life to afford it (roughly: the
    weakest rival is at half this seat's life or less). That inequality is also
    the ceiling: the answer is always below the seat's own life total wherever
    any such answer is legal, the rule ``default_sacrifice_pick`` states for
    every default here — one never picks the answer that loses the game.

    Deterministic, and a function of public state alone.
    """
    floor = max(0, int(minimum))
    life = int(game.players[player_index].life)
    rivals = [
        int(player.life)
        for seat, player in enumerate(game.players)
        if seat != player_index and not player.lost
    ]
    if not rivals:
        return floor
    bid = max(floor, min(rivals))
    quiet = max(0, life - floor) // 2
    if life - bid > quiet:
        return bid
    return floor


def choose_scry_arrangement(
    game: Game, caster_index: int, top_count: int,
    library_index: int | None = None,
) -> tuple[list[int], int]:
    """Decide a scry (CR 701.22a): the arrangement, and how many go to the bottom.

    Returns ``(card_order, bottom_count)`` in the shape ``_resolve_scry`` takes —
    a permutation of ``range(top_count)`` reading top-first, and how many of its
    trailing entries go to the bottom.

    Scored by ``_score_tutor_choice`` unchanged, because "how good would drawing
    this be for me" is exactly the scry question and a second scoring function
    would be a second opinion about the same thing. A card scoring below zero is
    worse than an unknown card, so those go to the bottom; the rest are ordered
    best-first so the best one is drawn next. Deterministic given the library,
    which the AI-behaviour regression tests require.
    """
    # Whose library is being looked through, which is not always the chooser's
    # (Coral Fighters looks at the defending player's). The score below asks
    # "how good would drawing this be **for its owner**", so over somebody
    # else's pile the answer is negated: a card that would help them is one to
    # bury, and keeping the scoring function and flipping its sign is what
    # stops this becoming a second opinion about the same question.
    owner_index = caster_index if library_index is None else int(library_index)
    sign = 1.0 if owner_index == caster_index else -1.0
    owner = game.players[owner_index]
    scored = [
        (index, sign * _score_tutor_choice(game, owner_index, card))
        for index, card in enumerate(owner.library[:top_count])
    ]
    kept = sorted((s for s in scored if s[1] >= 0.0), key=lambda item: item[1], reverse=True)
    bottomed = sorted((s for s in scored if s[1] < 0.0), key=lambda item: item[1], reverse=True)
    return [index for index, _ in kept] + [index for index, _ in bottomed], len(bottomed)


# --- What a toll's two losses are worth against each other -------------------
#
# The prices, in life-equivalents. Weights are tuning and belong here; *which
# resources a branch takes* is `ai_prompt_readers.toll_branch_loss`'s derivation
# from the compiled program, and the permanents it hands back are the engine's
# own default picks, so the comparison prices exactly what would be given up.

#: A branch whose life cost meets or beats the seat's total. Never the smaller
#: loss against anything survivable, whatever the other side gives up.
_TOLL_LETHAL_PRICE = 1000.0
#: A card out of hand (a discard) or out of the game (an ante): the classic
#: two-for-one accounting — a card is worth about two life.
_TOLL_CARD_PRICE = 2.0
#: A card milled off the seat's own library: barely a loss at all, but not
#: nothing (CR 704.5b is somewhere down there).
_TOLL_MILL_PRICE = 0.25
#: What any permanent is worth just by being one — a card that reached the
#: battlefield — before `_permanent_value` adds its stats and cost. Without a
#: floor a Mox prices at 0.0 (no P/T, no cmc) and the seat gives it up to dodge
#: any damage at all.
_TOLL_PERMANENT_FLOOR = 2.5
#: Tapping the source: a turn's use of it, not the card.
_TOLL_TAP_PRICE = 1.0


def _toll_loss_price(game: Game, player_index: int, loss) -> float:
    """One branch's `ai_prompt_readers.TollLoss`, priced in life-equivalents."""
    player = game.players[player_index]
    if loss.life and loss.life >= player.life:
        return _TOLL_LETHAL_PRICE
    price = float(loss.life)
    price += loss.cards * _TOLL_CARD_PRICE
    price += loss.milled * _TOLL_MILL_PRICE
    for permanent in loss.permanents:
        price += _TOLL_PERMANENT_FLOOR + _permanent_value(permanent)
    if loss.taps_source:
        price += _TOLL_TAP_PRICE
    return price


def toll_decline_is_smaller_loss(
    game: Game, player_index: int, entry: dict, self_recipients=()
) -> bool:
    """Whether taking this toll's printed penalty loses less than paying its
    price — the valuation behind **take gifts, pay tolls, make no trades**'
    middle word, for the seat nobody asked (`_default_optional_pay`).

    A *toll* is an offer with a printed decline consequence, so both answers
    are losses: "pay 2 life" against "sacrifice this enchantment" (Season of
    the Witch), "sacrifice that artifact" against "2 damage" (Curse Artifact).
    Both sides are derived from the compiled program by
    `ai_prompt_readers.toll_branch_loss` and priced by the weights above; a side the
    program cannot price answers False, which keeps the standing policy — pay
    tolls — rather than comparing a number to a guess.

    Deliberately silent on a mana-priced toll: the default pays those out of
    floating mana and, since ``optional_pay_may_tap_lands``, out of untapped
    lands too — always, because a toll's other answer is a loss as well and
    the standing policy is to pay. Pricing a tapped land against the penalty
    is a weight nobody has measured a need for yet.

    *entry* is the armed `optional_pay` data and *self_recipients* the printed
    player references that resolve to the offered seat, both supplied by the
    resolution because only it knows them.
    """
    penalty_steps = tuple(entry.get("_on_decline") or ())
    legacy_damage = int(entry.get("damage", 0) or 0)
    if not penalty_steps and not legacy_damage:
        return False  # not a toll; the unpriced-trade policy owns free offers
    if (
        entry.get("cost")
        or entry.get("cost_alternatives")
        or entry.get("graded_options")
    ):
        return False  # mana-priced: the floating-mana policy stands
    source = entry.get("_source_permanent")
    context = entry.get("_context")
    paying = toll_branch_loss(
        game, player_index, tuple(entry.get("_on_accept") or ()),
        self_recipients, source, context,
    )
    if paying is None:
        return False
    life_cost = int(entry.get("life_cost", 0) or 0)
    if life_cost:
        paying = paying.plus_life(life_cost)
    declining = toll_branch_loss(
        game, player_index, penalty_steps, self_recipients, source, context
    )
    if declining is None:
        # **A price that kills is never paid for a penalty nobody can price.**
        # "Counter target instant or sorcery spell unless its controller has
        # Molten Influence deal 4 damage to them": what a countered spell is
        # worth is not derivable here, so the standing policy — pay tolls —
        # applied, and a seat at 4 life paid with the game. Whatever the
        # penalty is, it is not larger than the game; every survivable price
        # still goes to the standing policy, exactly as before.
        return _toll_loss_price(game, player_index, paying) >= _TOLL_LETHAL_PRICE
    if legacy_damage:
        declining = declining.plus_life(legacy_damage)
    return _toll_loss_price(game, player_index, declining) < _toll_loss_price(
        game, player_index, paying
    )


def _target_change_side(game: Game, item) -> str | None:
    """Whose side the object's controller wanted its target on — "opponent"
    for an effect that hampers what it targets, "you" for one that helps —
    or None where the compiled program does not say.

    The same readers every other aiming decision here uses
    (``spell_target_side`` for a spell, ``ability_target_side`` /
    ``activation_target_side`` for an ability), so "which way does this effect
    cut" has one answer whether the seat is choosing the target or changing it.
    """
    from .ai_target_sides import activation_target_side

    instruction = getattr(item, "ability_instruction", None)
    if instruction is not None:
        return ability_target_side(instruction) or activation_target_side(instruction)
    if getattr(item, "is_ability", False):
        return None
    spell = item.card
    side = spell_target_side(spell)
    if side is not None:
        return side
    # A spell whose steps carry no ``targets`` description for that reader
    # ("any target", Lightning Bolt) is still read by its instruction's family,
    # exactly as an ability of the same effect is one branch up. An instant or
    # sorcery only: a permanent spell's instructions are a mirror of what the
    # permanent does, not a program the spell runs.
    printed_types = (spell.type_line or "").lower()
    if "instant" not in printed_types and "sorcery" not in printed_types:
        return None
    executed = game._select_executable_instruction(
        spell, getattr(item, "chosen_mode_index", None)
    )
    if executed is None:
        return None
    return ability_target_side(executed) or activation_target_side(executed)


def choose_target_change(game: Game, seat: int, item, slots) -> "list | None":
    """What a non-interactive *seat* does when it "may change the target or
    targets" of *item* (Psychic Battle): the picks, one per slot, or None to
    leave them as they are.

    The stated policy, and it is one sentence: **move harm off my side, move
    help onto it, and otherwise leave it.**

    * an effect its controller aimed to *hurt* (the program's side is
      "opponent") that points at this seat or something it controls is moved —
      to the controller's own side where a legal target is there, else to any
      target that is not this seat's;
    * an effect aimed to *help* (side "you") that somebody else controls and
      that is not already on this seat's side is moved onto it;
    * everything else — an effect with no derivable side, a harmful one
      already pointing elsewhere, this seat's own helpful one — is left alone.

    **One target only.** CR 115.7a makes a change all-or-nothing, so moving a
    several-target effect means accepting a new target for every slot, and
    whether that is a gain is a trade this policy does not price — "make no
    trades", the rule ``_default_optional_pay`` already keeps.

    Deterministic: candidates are taken in the order the enumeration lists
    them, which is board order.
    """
    if len(slots) != 1:
        return None
    slot = slots[0]
    if slot.current.kind not in ("player", "permanent"):
        return None
    side = _target_change_side(game, item)
    if side is None:
        return None

    def controller_of(target) -> int | None:
        if target.kind == "player":
            return target.seat
        if target.kind != "permanent":
            return None
        permanent = game.permanent_by_id(target.permanent_id)
        return None if permanent is None else game.controller_index_of(permanent)

    candidates = [
        candidate for candidate in slot.candidates
        if candidate.kind in ("player", "permanent")
    ]
    mine = controller_of(slot.current) == seat
    if side == "opponent":
        if not mine:
            return None
        elsewhere = [c for c in candidates if controller_of(c) != seat]
        back_at_them = [c for c in elsewhere if controller_of(c) == item.caster_index]
        pick = (back_at_them or elsewhere or [None])[0]
        return None if pick is None else [pick]
    if side == "you":
        if mine or item.caster_index == seat:
            return None
        onto_mine = [c for c in candidates if controller_of(c) == seat]
        return [onto_mine[0]] if onto_mine else None
    return None


#: Lands — on the battlefield and in hand — below which a seat gives up its
#: draw step for a land card (`offer_trade_is_worth_taking`). The number the
#: tutor score already uses for "mana-screwed" is three; one more, because the
#: card bought here costs a draw rather than a tutor.
LAND_FOR_DRAW_FLOOR = 4
def offer_trade_is_worth_taking(
    game: Game, player_index: int, entry: dict
) -> "bool | None":
    """Whether a seat nobody asks takes a "you may A. If you do, B." offer
    whose two halves are a price and a purchase (`ai_prompt_readers.offer_trade`) —
    True, False, or None when the offer is not one this can weigh and the
    standing policy answers.

    * **A draw step for a land card** (Elfhame Sanctuary): only while the seat
      is short of lands (`LAND_FOR_DRAW_FLOOR`). Taken every turn it is a seat
      that never draws a spell again.
    * **A card from hand for the source untapped** (Forsaken City): not taken.
      One mana is worth less than a card to a seat that can use its cards, and
      the case where it is not — a card the seat would discard at cleanup
      anyway — did not arise once in six simulated games. It is also not yet
      *payable* by a seat nobody asks: the pick behind the offer defaults to
      no card, and "If you do, untap this land" then untaps it regardless, so
      taking the offer here would be a free untap rather than a trade.
    """
    trade = offer_trade(entry.get("_on_accept") or ())
    if trade is None:
        return None
    player = game.players[player_index]
    if (trade.price, trade.purchase) == ("draw", "land_card"):
        lands = sum(
            1 for permanent in game.controlled_by(player_index)
            if permanent.has_type("land")
        ) + sum(1 for card in player.hand if card.primary_type == "land")
        return lands < LAND_FOR_DRAW_FLOOR
    if (trade.price, trade.purchase) == ("card", "untap_source"):
        return False
    return None


def offer_buys_own_drawback(game: Game, player_index: int, entry: dict) -> bool:
    """Whether a seat nobody asks would, by taking this offer, buy the
    drawback its **own** permanent prints.

    "Whenever this creature attacks or blocks, any player may exile a card
    from their graveyard. If a player does, this creature assigns no combat
    damage this turn." (Carrion Rats.) The offer goes to every seat in turn
    and what it buys is a loss for whoever controls the source — so that seat
    declines, whatever the price, and every other seat is left to the standing
    policy. Exiling a card from one's own graveyard reads as no payment
    (``ai_prompt_readers.offered_action_is_a_payment``), so before this the attacker took the
    offer and blanked its own Rats every combat. ``chained_toll_declined``
    makes the same call for a *chain* link's paid branch; this is the per-seat
    offer's twin, read off the compiled branch
    (``ai_valuation.offer_buys_a_drawback_to_its_source``).

    **Only an offer put to a set of seats.** "You may put the top creature
    card of defending player's graveyard onto the battlefield under your
    control. If you do, this creature assigns no combat damage this turn."
    (Bone Dancer.) Offered to its controller alone, the same drawback is the
    *price* of what the action takes, and that trade is the card — the
    reading only holds where the card lets anybody buy the drawback.
    """
    source = entry.get("_source_permanent")
    if (
        source is None
        or entry.get("_offered_actor") not in _SEAT_SET_OFFERS
        or not offer_buys_a_drawback_to_its_source(entry.get("_on_accept") or ())
    ):
        return False
    return game.controller_index_of(source) == player_index


#: The printed actors that put one offer to every seat of a set
#: (``handlers/control_flow._offered_seats``) — "any player may …" reaches the
#: AST as ``each_player``.
_SEAT_SET_OFFERS = frozenset({"each_player", "each_opponent"})


def chained_toll_declined(game: Game, player_index: int, entry: dict) -> bool:
    """Whether a seat nobody asked declines one link of an "unless **any
    player** pays" chain (`handlers/control_flow.unless_player_pays`).

    The chain asks every seat in turn, the effect's own controller included —
    and for that seat the standing policy, *pay tolls*, is backwards: Rhystic
    Tutor's caster paid {2} to stop its own search, and every rhystic spell
    the AI cast was countered by its own mana. Who a link's answer helps is
    whose effect it is, read off the compiled program:

    * the **unpaid** branch is what the controller cast the effect for, unless
      ``toll_branch_loss`` prices it as the controller's own loss (Icy
      Prison's "sacrifice this enchantment") — so the controller pays only to
      stop a loss, and every other seat pays only to stop a gain;
    * the **paid** branch (Rhystic Scrying's "if any player pays {2}, discard
      three cards") is the drawback the card prints, so its controller never
      buys it and every other seat does when it can afford to.

    False — the standing policy — for anything that is not a chain link.
    """
    links = tuple(entry.get("_on_decline") or ())
    if len(links) != 1 or getattr(links[0], "kind", None) != "unless_player_pays":
        return False
    caster = getattr(entry.get("_context"), "caster", None)
    if caster is None or caster not in game.players:
        return False
    controller = game.players.index(caster)
    unpaid = tuple(links[0].payload.get("unpaid") or ())
    if not unpaid:
        if chain_payment_counters_the_event_spell(entry):
            # What paying buys is the *payer's*: somebody else's spell
            # countered (Ice Cave), whoever's permanent makes the offer. Not a
            # drawback its controller avoids, so no seat declines it by rule —
            # whether the mana is worth spending is
            # ``optional_pay_may_tap_lands``' question.
            return False
        return player_index == controller
    loss = toll_branch_loss(
        game, controller, unpaid, {"caster"}, entry.get("_source_permanent")
    )
    unpaid_is_a_loss = loss is not None and loss != TollLoss()
    return (player_index == controller) != unpaid_is_a_loss


def chain_payment_counters_the_event_spell(entry: dict) -> bool:
    """Whether *entry* is a link of an offer chain whose payment buys exactly
    one thing: the spell the trigger fired on, countered.

    "Whenever a player casts a spell, any other player may pay that spell's
    mana cost. If a player does, counter the spell." (Ice Cave.) Read off the
    armed link's own compiled branches — a ``paid`` branch that is a counter
    bound to the trigger and no ``unpaid`` branch at all — so it is a fact
    about the program and never about a card.

    The chain is only ever offered to seats *other* than the spell's caster,
    and this engine has no teams, so for every seat that is asked the spell is
    an opponent's: paying is a gain for the payer, at a price.
    """
    links = tuple(entry.get("_on_decline") or ())
    if len(links) != 1 or getattr(links[0], "kind", None) != "unless_player_pays":
        return False
    payload = links[0].payload
    paid = tuple(payload.get("paid") or ())
    return bool(paid) and not payload.get("unpaid") and all(
        getattr(step, "kind", None) == "counter_top_stack_spell"
        and step.payload.get("bound_to_trigger")
        for step in paid
    )


#: The life total below which a seat nobody asked starts spending its lands on
#: a life-only toll during its own turn (:func:`optional_pay_may_tap_lands`).
#: A weight, like every number in this module: half the starting total, so a
#: healthy seat keeps developing and one that has been bled to it stops
#: bleeding. The toll is paid when declining would leave the seat *under* it.
LIFE_TOLL_FLOOR = 10


def _life_only_toll(entry: dict) -> int | None:
    """The life a seat loses by declining *entry*, when losing that life is
    **all** declining does; otherwise None.

    Read off the armed offer's own decline branch, so it is a fact about the
    compiled program and never about a card: exactly one ``target_loses_life``
    carrying a printed number. Anything else — a sacrifice, damage, a counter,
    two steps, an amount only the resolution knows — is a toll this cannot
    price, and None keeps the standing policy for it (pay).
    """
    decline = tuple(entry.get("_on_decline") or ())
    if len(decline) != 1:
        return None
    step = decline[0]
    if getattr(step, "kind", None) != "target_loses_life":
        return None
    amount = step.payload.get("amount")
    return amount if isinstance(amount, int) and amount > 0 else None


def optional_pay_may_tap_lands(game: Game, player_index: int, entry: dict) -> bool:
    """Whether a seat nobody asked may tap its untapped lands to pay a
    mana-priced "you may pay" / "unless you pay" (`_default_optional_pay`).

    The policy that default states — **take gifts, pay tolls, make no trades** —
    had a mana half that read "never tap a land", and the offers this answers
    arrive where the pool is empty: an upkeep, a combat damage step, an
    opponent's turn. So every mana-priced toll was declined (Vaporous Djinn
    sacrificed itself with its two Islands untapped) and every mana-priced gift
    was refused (Rootwater Thief's {2}, Liliana's Devotee's {1}{B}). The
    plumbing to pay from lands was already there — ``_optional_pay_plan`` is a
    ``plan_payment`` over the untapped lands — and this is the weight that
    decides when to use it:

    * **A toll is always paid from the board when it can be.** Both answers
      are losses and the standing policy is to pay; refusing an affordable toll
      because the mana was in a land rather than in the pool was never the
      policy, only a consequence of where the pool happened to be.
    * **A gift is paid from lands only with mana nothing else will spend.** On
      another seat's turn the lands sit until this seat's untap step anyway. On
      the seat's own turn they are what it casts with, so a gift is taken only
      when no spell in hand could be cast with them now — the same question
      ``ai_policy.choose_cast_action`` answers, asked of the same candidates.
    * **And only a gift the seat's own object offers.** An offer another
      seat's spell makes this one ("that player may pay {R}{R}. If the player
      does, they may copy this spell", Chain Lightning) is priced by a card
      somebody else chose to cast, and what accepting does is left to defaults
      this policy cannot value — the copy keeps its original target, which is
      the payer's own creature. Those keep the floating-mana rule.
    * **A toll whose whole penalty is a little life is the one toll priced
      against the lands** (:func:`_life_only_toll`). "Whenever a player draws a
      card, that player loses 2 life unless they pay {2}" (Phyrexian Tyranny)
      asks every turn, in the draw step, before the seat has cast anything —
      and "always pay" answered it by tapping two lands a turn for the rest of
      the game: forty tolls paid out of forty in a six-game run, the seat
      under it casting with whatever was left. So on the seat's **own** turn
      such a toll is paid like a gift — with mana nothing in hand could use —
      until its life is low enough (:data:`LIFE_TOLL_FLOOR`) that the life is
      the dearer of the two. On another seat's turn the lands are idle and the
      standing answer stands: pay.
    """
    if chain_payment_counters_the_event_spell(entry):
        # **A gift at a price, to whichever seat pays it** (Ice Cave): the
        # decline branch is only the chain moving on, so refusing costs
        # nothing and this is not a toll — and what accepting buys is fully
        # known, an opponent's spell countered, so it is not the unvalued offer
        # of another seat's object either. It takes the gift rule's mana half:
        # lands that are idle (another seat's turn) always, and on the seat's
        # own turn only lands nothing in its hand could use.
        if game.active_player_index != player_index:
            return True
        return not _hand_could_use_mana(game, player_index)
    if entry.get("_on_decline") or int(entry.get("damage", 0) or 0) > 0:
        loss = _life_only_toll(entry)
        if loss is None or game.active_player_index != player_index:
            return True
        payer = game.players[player_index]
        if payer.life - loss < LIFE_TOLL_FLOOR:
            return True
        return not _hand_could_use_mana(game, player_index)
    context = entry.get("_context")
    if getattr(context, "caster", None) is not game.players[player_index]:
        return False
    if game.active_player_index != player_index:
        return True
    return not _hand_could_use_mana(game, player_index)


def _hand_could_use_mana(game: Game, player_index: int) -> bool:
    """Whether a spell in *player_index*'s hand could be cast with the mana
    its board makes — the question a gift or a toll paid on the seat's **own**
    turn asks ("lands nothing in its hand could use").

    Not `ai_casts._cast_candidate`, which this asked until the policy began to
    rehearse a cast before proposing it: that answers "is this cast worth
    proposing *now*", and asked while this very prompt is owed, the rehearsal's
    copy refuses every cast — so the whole hand read as unusable and the seat
    paid with lands it had a use for (Ice Cave, a Lightning Bolt in hand). What
    is asked here is the older question: legal to aim, and affordable.
    """
    player = game.players[player_index]
    for _hand_index, card in hand_spells(player):
        if card.primary_type == "land":
            continue
        if not _can_cast_with_targets(game, player_index, card):
            continue
        x_value = 0 if "{X}" in (card.mana_cost or "").upper() else None
        if _plan_land_taps(game, player, _cost_for(game, player, card, x_value)) is not None:
            return True
    return False


def order_hand_pick(
    game: Game, player_index: int, candidates, payload: dict, source_card
) -> list[int]:
    """*candidates* (hand slots) in the order a seat nobody asked should pick
    them for a "choose a card in your hand" (`_default_choose_cards_in_hand`).

    Unchanged — hand order, the stated default — unless the program behind the
    pick puts the picked card onto the battlefield for its owner
    (``ai_valuation.hand_pick_entry_consumer``). Then the cards that sentence
    admits come first, and among them the one at its superlative's extreme:
    "with the **lowest** mana value" enters only the lowest, so the cheapest
    admitted card is the pick that can win the comparison. Everything else
    keeps its hand order behind them.
    """
    from .ai_valuation import hand_pick_entry_consumer
    from .handlers._common import _card_matches_filter

    order = list(candidates)
    key = str((payload or {}).get("result_key") or "chosen_hand_cards")
    consumer = hand_pick_entry_consumer(source_card, key) if source_card else None
    if consumer is None:
        return order
    player = game.players[player_index]
    admitted = [
        slot for slot in order
        if _card_matches_filter(
            player.hand[slot], consumer["card_filter"], game=game, owner=player
        )
    ]
    guard = consumer.get("guard")
    if guard:
        # "…then put that card onto the battlefield **if it has the same name
        # as a permanent**" (Retraced Image): a pick the guard refuses enters
        # nothing, so the ones it admits go first. Asked of the engine's own
        # evaluator with the pick as the record the guard reads — the policy
        # and the resolution cannot disagree about what the guard means.
        from .game_types import OracleExecutionContext
        from .handlers.control_flow import evaluate_condition

        def holds(slot: int) -> bool:
            context = OracleExecutionContext(
                caster=player, target=player, card=source_card,
                results={key: [player.hand[slot]]},
            )
            return bool(evaluate_condition(game, context, guard))

        admitted = [slot for slot in admitted if holds(slot)]
    superlative = consumer["superlative"]
    if superlative.get("characteristic") == "mana_value":
        sign = 1 if superlative.get("extreme") == "least" else -1
        admitted.sort(key=lambda slot: (sign * int(player.hand[slot].cmc or 0), slot))
    return admitted + [slot for slot in order if slot not in admitted]
