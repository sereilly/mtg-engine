"""What a cast the policy proposes names as its target.

One chooser for each shape of announcement, each asked of the candidate
being built (its mode, its offers, its zone: ``ai_actions``) and each choosing
out of the engine's own enumeration — the list a person's picker is built
from — so nothing proposed is a target the cast gate refuses:

* **one object** (:func:`_choose_single_object_target`) — the candidates the
  effect would act on, look-alikes dropped, each rehearsed and the one that
  does most kept (:func:`_best_target`); and for a spell that may name a
  player or a permanent, whether the permanent beats the seat
  (:func:`_better_than_the_seat`);
* **a spell on the stack** (:func:`_guarded_stack_target`,
  :func:`_chosen_stack_target`), and "a source of your choice" (CR 609.7a,
  :func:`_choose_damage_source`), which is chosen rather than targeted;
* **an Aura's host** (:func:`_choose_aura_target`), and the host of an Aura
  put onto the battlefield without a cast (:func:`choose_returning_aura_host`,
  CR 303.4f);
* **a card in a graveyard** an exile effect denies
  (:func:`_graveyard_denial_target`, on the cast's road and the activation's).

An announcement naming **several** targets or **roles** is
``ai_slot_targets``' (one pick per slot or per role, each on the side its
step wants); a divided spell's targets and shares are ``ai_divisions``'; the
player a spell names is ``ai_scoring._choose_target_for_spell``'s, which a
card's abstract worth asks too.
"""

from __future__ import annotations

import re

from .ai_weighed_cast import SPELL_TYPES
from .ai_target_sides import (
    entry_trigger_target_side,
    host_effect_side,
    host_trigger_side,
    spell_denies_its_own_target,
    spell_target_side,
)
from .ai_standing import permanent_worth
from .ai_prompt_readers import (
    exiles_a_graveyard_target,
    graveyard_denial_order,
    graveyard_price_order,
)
from .game import Game
from .mixins.stack import (
    aura_enchant_noun,
    enchant_noun_seat,
    permanent_matches_enchant_noun,
)
from .target_restrictions import forbidden_target
from .models import CardDefinition
from .oracle import compile_card_oracle
from .targeting import GRAVEYARD_TARGET_KIND, spec_roles
from .cost_pickers import spec_is_a_cost
from .ai_actions import (
    _OFFERS_ANNOUNCED,
    _announced_mode,
    _announced_steps,
    _cast_zone,
    _cast_spec,
)
from .ai_scoring import (
    choose_attack_target,
    _announcement,
    _rehearse_announcement,
    _weighed_through_the_fight,
    _leaves_nothing,
)
from .ai_cast_gates import _targets_are_optional


#: How many distinct targets one cast is rehearsed at. A rehearsal is a cast,
#: and a board of forty permanents is not forty questions worth asking.
TARGETS_WEIGHED = 8


def _graveyard_denial_target(
    game: Game, player_index: int, legal
) -> "tuple[int, int] | None":
    """``(pile's seat, slot)`` — the card an "exile target card from a
    graveyard" is aimed at — or None to name nothing.

    *legal* is the picker's own list for the announcement (``valid_targets``).
    A card in **another seat's** pile, the ones its owner could still cast
    from there first (`ai_prompt_readers.graveyard_denial_order`), then seat and
    pile order. None when no other seat's pile holds a legal card: the
    announcement is then what it always was — a seat and no slot, which the
    handler answers.

    **Why the policy names it at all.** A bare announcement falls to the
    handler's scan, "the first graveyard with a card in it, in seat order" —
    so the seat in chair 0 exiled a card of its own with Coffin Purge, Cremate,
    Headstone, Crypt Creeper, Steamclaw, Grave Robbers and Scavenging Ooze,
    and the seat in chair 1 exiled its opponent's, off one board. A graveyard
    card is announced as a seat and a slot in that seat's pile, the spelling
    the cast and activation gates check (`target_descriptions.GRAVEYARD_TARGET_KIND`).
    """
    by_seat: dict[int, list[int]] = {}
    for entry in legal or ():
        if entry.get("kind") != "graveyard":
            continue
        seat = int(entry["seat"])
        if seat != player_index:
            by_seat.setdefault(seat, []).append(int(entry["index"]))
    for seat in sorted(by_seat):
        ordered = graveyard_denial_order(game, seat, by_seat[seat])
        if not ordered:
            continue
        # One card, not "up to three": among the cards its owner could no
        # longer cast anyway, the one of greatest mana value — what a
        # recursion would most want back, and what an exile that pays its
        # source for the card (Scavenging Ooze's creature) is worth most
        # against. The castable ones stay first, whatever they cost.
        from .flashback import has_flashback

        pile = game.players[seat].graveyard
        first = ordered[0]
        if not has_flashback(pile[first], game=game, owner_seat=seat):
            first = max(
                ordered,
                key=lambda slot: (float(getattr(pile[slot], "cmc", 0) or 0), -slot),
            )
        return seat, first
    return None


def _cast_graveyard_denial(
    game: Game, player_index: int, card: CardDefinition
) -> "tuple[int, int] | None":
    """`_graveyard_denial_target` for the cast candidate being built: the
    spell's own spec and steps (its mode, its offers, the zone it leaves),
    and the picker's list for that announcement."""
    program = compile_card_oracle(card)
    if not _one_graveyard_card_is_denied(
        _cast_spec(card, program), _announced_steps(card, program)
    ):
        return None
    legal = game.cast_target_spec(
        player_index, card, optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        mode_index=_announced_mode(card), from_zone=_cast_zone(card),
    ).get("valid_targets") or []
    denial = _graveyard_denial_target(game, player_index, legal)
    own = _own_graveyard_pick(game, player_index, legal)
    if denial is None or own is None:
        return denial
    return _better_graveyard_pick(game, player_index, card, denial, own)


def _own_graveyard_pick(
    game: Game, player_index: int, legal
) -> "tuple[int, int] | None":
    """``(the caster's seat, slot)`` — the card of its **own** an exile out of
    a graveyard would cost it least (``graveyard_price_order``: one it could
    still cast from there last, then the cheapest) — or None when the
    picker offers none of its own."""
    slots = [
        int(entry["index"]) for entry in legal or ()
        if entry.get("kind") == "graveyard" and int(entry["seat"]) == player_index
    ]
    if not slots:
        return None
    return player_index, graveyard_price_order(game, player_index, slots)[0]


def _better_graveyard_pick(
    game: Game, player_index: int, card: CardDefinition,
    denial: "tuple[int, int]", own: "tuple[int, int]",
) -> "tuple[int, int]":
    """Of an opponent's card (*denial*) and one of the caster's own (*own*),
    the one whose exile does more, by rehearsal (``ai_rehearsal.rehearse``) —
    *denial* on a tie or where neither can be weighed.

    The steps behind the exile may give the card's **owner** something:
    "Exile target card from a graveyard. Its owner creates a 1/1 white Spirit
    creature token with flying." (Funeral Pyre.) The denial reading aimed it
    at the opponent's pile every time, so the cast handed the opponent a
    flier — and the rehearsal, reading that, held a spell that cast at the
    caster's own land card makes the caster one. A plain exile reads the same
    either way (no standing counts a graveyard), so it keeps the denial.
    """
    best, best_swing = denial, None
    for seat, slot in (denial, own):
        rehearsal = _rehearse_announcement(
            game, player_index, card,
            _announcement(game, card, target=seat, caster=player_index, permanent_index=slot),
        )
        if rehearsal is None or not rehearsal.accepted or not rehearsal.changed:
            continue
        if best_swing is None or rehearsal.swing > best_swing + 1e-9:
            best, best_swing = (seat, slot), rehearsal.swing
    return best


def _one_graveyard_card_is_denied(spec, instructions) -> bool:
    """Whether an announcement described by *spec* names exactly **one card in
    a graveyard** and the steps behind it exile that card — the shape
    `_graveyard_denial_target` answers."""
    return (
        isinstance(spec, dict)
        and spec.get("kind") == GRAVEYARD_TARGET_KIND
        and not spec_roles(spec)
        and not spec_is_a_cost(spec)
        and not spec.get("max_targets")
        and not spec.get("x_targets")
        and exiles_a_graveyard_target(instructions)
    )


#: Printed phrases that make an Aura's effect a cost to whoever controls its
#: host, so it belongs on an opponent's permanent. Text probes, and tuning
#: like every other weight in this module.
_HARMFUL_AURA_MARKERS = (
    "gets -",
    "doesn't untap",
    "tap enchanted",
    "you control enchanted",
    # "When this Aura enters, gain control of enchanted land until end of
    # turn." (Wellspring.) A steal of the host, as the line above is; until
    # SCG it read harmful only because "untap enchanted land" holds the
    # letters "tap enchanted" (see the word reading below).
    "gain control of enchanted",
    "can't attack",
    "can't block",
)
#: The markers as **words**: "tap enchanted" is a marker, and it is also the
#: last two words of "{U}: Untap enchanted creature" — a gift its controller
#: pays for. Read as a substring it made Pemmin's Aura, Instill Energy and
#: Nature's Chosen harmful, so an AI seat cast Pemmin's Aura on a person's
#: creature and then paid to untap it for them (SCG Phase 5, smoke game 1).
_HARMFUL_AURA_MARKER_WORDS = re.compile(
    r"\b(?:" + "|".join(re.escape(marker) for marker in _HARMFUL_AURA_MARKERS) + r")"
)
#: …and the Auras whose whole effect is a price charged to **the host's
#: controller** rather than to the host: "this Aura deals 1 damage to that
#: player" (Wanderlust, Cursed Land, Warp Artifact), "…to that land's
#: controller" (Psychic Venom), "its controller loses life equal to its power"
#: (Death Watch). None of them printed a phrase the list above reads, so the
#: AI cast every one of them onto its **own** permanent — 21 of the 22 shipped
#: Auras printing one, measured with a host of every kind on both boards — and
#: paid the damage itself every upkeep. Read the same way from a Licid's text.
_HARMFUL_AURA_PATTERN = re.compile(
    r"damage to (?:that player|its controller|that [a-z]+'s controller)"
    r"|(?:that player|its controller) loses (?:\d+|x|life)"
)


def _aura_harms_its_host(card: CardDefinition) -> bool:
    """Whether *card*'s text, as an Aura, works against the permanent it
    enchants and that permanent's controller — so the AI puts it on an
    opponent's permanent rather than its own.

    One reader for the two ways an Aura gets a host: cast onto one
    (`_choose_aura_target`), and a permanent that *becomes* one and attaches
    itself (`ai_valuation.source_becomes_an_aura`, the Licids), where the
    activation chooser asks the same question of the same text.
    """
    text = (card.oracle_text or "").lower()
    return (
        _HARMFUL_AURA_MARKER_WORDS.search(text) is not None
        or _HARMFUL_AURA_PATTERN.search(text) is not None
        or _host_abilities_harm_it(card)
        or _host_triggers_harm_it(card, text)
    )


#: An Aura's printed gift to its host — "Enchanted creature gets +3/+3"
#: (Spinal Graft, Unstable Mutation), "…has first strike and trample"
#: (Aggression): the boon a host-harming trigger beside it is the price of,
#: so such an Aura stays on its controller's side.
_HOST_GIFT = re.compile(r"\benchanted [a-z]+ (?:gets \+|has |gains )")


def _host_triggers_harm_it(card: CardDefinition, text: str) -> bool:
    """Whether *card*'s triggered abilities work against its host
    (``ai_target_sides.host_trigger_side``: "When enchanted land becomes
    tapped, destroy it", Kudzu and Blight; "Whenever enchanted creature
    becomes tapped, put a -0/-2 counter on it", Spirit Shackle) while its
    text gives the host nothing (:data:`_HOST_GIFT`). No marker above reads
    a destruction, so the AI cast Kudzu on its own Forest — and destroyed the
    land the first time it tapped it for mana (kg5). Read off the compiled
    program, so it names no card."""
    if _HOST_GIFT.search(text):
        return False
    return any(
        host_trigger_side(trigger.instruction) == "opponent"
        for trigger in compile_card_oracle(card).triggered_abilities
    )


def _host_abilities_harm_it(card: CardDefinition) -> bool:
    """Whether every one of *card*'s activated abilities that reads as one
    side's or the other's on its host (``ai_target_sides.host_effect_side``)
    reads as the opponent's: "{1}{B}: Put a -1/-1 counter on enchanted
    creature." (Torture.) The Aura's controller pays for those, so its host is
    the creature they are meant to hurt. No marker above reads a counter, and
    the AI cast Torture on its own creature — the host-ability census's one
    finding past Pemmin's Aura (SCG Phase 5). Read off the compiled program,
    so it names no card; an Aura with no such ability is left to the text."""
    sides = {
        host_effect_side(ability.instruction)
        for ability in compile_card_oracle(card).activated_abilities
        if ability.instruction is not None
    } - {None}
    return sides == {"opponent"}


def choose_returning_aura_host(game: Game, seat: int, card: CardDefinition, legal: list):
    """Which of *legal* an Aura card that *seat* is putting onto the
    battlefield enchants, where the effect names no host (CR 303.4f:
    Replenish, Cleansing Meditation).

    The cast chooser's question asked of a choice that is not a target: an
    Aura whose text works against its host (``_aura_harms_its_host``) goes on
    a permanent somebody else controls, any other on *seat*'s own. A
    preference, not a filter — with only the other side's permanents legal,
    one of them is still the answer — and stable, so board order breaks every
    tie and a seed still reproduces a run.

    The answer for every seat nobody asks, and the default of the prompt an
    interactive seat is asked (``permanent_choice`` with ``default_prefers:
    "returning_aura_host"``), so a seat answered for lands where this would.
    """
    harmful = _aura_harms_its_host(card)
    ranked = sorted(
        legal,
        key=lambda host: (
            (game.controller_index_of(host) == seat) == harmful,
            # …and, on the other side, a host the Aura's own -X/-X kills
            # first (`aura_kills_its_host`): Screams from Within on a
            # Llanowar Elves is a creature gone and the Aura back again,
            # on a Grizzly Bears a 1/1 left standing (DST W1G9).
            not (harmful and aura_kills_its_host(card, host)),
            copies_worn(host, card),
        ),
    )
    return ranked[0]


def aura_kills_its_host(card: CardDefinition, host) -> bool:
    """Whether *card*'s static P/T grant, attached to *host*, leaves it with
    0 or less toughness (CR 704.5f) — "Enchanted creature gets -1/-1" on an
    X/1. Read through the grant the layers apply (``aura_grants.
    aura_static_pt_grant``) and the host's toughness through them too."""
    from .aura_grants import aura_static_pt_grant

    grant = aura_static_pt_grant(card.oracle_text or "")
    if grant is None or grant[1] >= 0 or not host.is_creature:
        return False
    return host.effective_toughness + grant[1] <= 0


def copies_worn(host, card: CardDefinition) -> int:
    """How many Auras attached to *host* are the card *card* is — a second
    one of which adds little or nothing to the first: a second "Enchanted
    creature has flying", a second Pacifism, a second set of the same
    activated abilities on one creature.

    The diminishing value an Aura's host is ranked by after its side: an AI
    seat put all five Pemmin's Auras it cast on one Prodigal Sorcerer (SCG
    Phase 5's re-check), because the host chooser took the first legal
    creature every time. Asked by what the attached card *is*
    (``copies.card_identity``, every printed field), never by its name."""
    from .aura_attachment import auras_attached_to
    from .copies import card_identity

    wanted = card_identity(card)
    return sum(
        1 for aura in auras_attached_to(host)
        if card_identity(aura.card) == wanted
    )


def _choose_aura_target(game: Game, caster_index: int, card: CardDefinition) -> tuple[int, int] | None:
    """Pick (player_index, permanent_index) for an Aura's enchant target.

    Harmful auras go on an opponent's permanent, beneficial ones on the caster's.
    Returns None when the preferred player has no legal target — the Aura is
    unplayable this turn rather than cast onto a permanent that helps the enemy.
    """
    noun = aura_enchant_noun(card)
    if noun is None:
        return None
    harmful = _aura_harms_its_host(card)
    if not harmful and enchant_noun_seat(noun) != "you":
        # A gift whose own ability can shrink its host to nothing ("{1}:
        # Enchanted creature gets +1/-1 or -1/+1", Pemmin's Aura) is removal
        # on an opponent's creature that ability can kill.
        killed = _host_its_ability_kills(game, caster_index, card, noun)
        if killed is not None:
            return killed
    target_player_index = choose_attack_target(game, caster_index) if harmful else caster_index
    # "Enchant creature **you control**" (Cocoon): however "harmful" the text
    # reads, the clause forbids an opponent's permanent — the same gate the
    # cast path applies (CR 601.2c), asked here so the AI never spends a turn
    # on a cast the game then refuses.
    seat_clause = enchant_noun_seat(noun)
    if seat_clause == "you":
        target_player_index = caster_index
    elif seat_clause == "opponent" and target_player_index == caster_index:
        target_player_index = choose_attack_target(game, caster_index)
    # Of the legal hosts, one the Aura's own -X/-X kills (`aura_kills_its_host`:
    # Weakness on an X/1), then the first that wears no copy of this Aura
    # (`copies_worn`, the diminishing value of a second one), then the first.
    legal: list[tuple[bool, int, int]] = []
    for permanent_index, permanent in enumerate(game.players[target_player_index].battlefield):
        # The spell's own printed targeting restriction (CR 601.2c). Asked here
        # as well as at the cast, and through the same function: a choice only
        # the cast path refuses is an AI turn spent on an action the game then
        # rejects, and a human seat offered a target it cannot take.
        if forbidden_target(game, card, permanent, caster_index):
            continue
        # CR 702.16b: an Aura with a quality cannot be cast targeting a
        # permanent with protection from it. Asked through the cast path's own
        # function for the same reason `forbidden_target` is, one line up — and
        # it was missing, so the AI would pick a creature wearing White Ward for
        # a white Aura, be refused, and pick it again next turn. Invisible until
        # the simulator started building decks that contain both.
        if not game._can_be_targeted(permanent, card, caster_index=caster_index):
            continue
        if permanent_matches_enchant_noun(permanent, noun):
            spares = not (harmful and aura_kills_its_host(card, permanent))
            legal.append((spares, copies_worn(permanent, card), permanent_index))
    if not legal:
        return None
    return target_player_index, min(legal)[2]


def _host_shrink(card: CardDefinition) -> "tuple[int, dict] | None":
    """``(toughness, mana)`` — the most toughness one activation of *card*'s
    own host abilities takes from its host, and that activation's mana — for
    an ability that costs mana and nothing else (so it can be repeated) and
    whose effect lands on the host alone, by a mode or a step: "{1}:
    Enchanted creature gets +1/-1 or -1/+1" (Pemmin's Aura), "{R}: Enchanted
    creature gets +1/-1" (Flowstone Blade). None for every other Aura."""
    from dataclasses import replace

    best = None
    for ability in compile_card_oracle(card).activated_abilities:
        cost = ability.cost
        if ability.instruction is None or cost is None or not any(cost.mana.values()):
            continue
        if replace(cost, mana={}) != type(cost)(mana={}):
            continue
        taken = _toughness_taken(ability.instruction)
        if taken and (best is None or taken > best[0]):
            best = (taken, {symbol: int(n) for symbol, n in cost.mana.items() if n})
    return best


def _toughness_taken(instruction) -> int:
    """The most toughness *instruction* takes from the host: a host P/T step
    (``pump_enchanted_creature``) with a negative toughness, read through
    ``choose_one``'s modes and a sequence's steps."""
    payload = getattr(instruction, "payload", None) or {}
    if instruction.kind == "choose_one":
        return max(
            (_toughness_taken(mode["instruction"]) for mode in payload.get("modes") or ()
             if isinstance(mode, dict) and mode.get("instruction") is not None),
            default=0,
        )
    if instruction.kind == "sequence":
        return sum(_toughness_taken(step) for step in payload.get("steps") or ())
    toughness = payload.get("toughness")
    if instruction.kind == "pump_enchanted_creature" and isinstance(toughness, int) and toughness < 0:
        return -toughness
    return 0


def _host_its_ability_kills(game: Game, caster_index: int, card: CardDefinition, noun):
    """``(seat, slot)`` of the opponent's creature *card*'s host shrink
    (:func:`_host_shrink`) kills with **one** activation once it enchants it
    — its toughness left no more than one activation takes, the caster's
    lands able to pay for one — the most valuable such creature first
    (``permanent_worth``), or None. A legal host by the cast path's own gates
    (``forbidden_target``, ``_can_be_targeted``, the enchant noun). The kill
    is the activation chooser's to make later, which rehearses a host P/T
    trade on the host it finds (``ai_target_sides.host_effect_by_the_moment``)
    one activation at a time — so a host several activations would kill, each
    a gift until the last, is not one it would finish."""
    shrink = _host_shrink(card)
    if shrink is None:
        return None
    taken, mana = shrink
    colours = [symbol for symbol in mana if symbol != "generic"]
    paying = [
        permanent for permanent in game.controlled_by(caster_index)
        if permanent.has_type("land") and (
            not colours
            or set(colours) <= set(game._land_payment_colors(permanent) or ())
        )
    ]
    activations = len(paying) // max(1, sum(mana.values()))
    if activations <= 0:
        return None
    seat = choose_attack_target(game, caster_index)
    best = None
    for slot, permanent in enumerate(game.players[seat].battlefield):
        if not permanent.is_creature or not permanent_matches_enchant_noun(permanent, noun):
            continue
        if forbidden_target(game, card, permanent, caster_index):
            continue
        if not game._can_be_targeted(permanent, card, caster_index=caster_index):
            continue
        if permanent.effective_toughness - permanent.damage_marked > taken:
            continue
        worth = permanent_worth(permanent, now=False)
        if best is None or worth > best[0]:
            best = (worth, slot)
    return None if best is None else (seat, best[1])


#: Cast specs whose legal answers are not permanents on a battlefield — a
#: player, a spell, a card in a graveyard or a hand, a choice of modes. The
#: single-object chooser below has nothing to say about them.
_NOT_OBJECT_SPECS = frozenset({
    "none", "modal", "player", "stack", "graveyard_creature", "hand_card",
    "spell_or_permanent",
})


def _choose_single_object_target(
    game: Game, caster_index: int, card: CardDefinition, preferred_seat: int,
    *, x_value: int | None = None,
):
    """Name the one permanent a one-object-target spell is cast at:
    ``(seat, index, [permanent_id])``, ``()`` when the side the effect wants
    holds no legal target, or None when *card* is not such a spell.

    **Which permanent is the one the cast does most at.** Every legal target
    on the side the effect wants is a different cast, so each is rehearsed
    (`_best_target`) and the largest swing named: the creature a -2/-2 kills
    rather than the one it only shrinks, the dearest thing a destroy may
    take, the body a pump does most on. This named the first legal permanent
    in battlefield order — whichever the seat happened to play first.

    A spell that may name **a player or a permanent** ("any target") is
    weighed the same way against the seat it would otherwise be aimed at:
    three damage is worth a creature it kills more often than it is worth
    three life (`_better_than_the_seat`).

    The cast used to name a **seat** and leave the permanent to the handler's
    board scan — the headless convention, which W1G2 measured 156 of 182
    creature-targeting spells accepting. Two ways that resolved doing nothing,
    both measured in NEM's simulation: a handler with no scan to fall into
    (Sivvi's Valor: "its target is gone"), and a seat with no permanent the
    printed noun admits (Topple aimed at a seat whose creatures were not the
    greatest). Naming the permanent out of the engine's own enumeration — the
    list the browser's picker offers a human — answers both, and the first
    legal permanent on the seat is the one the scan would have taken.

    Which seat is ``ai_target_sides.spell_target_side``: a side the effect wants
    with nothing legal on it is ``()``, because the alternative is aiming a
    denial at the caster's own board or a gift at an opponent's. With no side,
    *preferred_seat* (the score's choice) first and then any seat — a spell that
    can only do something on the other board is cast there rather than at
    nothing. A spec offering a **player** is left alone: "any target" damage is
    aimed at a face by the seat it already carries.
    """
    program = compile_card_oracle(card)
    spec = _cast_spec(card, program)
    # "Target spell **or permanent**" (the five Laces): on a battlefield the
    # answer is a permanent like any other, and a cast that named only a seat
    # left the handler to find one on it — the caster's own, which with
    # nothing of the caster's there was a cast that did nothing.
    spell_or_permanent = isinstance(spec, dict) and spec.get("kind") == "spell_or_permanent"
    if (
        not isinstance(spec, dict)
        or (spec.get("kind") in _NOT_OBJECT_SPECS and not spell_or_permanent)
        or spec_roles(spec)
        or _targets_are_optional(_announced_steps(card, program))
        # A spell with **no target**, whose derived spec is the picker for its
        # printed cost ("…, sacrifice a creature. Draw two cards."). A payment
        # is not a target (CR 601.2b vs 601.2c): naming the creature here put
        # an id on the *target* channel for a spell that has none, which is not
        # where the cost path reads its payer from — and the permanent named is
        # the one about to leave.
        or spec_is_a_cost(spec)
    ):
        return None
    legal = game._enumerate_targets(
        caster_index, card, spec, for_cast=True,
        # The announcement *spec* was derived under (CR 702.33g), so the
        # per-candidate probe judges each permanent against that same spec.
        optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        # ...and the mode (CR 601.2b): the probe reads the chosen mode's own
        # instruction, so a list asked with none is mode 0's list.
        mode_index=_announced_mode(card),
    )
    if spell_or_permanent:
        # The spells on offer are `_guarded_stack_target`'s and the engine's.
        legal = [entry for entry in legal if entry.get("kind") == "permanent"]
    if not legal:
        return None
    # A seat among the answers: "any target", "target player or planeswalker".
    names_a_seat = any(entry.get("kind") != "permanent" for entry in legal)
    legal = [entry for entry in legal if entry.get("kind") == "permanent"]
    if names_a_seat:
        if not legal or card.primary_type not in SPELL_TYPES:
            return None
        return _better_than_the_seat(
            game, caster_index, card, legal, preferred_seat, x_value
        )
    if spell_denies_its_own_target(card):
        # "Return target permanent you control to its owner's hand"
        # (Scapegoat): a denial the printed words aim at the caster's own
        # board, which this policy has no rescue to time it for.
        return ()
    if spec.get("source_of_choice"):
        return _choose_damage_source(game, caster_index, legal)
    # "Destroy target permanent **if it's blue**" (Pyroblast): every permanent
    # is a legal target and only a blue one is destroyed. Named from the ones
    # the effect would reach, and not cast when it would reach none and do
    # nothing else (`_reached_by_the_effect`).
    legal = _reached_by_the_effect(game, caster_index, card, legal)
    if not legal:
        return ()
    # A permanent's entry trigger, whose target this engine names as the
    # permanent is cast: `spell_target_side` has nothing to read for it.
    side = spell_target_side(card) or entry_trigger_target_side(card)
    others = [seat for seat in range(len(game.players)) if seat != caster_index]
    if side == "you":
        order = [caster_index]
    elif side == "opponent":
        first = choose_attack_target(game, caster_index)
        order = [first] + [seat for seat in others if seat != first]
    else:
        order = [preferred_seat] + [
            seat for seat in [caster_index, *others] if seat != preferred_seat
        ]
    candidates = _target_candidates(game, legal, order)
    if not candidates:
        return ()
    return _best_target(game, caster_index, card, candidates, x_value)


def _target_candidates(game: Game, legal: list[dict], order: list[int]) -> list[tuple]:
    """*legal* — one-object candidates off the engine's own list — as
    ``(seat, index, [permanent_id])``, the seats in *order* and each seat's
    permanents as the enumeration lists them."""
    candidates: list[tuple] = []
    for seat in order:
        for entry in legal:
            if entry.get("seat") != seat:
                continue
            permanent_id = game.permanent_id_of(game.permanent_at(seat, entry["index"]))
            if isinstance(permanent_id, int):
                candidates.append((seat, entry["index"], [permanent_id]))
    return candidates


def _distinct_targets(game: Game, candidates: list[tuple]) -> list[tuple]:
    """*candidates* with look-alikes dropped — two untapped Forests are one
    question — and at most `TARGETS_WEIGHED` of them kept: the first in
    order, then the dearest (``ai_standing.permanent_worth``) and the
    frailest, since the target a spell does most at is as often the one it
    can just kill as the one worth most."""
    seen: set = set()
    distinct: list[tuple] = []
    for candidate in candidates:
        permanent = game.permanent_by_id(candidate[2][0])
        if permanent is None:
            continue
        creature = bool(permanent.is_creature)
        look = (
            candidate[0], permanent.card.name, permanent.tapped,
            creature and permanent.effective_power,
            creature and permanent.effective_toughness,
            permanent.damage_marked, permanent.attacking, permanent.blocked,
            tuple(sorted(permanent.metadata)),
        )
        if look in seen:
            continue
        seen.add(look)
        distinct.append((candidate, permanent, creature))
    if len(distinct) <= TARGETS_WEIGHED:
        return [candidate for candidate, _permanent, _creature in distinct]
    kept: list[int] = [0]
    by_worth = sorted(
        range(len(distinct)),
        key=lambda slot: (-permanent_worth(distinct[slot][1]), slot),
    )
    by_frailty = sorted(
        (slot for slot in range(len(distinct)) if distinct[slot][2]),
        key=lambda slot: (distinct[slot][1].effective_toughness, slot),
    )
    for dear, frail in zip(by_worth, by_frailty + by_worth):
        for slot in (dear, frail):
            if slot not in kept and len(kept) < TARGETS_WEIGHED:
                kept.append(slot)
    return [distinct[slot][0] for slot in sorted(kept)]


def _best_target(
    game: Game, caster_index: int, card: CardDefinition, candidates: list[tuple],
    x_value: int | None,
):
    """The candidate whose cast does most (``ai_rehearsal.rehearse``), the
    earlier one on a tie — or ``()`` when every one of them is a cast the
    engine refuses or that changes nothing.

    One candidate is not rehearsed here: there is nothing to choose, and the
    cast built from it is rehearsed where it is scored. Neither is anything
    when no rehearsal can be run; the first candidate is then the answer it
    always was.
    """
    distinct = _distinct_targets(game, candidates)
    if len(distinct) <= 1:
        return distinct[0] if distinct else candidates[0]
    best = None
    best_swing = None
    rehearsed = False
    for seat, index, ids in distinct:
        # "Destroy target artifact with mana value X": the target fixes X.
        implied = (
            game._x_implied_by_target(card, seat, index, None)
            if x_value is not None else None
        )
        announcement = _announcement(
            game, card, target=seat, caster=caster_index, permanent_index=index,
            permanent_ids=ids, x_value=x_value if implied is None else implied,
        )
        rehearsal = _weighed_through_the_fight(
            game, caster_index, card, announcement,
            _rehearse_announcement(game, caster_index, card, announcement),
        )
        if rehearsal is None:
            continue
        rehearsed = True
        if not rehearsal.accepted or not rehearsal.changed or _leaves_nothing(rehearsal):
            continue
        if best_swing is None or rehearsal.swing > best_swing:
            best, best_swing = (seat, index, ids), rehearsal.swing
    if best is not None:
        return best
    return () if rehearsed else distinct[0]


def _better_than_the_seat(
    game: Game, caster_index: int, card: CardDefinition, legal: list[dict],
    preferred_seat: int, x_value: int | None,
):
    """For a spell that may name a player **or** a permanent: the permanent
    whose cast is measured to do more than naming the seat alone, or None to
    keep the seat.

    The permanents weighed are on the side the seat choice already says the
    effect is for — an opponent's when the seat is one (damage), the
    caster's own when it is the caster's (a shield).
    """
    hostile = preferred_seat != caster_index
    seats = [
        seat for seat in range(len(game.players))
        if (seat != caster_index) == hostile
    ]
    order = [preferred_seat] + [seat for seat in seats if seat != preferred_seat]
    candidates = _distinct_targets(game, _target_candidates(game, legal, order))
    if not candidates:
        return None
    at_seat = _announcement(
        game, card, target=preferred_seat, caster=caster_index, x_value=x_value,
    )
    at_the_seat = _weighed_through_the_fight(
        game, caster_index, card, at_seat,
        _rehearse_announcement(game, caster_index, card, at_seat),
    )
    if at_the_seat is None:
        return None
    if (
        at_the_seat.accepted and at_the_seat.fleeting
        and game.current_turn_phase != "combat"
        and not (at_the_seat.combat_ahead and at_the_seat.creature_ahead)
    ):
        # Aimed at the player it is over with the turn, and with no combat
        # still to come this reading has no damage in it for it to stop or to
        # add to: what may name "any target" is damage, which a player keeps,
        # or a shield — and a shield with nothing coming is as much nothing
        # on a creature as on its controller. So the permanents are not each
        # rehearsed to learn that, and the seat stands. Before the caster's
        # own fight they are: the 2/2 about to trade is what a shield is for.
        return None
    best = None
    best_swing = (
        at_the_seat.swing
        if at_the_seat.accepted and not _leaves_nothing(at_the_seat) else None
    )
    for seat, index, ids in candidates:
        announcement = _announcement(
            game, card, target=seat, caster=caster_index, permanent_index=index,
            permanent_ids=ids, x_value=x_value,
        )
        rehearsal = _weighed_through_the_fight(
            game, caster_index, card, announcement,
            _rehearse_announcement(game, caster_index, card, announcement),
        )
        if (
            rehearsal is None or not rehearsal.accepted or not rehearsal.changed
            or _leaves_nothing(rehearsal)
        ):
            continue
        if best_swing is None or rehearsal.swing > best_swing:
            best, best_swing = (seat, index, ids), rehearsal.swing
    return best


#: `if_then` conditions that are a property of **the permanent the spell
#: targets** — the clause is on the effect, not on the target phrase, so the
#: engine's picker rightly offers every permanent (CR 608.2b reads the printed
#: target phrase, and Pyroblast's says no colour) and a target that fails it
#: is one the spell does nothing to.
#:
#: Named, where "evaluate whatever condition is there" would be shorter,
#: because a condition about something *else* (was this spell kicked, did a
#: creature die this turn) cannot be asked before the cast exists, and
#: answering it early would withhold spells for a reason that is not true. A
#: kind left off costs the old behaviour and nothing more.
_TARGET_GUARDS = frozenset({
    "target_is_color", "target_shares_most_common_color",
    # "Counter target spell **if it was kicked**" (Ertai's Trickery): CR
    # 702.33d's fact about the *targeted* spell, which is on the stack to be
    # asked. Not `was_kicked`, which is about this one.
    "target_was_kicked",
    # "Destroy target nonland permanent **if another permanent with the same
    # name is on the battlefield**" (Winnow) — `_is_a_target_guard` admits the
    # kind only in that spelling; "a card with the same name as that spell"
    # (Bazaar of Wonders) is about a spell some trigger fired on.
    "same_named_object",
    # "Counter target spell if it shares a color with a creature you control."
    # (Jaded Response.) A property of the spell the cast names, read against
    # the caster's own board as it stands — askable before the cast exists.
    "target_shares_color_with_matching",
})


def _is_a_target_guard(condition) -> bool:
    """Whether *condition* is a `_TARGET_GUARDS` clause about the object the
    spell targets."""
    if not isinstance(condition, dict) or condition.get("kind") not in _TARGET_GUARDS:
        return False
    if condition.get("kind") == "same_named_object":
        return condition.get("same_name_as") == "target"
    return True


def _reached_by_the_effect(
    game: Game, caster_index: int, card: CardDefinition, legal: list[dict]
) -> list[dict]:
    """The entries of *legal* — one-object candidates, off the engine's own
    list — that the candidate being built would actually **do something to**.

    All of them, for every spell whose effect is not guarded by a condition on
    its target (`_TARGET_GUARDS`). For one that is: the permanents the guard
    holds for, asked of the engine's own evaluator
    (`control_flow.evaluate_condition`) with that permanent as the target — so
    the policy and the resolution cannot disagree about what "if it's blue"
    means, layers and all. When the guard holds for none of them the answer
    is empty only if the guarded step is the whole spell; where the spell
    does something else as well ("…Draw a card at the beginning of the next
    turn's upkeep", Soul Rend) the candidates stand, because the cast is not
    nothing.

    This surfaced with the mode chooser and was true before it: an AI seat
    holding Hydroblast or Pyroblast in its main phase now weighs "Destroy
    target permanent if it's red", and across ten seeded Ice Age games it
    cast that at ten permanents of the wrong colour — a legal cast and a card
    spent on nothing. Soul Rend and Barrin's Unmaking, which print no mode,
    were aimed the same way all along.
    """
    from .game_types import OracleExecutionContext
    from .handlers.control_flow import evaluate_condition

    guards, whole_spell = _target_guards(card, on_a_spell=False)
    if not guards:
        return legal

    def reached(entry: dict) -> bool:
        permanent = game.permanent_at(entry["seat"], entry["index"])
        if permanent is None:
            return False
        context = OracleExecutionContext(
            caster=game.players[caster_index],
            target=game.players[entry["seat"]],
            card=card,
            target_permanent_index=[entry["index"]],
            target_permanent_id=[permanent.permanent_id],
        )
        return any(evaluate_condition(game, context, guard) for guard in guards)

    kept = [entry for entry in legal if reached(entry)]
    if kept or whole_spell:
        return kept
    return legal


def _target_guards(card: CardDefinition, *, on_a_spell: bool) -> "tuple[list[dict], bool]":
    """``(conditions, whole_spell)``: the `_TARGET_GUARDS` conditions that
    guard the candidate being built's steps, for a target on the stack
    (*on_a_spell*) or on the battlefield — and whether those guarded steps
    are **everything** the spell does, so that a target every guard fails for
    is a cast that does nothing at all.

    A guard with an ``else`` arm is not one: the spell does something either
    way, and which is better is a valuation this does not make.
    """
    steps = _announced_steps(card, compile_card_oracle(card))
    guards = [
        condition
        for step in steps
        if step.kind == "if_then"
        and not (step.payload or {}).get("else")
        and _is_a_target_guard(condition := (step.payload or {}).get("condition"))
        and (condition.get("target") == "spell") == on_a_spell
    ]
    return guards, bool(guards) and len(guards) == len(steps)


def _guarded_stack_target(game: Game, caster_index: int, card: CardDefinition):
    """The spell on the stack a cast whose effect is guarded by a condition
    on **that spell** should name — its engine (bottom-first) stack index;
    ``()`` when the guard holds for no spell the cast may name and the guarded
    step is the whole spell; None for every other cast, which names nothing
    and is answered by the engine as it always was.

    `_reached_by_the_effect` for the other zone a target can be in. "Counter
    target spell **if it's blue**" (Pyroblast, Hydroblast, Burnout) may be
    announced at any spell, and the web AI's priority response announced it at
    whatever was on top: a Pyroblast spent on a green creature spell, on the
    tree before the mode chooser and after it. The topmost spell the guard
    holds for, off the engine's own list of what the announcement may name.
    """
    from .game_types import OracleExecutionContext
    from .handlers.control_flow import evaluate_condition

    guards, whole_spell = _target_guards(card, on_a_spell=True)
    if not guards:
        return None
    spec = _cast_spec(card, compile_card_oracle(card))
    if not isinstance(spec, dict) or spec.get("kind") != "stack":
        return None
    depth = len(game.stack)
    reached: list[int] = []
    for entry in game._enumerate_targets(
        caster_index, card, spec, for_cast=True,
        optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        mode_index=_announced_mode(card),
    ):
        top_first = entry.get("stack_index")
        if entry.get("kind") != "stack" or not isinstance(top_first, int):
            continue
        index = depth - 1 - top_first
        if not 0 <= index < depth:
            continue
        item = game.stack[index]
        context = OracleExecutionContext(
            caster=game.players[caster_index],
            target=game.players[item.caster_index],
            card=card,
            stack_target=item,
        )
        if any(evaluate_condition(game, context, guard) for guard in guards):
            reached.append(index)
    if reached:
        return max(reached)
    return () if whole_spell else None


def _chosen_stack_target(
    game: Game, caster_index: int, card: CardDefinition, target_seat: int,
):
    """Which spell on the stack a cast whose target **is** a spell names, where
    `_guarded_stack_target` has no guard to choose by: its engine
    (bottom-first) stack index, ``()`` when no candidate is worth casting at,
    or None for a cast that targets no spell.

    **Each candidate is a different cast, so each is rehearsed** and the
    largest swing named, as `_best_target` does for a permanent. With one
    candidate there is nothing to choose and it is named as it is. This left
    the choice to the engine's default for a bare announcement — the first
    entry of the picker's list, with the caster's own seat's first — which
    was harmless while a seat answered only one spell, and became a
    misplay the day it could answer a response: a seat whose spell was met
    by a Confound cast Gainsay ("Counter target blue spell") at **its own**
    blue Aura beneath it, and the Confound fizzled over a spell that was
    gone anyway.
    """
    spec = _cast_spec(card, compile_card_oracle(card))
    if not isinstance(spec, dict) or spec.get("kind") != "stack":
        return None
    depth = len(game.stack)
    candidates: list[int] = []
    for entry in game._enumerate_targets(
        caster_index, card, spec, for_cast=True,
        optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        mode_index=_announced_mode(card),
    ):
        top_first = entry.get("stack_index")
        if entry.get("kind") != "stack" or not isinstance(top_first, int):
            continue
        index = depth - 1 - top_first
        if 0 <= index < depth and index not in candidates:
            candidates.append(index)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    best = None
    best_swing = None
    rehearsed = False
    # Topmost first, so a tie names the spell most recently cast.
    for index in sorted(candidates, reverse=True):
        announcement = {
            **_announcement(game, card, target=target_seat, caster=caster_index),
            "target_stack_index": index,
        }
        rehearsal = _rehearse_announcement(game, caster_index, card, announcement)
        if rehearsal is None:
            continue
        rehearsed = True
        if not rehearsal.accepted or not rehearsal.changed or _leaves_nothing(rehearsal):
            continue
        if best_swing is None or rehearsal.swing > best_swing:
            best, best_swing = index, rehearsal.swing
    if best is not None:
        return best
    return () if rehearsed else max(candidates)


def _choose_damage_source(game: Game, caster_index: int, legal: list[dict]):
    """Name "a source of your choice" (CR 609.7a) for a spell that shields
    against one: ``(seat, index, [permanent_id])``, or ``()`` when no source on
    the table is one this seat would want to name.

    A source is not a target, so no effect has a *side* for it
    (``spell_target_side`` is None) and the chooser above took the first legal
    permanent on the caster's own seat — its own first land. Legal, and a card
    spent on nothing: three of seven simulated Samite Ministrations, and every
    Reverse Damage, Eye for an Eye, Shadowbane, Reflect Damage and
    Invulnerability an AI seat ever cast.

    The choice is the one the engine makes for a seat that names nothing
    (``handlers/prevention.default_damage_source``, written for the activated
    half of the same phrase): the opposing source most likely to deal damage
    this turn. Asked of that function rather than restated, and then held to
    the announcement's own enumeration — where the printed phrase narrows what
    may be chosen, the same rule is applied to what it admits. With no
    opposing creature there is nothing worth shielding against and the card is
    kept for a board that has one.
    """
    from .handlers.prevention import default_damage_source

    by_id: dict[int, tuple[int, int]] = {}
    for entry in legal:
        permanent = game.permanent_at(entry["seat"], entry["index"])
        permanent_id = game.permanent_id_of(permanent)
        if isinstance(permanent_id, int):
            by_id[permanent_id] = (entry["seat"], entry["index"])
    chosen = default_damage_source(game, caster_index)
    chosen_id = getattr(chosen, "permanent_id", None)
    if chosen_id in by_id:
        seat, index = by_id[chosen_id]
        return seat, index, [chosen_id]
    admitted = [
        permanent
        for permanent_id, (seat, _index) in by_id.items()
        if seat != caster_index
        and (permanent := game.permanent_by_id(permanent_id)) is not None
        and permanent.is_creature
    ]
    if not admitted:
        return ()
    best = max(
        admitted,
        key=lambda perm: (bool(perm.attacking), perm.effective_power, -perm.permanent_id),
    )
    seat, index = by_id[best.permanent_id]
    return seat, index, [best.permanent_id]
