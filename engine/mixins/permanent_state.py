from __future__ import annotations

import re
from dataclasses import replace


from ..enter_effects import (
    ENTERED_BATTLEFIELD_TURN,
    entry_exile_requirement,
    entry_sacrifice_requirement,
    sacrifice_any_number_on_enter,
    CHOOSE_COLOR_AND_OPPONENT_ON_ENTER,
    chooses_color_on_enter,
    chooses_two_land_types_on_enter,
    chooses_creature_type_on_enter,
    CHOOSE_CARD_NAME_ON_ENTER,
    chooses_opponent_on_enter,
    COPY_ARTIFACT_ON_ENTER,
    COPY_CREATURE_ON_ENTER,
    ENTERS_TAPPED,
    enters_with_x_pt_counters,
    enters_with_x_named_counters,
    choose_number_on_enter,
    pay_any_life_on_enter,
    enters_with_pt_counters,
    enters_with_named_counter,
    LOSE_LIFE_EQUAL_TO_TOTAL_ON_ENTER,
    NO_MAXIMUM_HAND_SIZE,
    choosable_bodies,
    SPEND_ANY_COLOR,
    SPEND_WHITE_AS_RED,
)
from ..auras import aura_protection_colors, auras_attached_to
from .. import copies
from ..named_counters import add_counters as add_named_counters
from ..named_counters import counters_on
from ..tokens import make_token_card
from ..keywords import (add_derived_grant, add_derived_removal,
                        clear_derived_grants)
from ..enter_tapped_statics import (
    ENTER_TAPPED_STATIC_KIND,
    enter_tapped_filter_from_payload,
)
from ..land_animation import (
    LAND_ANIMATION_KIND,
    LandAnimation,
    land_animation_from_payload,
)
from ..land_types import (
    CHOSEN_LAND_TYPES,
    STATIC_SUPERTYPE_REMOVAL_KIND,
    add_derived_land_type,
    clear_derived_land_types,
    resolve_static_land_type_change,
    static_land_type_change_applies,
    static_source_timestamp,
    static_supertype_removal_applies,
)
from ..layer_bridge import (
    DERIVED_LOST_SUPERTYPES,
    QUALIFIED_BUFFS,
    types_before_timestamp,
)
from ..lord_buffs import (
    GRANTED_ACTIVATED_ABILITIES,
    LORD_BUFF_KIND,
    LordBuff,
    lord_buff_from_payload,
)
from ..handlers._common import attached_host, evaluate_count, resolve_amount
from ..search_filters import name_key
from ..subject_filters import subject_matches
from ..models import CardDefinition, Permanent, PlayerState
from ..oracle import _COLOR_WORD_TO_SYMBOL, compile_card_oracle, expand_card_lines
from ..pt import add_pt_counters, clear_base_pt, pt_counter_deltas, set_base_pt
from ..static_bonuses import (
    BASIC_LAND_WORDS,
    conditional_static_holds,
    singular_land_type,
)

# "half the number of <land type>s you control" (Aspect of Wolf). The type is a
# capture rather than a literal, so a Magical Hack rewriting the word moves the
# count with it.
_HALF_LAND_COUNT_RE = re.compile(r"half the number of ([a-z]+) you control")


# Characteristic-defining P/T (CR 604.3 / layer 7a). There is no registry to
# add to: the instruction describes what to count, so a card printed with one
# of these templates needs no code here at all.
def _count_dynamic_pt(
    game, player: PlayerState, permanent: Permanent, payload: dict
) -> int:
    """Tally the objects a ``dynamic_pt_count`` instruction describes.

    One counter for every characteristic-defining P/T, because they differ only
    in *what* they count and *whose* battlefield they count it on — both of
    which arrive on the payload (engine/characteristic_defining.py). The four
    functions this replaced each hardcoded one card's answer to those two
    questions.

    Types are read through ``has_type``/``is_creature`` (CR 613 layer 4), so an
    animated land counts as a creature and a land turned into a Swamp counts as
    a Swamp — the printed type line is not the authority on either.
    """
    # "**During your turn**, …are each equal to 2 plus the number of Swamps
    # your opponents control. **During turns other than yours**, …are each 2."
    # (Angry Mob.) A question about the turn rather than about a battlefield, so
    # it is asked before the scope is read: on any other player's turn the
    # sentence names no set at all and the printed constant is the whole answer.
    if payload.get("only_during") == "your_turn":
        active = game.players[game.active_player_index] if game.players else None
        if active is not player:
            return int(payload.get("otherwise_value", 0))
    scope = payload.get("scope", "you")
    if scope == "all":
        battlefields = [p.battlefield for p in game.players]
    elif scope == "opponents":
        # "…the number of artifacts **your opponents** control" (Gaea's
        # Avenger). Whose battlefield is already payload, so this is one more
        # value for it rather than a second counter.
        battlefields = [p.battlefield for p in game.players if p is not player]
    elif scope == "chosen_player":
        # "…the number of creatures **the chosen player** controls" (Lost Order
        # of Jarkeld). The seat this permanent chose as it entered (CR 614.1c),
        # read off the permanent rather than off the game — the record belongs
        # to one object, the way `chosen_number` two branches up does.
        #
        # Through the control seam, not `player.battlefield`: the sentence says
        # "controls", and a creature the chosen player has *stolen* is one they
        # control. The scopes beside this one predate the seam and are ratcheted
        # where they are; a new one has no reason to join them.
        #
        # No record is a permanent still entering — the choice is part of
        # arriving — and an empty board is the honest answer for it: the printed
        # constant alone, which is what the card is worth until the seat exists.
        seat = permanent.metadata.get("chosen_player_index")
        battlefields = (
            [list(game.controlled_by(seat))]
            if isinstance(seat, int) and 0 <= seat < len(game.players)
            else []
        )
    elif (
        scope == "defender_when_attacking"
        and permanent.attacking
        and permanent.defending_player_index is not None
    ):
        battlefields = [game.players[permanent.defending_player_index].battlefield]
    else:
        battlefields = [player.battlefield]

    what = payload.get("count")
    if what == "sacrificed_as_entered":
        # Wood Elemental: the Forests were sacrificed as this creature entered
        # and are cards in a graveyard now (CR 400.7, CR 613.1), so there is
        # nothing on a battlefield left to tally. The number was recorded where
        # it happened; this reads it back.
        return int(permanent.metadata.get("sacrificed_as_entered") or 0)
    if what == "life_paid_as_entered":
        # Nameless Race: the life was paid as the creature entered (CR 614.1c)
        # and nothing on a board records it, so it rides the permanent the same
        # way Wood Elemental's sacrifice count does.
        return int(permanent.metadata.get("life_paid_as_entered") or 0)
    if what == "chosen_number":
        # Shapeshifter: the value is a number a player chose, not a tally of
        # anything, so it answers before the battlefield loop rather than inside
        # it. It is on this payload anyway because what it *defines* is a
        # characteristic-defining P/T (CR 604.3) like every other entry here.
        return int(permanent.metadata.get("chosen_number") or 0)
    excluded = payload.get("exclude_type")
    land_type = payload.get("land_type")
    card_type = payload.get("card_type")
    # "the number of **snow** lands you control" (Drift of the Dead). A
    # supertype (CR 205.4), computed through layer 4 like every other
    # characteristic — so a land Arcum's Weathervane thawed stops counting and
    # one it froze starts, which is the whole point of the Weathervane.
    supertype = payload.get("supertype")
    # "the number of **other** Rats on the battlefield" (Pestilence Rats): the
    # source itself is excluded by identity (CR 109.5), never by name — a
    # second Rat with the same name is a different permanent.
    subtype = payload.get("subtype")
    exclude_self = bool(payload.get("exclude_self"))

    total = 0
    for battlefield in battlefields:
        for perm in battlefield:
            if supertype is not None and not perm.has_supertype(supertype):
                continue
            if exclude_self and perm is permanent:
                continue
            if what == "land":
                # No ``land_type`` on the payload is the unnarrowed printing —
                # "the number of lands you control" — so the question is the
                # card type alone. Asked through ``has_type`` like the subtype
                # branch beside it, so a permanent that *became* a land counts
                # and one that stopped being one does not (CR 613 layer 4).
                total += perm.has_type(str(land_type) if land_type else "land")
            elif what == "creature":
                if perm.is_creature and not (excluded and perm.has_type(str(excluded))):
                    total += 1
            elif what == "same_name":
                # "creatures named ~": an object's *name* is a copiable value
                # (CR 707.2, layer 1), so a Clone copying Plague Rats both is
                # named Plague Rats and counts the others. The printed face
                # answered here for a year and missed every copy.
                total += perm.effective_card.name == permanent.effective_card.name
            elif what == "card_type":
                total += bool(card_type and perm.has_type(str(card_type)))
            elif what == "subtype":
                # Through `has_type` like every other type question here, so a
                # creature *given* the subtype counts (CR 613 layer 4).
                total += bool(subtype and perm.has_type(str(subtype)))
    # "…equal to **1 plus** the number of …" (Gaea's Avenger). A printed
    # constant added to the tally, on the payload because it is part of the
    # sentence rather than part of the counting — a card printed "2 plus" is
    # the same template.
    return total + int(payload.get("plus", 0))


def _add_static_pt(permanent: Permanent, power: int, toughness: int) -> None:
    """Contribute a layer-7c modification to the *derived* buff channel.

    ``derived_buff_power``/``derived_buff_toughness`` are cleared and rebuilt
    from scratch by ``_refresh_dynamic_creatures`` on every recompute, so a
    contribution here needs no record of itself. That is the difference from
    adding to ``power_bonus``, which persists: anything written there has to be
    subtracted again later, and a subtraction that does not exactly match its
    addition compounds on every refresh — and CR 611.3a means the refresh runs
    constantly. Aspect of Wolf shipped exactly that bug; see
    tests/regressions/test_batch17.py.

    The channel is cleared by the same function that rebuilds it. Splitting
    those across two functions is how this class of bug gets back in: whoever
    calls only the rebuilding half then doubles every contribution.
    """
    if power:
        permanent.metadata["derived_buff_power"] = (
            int(permanent.metadata.get("derived_buff_power", 0)) + power
        )
    if toughness:
        permanent.metadata["derived_buff_toughness"] = (
            int(permanent.metadata.get("derived_buff_toughness", 0)) + toughness
        )


def _apply_conditional_bonus(
    permanent: Permanent, metadata_key: str, active: bool, power: int, toughness: int
) -> None:
    """A "gets +N/+N as long as <condition>" static ability
    (conditional_land_bonus, conditional_untapped_bonus, …).

    Derived, not accumulated: when the condition holds the bonus is contributed
    to the recomputed channel, and when it stops holding nothing has to be
    undone — the next recompute simply does not contribute it.
    """
    if active:
        _add_static_pt(permanent, power, toughness)
    else:
        permanent.metadata[metadata_key] = (0, 0)


class PermanentStateMixin:
    def _initialize_permanent_state(
        self,
        permanent: Permanent,
        caster_index: int,
        target_player_index: int | None,
    ) -> None:
        """Perform CR 614.1c's entry state, and mark what it left unanswered.

        A permanent whose entry choice is still owed **has not finished
        entering**: the choice is part of arriving, not something that happens
        to it afterwards (CR 614.1c), so its characteristics are not settled and
        CR 704.5f cannot yet be applied to a characteristic-defining P/T that
        counts nothing yet. Every prompt this raises is therefore stamped with
        the permanent it is about, and the state-based sweep reads that.

        It was invisible until Wood Elemental, only because every earlier entry
        choice defaulted to something survivable: Shapeshifter's middle of the
        range is a 3/4. Wood Elemental's honest default is zero, so the creature
        went to the graveyard between the prompt being raised and the player
        seeing it — with the prompt still queued, about a permanent that no
        longer existed.
        """
        armed_before = len(self.pending_choices)
        self._perform_entry_state(permanent, caster_index, target_player_index)
        for choice in self.pending_choices[armed_before:]:
            choice.data.setdefault("_entering_permanent", permanent)

    def _perform_entry_state(
        self,
        permanent: Permanent,
        caster_index: int,
        target_player_index: int | None,
    ) -> None:
        if permanent.card.primary_type in ("creature", "land", "artifact"):
            # Lands are stamped too: if a land later becomes a creature (Kormus Bell,
            # Living Lands) it must respect summoning sickness based on when it came
            # under control (CR 302.6). The marker is ignored for non-creature lands.
            permanent.metadata["summoning_sickness_turn"] = self.turn
        # …and, separately, the turn it *entered the battlefield*. The stamp
        # above is CR 302.6's "since their most recent turn began", which a
        # control change re-writes (`_sync_control`) and a passing turn carries
        # forward (`_advance_summoning_sickness`) — so it cannot answer "did
        # this permanent enter this turn?", the question Chaos Lord's "unless it
        # entered this turn" asks. Written once here and never again; anything
        # that leaves and returns is a new object with a new stamp (CR 400.7).
        permanent.metadata[ENTERED_BATTLEFIELD_TURN] = self.turn
        program = compile_card_oracle(permanent.card)
        text = program.normalized_text

        # CR 306.5b: a planeswalker enters with loyalty counters equal to its
        # printed loyalty number — an intrinsic replacement effect, so it is
        # part of entering, not a triggered ability. Unconditional for the card
        # type: the ability is not printed text, so there is no phrase in
        # engine/enter_effects.py to probe for.
        if permanent.card.primary_type == "planeswalker":
            printed = permanent.card.loyalty
            if printed is not None and printed.strip().lstrip("-").isdigit():
                permanent.metadata["loyalty_counters"] = int(printed)

        # enters tapped (static creature/permanent lines or normalized text).
        # The phrases probed for here live in engine/enter_effects.py, which
        # engine/grammar/registries.py also reads to tell the parser these lines
        # are already implemented — one string, two readers, so they cannot
        # drift apart.
        if any(line for line in program.static_lines if ENTERS_TAPPED in line) or (
            ENTERS_TAPPED in text and "unless" not in text
        ):
            permanent.tapped = True

        # CR 614.1c, the *other* sentence: a permanent already on the
        # battlefield saying how somebody else's permanents enter ("Artifacts,
        # creatures, and lands your opponents control enter tapped", Kismet).
        # Asked of the board rather than of the card being read, which is the
        # whole difference between the two — and asked here, at the one seam an
        # entry passes through, so a permanent arriving by any road (cast,
        # token, reanimation) meets it.
        if self._enters_tapped_by_a_static(permanent):
            permanent.tapped = True

        # "As this creature enters, it becomes your choice of <body>, <body>,
        # or <body>." (Primal Clay.) A body is applied immediately so headless
        # and AI play never blocks, and an interactive controller is offered the
        # choice; confirm_enter_body_choice replaces it.
        #
        # The default is the FIRST body printed, not the biggest: the card lists
        # them in a fixed order and picking "best" would be this code deciding
        # strategy on the player's behalf, differently from how the prompt they
        # are about to answer is ordered.
        bodies = choosable_bodies(text)
        if bodies:
            # Options first: _apply_chosen_body clears the keywords of the
            # *other* bodies before granting the chosen one's, and the card's
            # text mentions every body's keyword — so the compiler reads
            # "with flying" off Primal Clay and grants it. Applying a body
            # before the options are recorded leaves that stray grant in place.
            permanent.metadata["body_options"] = list(bodies)
            self._apply_chosen_body(permanent, bodies[0])
            if len(bodies) > 1:
                self.arm_pending_choice(
                    "body_choice", caster_index,
                    card_name=permanent.card.name, permanent=permanent,
                    options=list(bodies),
                )

        # "As this artifact enters, choose an opponent." (Black Vise) / "As
        # this creature enters, choose an opponent." (Lost Order of Jarkeld.) /
        # "As this enchantment enters, choose a color and an opponent." (Jihad)
        # Deterministic defaults are stamped immediately (the cast target, else
        # the first living opponent; the color the opponent controls most among
        # nontoken permanents) so headless/AI play never blocks. An interactive
        # caster with a genuine choice — several opponents, or a color to pick —
        # gets a prompt whose confirm_enter_choice overwrites the defaults
        # before anything consults them.
        needs_color = CHOOSE_COLOR_AND_OPPONENT_ON_ENTER in text
        if needs_color or chooses_opponent_on_enter(text):
            opponents = [
                i for i, p in enumerate(self.players) if i != caster_index and not p.lost
            ]
            if target_player_index in opponents:
                chosen = target_player_index
            elif opponents:
                chosen = opponents[0]
            else:
                chosen = 1 - caster_index
            permanent.metadata["chosen_player_index"] = chosen
            default_color = None
            if needs_color:
                default_color = self._dominant_nontoken_color(self.players[chosen]) if 0 <= chosen < len(self.players) else "W"
                permanent.metadata["chosen_color"] = default_color
                # Jihad's anthem is conditioned on the stored choices, and the
                # entry recalculation ran before they were stamped — recompute.
                self._recalculate_lord_buffs()
            if needs_color or len(opponents) > 1:
                self.arm_pending_choice(
                    "enter_choice", caster_index,
                    card_name=permanent.card.name, permanent=permanent,
                    needs_color=needs_color, opponents=opponents,
                    default_seat=chosen, default_color=default_color,
                )

        # "As this enchantment enters, choose a color." (Psychic Allergy.) The
        # colour half with no player beside it, so no seat is recorded at all —
        # asked *after* the pair above and only when that phrase is absent,
        # because this one is its prefix and would otherwise claim Jihad's line
        # and drop the opponent it names.
        #
        # The default is the colour this permanent's controller's **opponents**
        # hold most of among nontoken permanents. That is the stated policy for
        # a choice nothing else constrains (idiom 8), and it is the same
        # reasoning as Jihad's default one branch up: a colour nobody controls
        # makes every "choose a color" effect inert, which is a legal choice no
        # player would make and an AI seat would be stuck with.
        if (
            chooses_color_on_enter(text)
            and CHOOSE_COLOR_AND_OPPONENT_ON_ENTER not in text
        ):
            opponents = [
                i for i, p in enumerate(self.players)
                if i != caster_index and not p.lost
            ]
            counts: dict[str, int] = {}
            for seat in opponents:
                for perm in self.controlled_by(seat):
                    if perm.metadata.get("is_token"):
                        continue
                    for color in self._effective_colors(perm):
                        counts[color] = counts.get(color, 0) + 1
            default_color = max(sorted(counts), key=lambda c: counts[c]) if counts else "W"
            permanent.metadata["chosen_color"] = default_color
            self.arm_pending_choice(
                "enter_choice", caster_index,
                card_name=permanent.card.name, permanent=permanent,
                needs_color=True, opponents=[], default_seat=None,
                default_color=default_color,
            )

        # "As this enchantment enters, choose two basic land types."
        # (Illusionary Terrain.) An **ordered pair**: the static beside it names
        # "the first chosen type" and "the second chosen type", so the record is
        # a tuple and the order is the whole of what it carries.
        #
        # The default is the hoser's choice a player would make — the basic type
        # this permanent's controller's opponents hold most of becomes the one
        # they hold least — because a pair naming a type nobody controls makes
        # the enchantment inert, which is legal and is not a choice any player
        # would make (idiom 8). Stamped before the prompt so an AI or headless
        # seat never blocks, exactly as Black Vise's opponent is.
        if chooses_two_land_types_on_enter(text):
            first, second = self._default_terrain_land_types(caster_index)
            permanent.metadata[CHOSEN_LAND_TYPES] = (first, second)
            # The static reads the record, and the record did not exist when
            # the entry recalculation ran — recompute, the way Jihad's anthem
            # does one branch up.
            self._refresh_dynamic_creatures()
            self.arm_pending_choice(
                "enter_choice", caster_index,
                card_name=permanent.card.name, permanent=permanent,
                needs_color=False, opponents=[], default_seat=None,
                default_color=None, needs_land_types=True,
                default_land_types=[first, second],
            )

        # "As this enchantment enters, choose **a creature type**."
        # (An-Zerrin Ruins.) The third quality this one sentence can name, and
        # the third shape of this one prompt that carries no seat — so it is
        # armed exactly as the colour is, with the record stamped first so an
        # AI or headless controller never blocks.
        #
        # The default is the creature type this permanent's controller's
        # **opponents** have most of, which is the stated policy for a choice
        # nothing else constrains (idiom 8) and the same reasoning as the
        # colour one above: a type nobody controls makes the enchantment inert,
        # which is a legal choice no player would make and an AI seat would be
        # stuck with.
        if chooses_creature_type_on_enter(text):
            permanent.metadata["chosen_creature_type"] = (
                self._default_chosen_creature_type(caster_index)
            )
            self.arm_pending_choice(
                "enter_choice", caster_index,
                card_name=permanent.card.name, permanent=permanent,
                needs_color=False, opponents=[], default_seat=None,
                default_color=None, needs_creature_type=True,
                default_creature_type=permanent.metadata["chosen_creature_type"],
            )

        # "As this enchantment enters, choose a card name." (Runed Halo.) The
        # choice is made *as* the permanent enters (CR 614.1c), so it is stamped
        # here rather than by a trigger — by the time a trigger could resolve,
        # the protection would already have failed to apply once.
        #
        # The default names a card the chooser can actually see: the top card of
        # an opponent's graveyard, else one of their permanents. Naming nothing
        # would make the protection apply to nothing at all, which is a legal
        # choice no player would make and an AI seat would be stuck with.
        if CHOOSE_CARD_NAME_ON_ENTER in text:
            opponents = [
                i for i, p in enumerate(self.players)
                if i != caster_index and not p.lost
            ]
            seen = [
                card.name
                for seat in opponents
                for card in reversed(self.players[seat].graveyard)
            ] + [
                perm.card.name
                for seat in opponents
                for perm in self.controlled_by(seat)
            ]
            permanent.metadata["chosen_card_name"] = seen[0] if seen else ""
            self.arm_pending_choice(
                "enter_choice", caster_index,
                card_name=permanent.card.name, permanent=permanent,
                needs_card_name=True, choices=sorted(set(seen)),
                default_card_name=permanent.metadata["chosen_card_name"],
            )

        # "As this creature enters, choose a number between 0 and 7."
        # (Shapeshifter.) CR 614.1c puts the choice at entry, not on a trigger:
        # the number is what the card's P/T is *defined* by, so a trigger would
        # leave it on the battlefield as a 0/0 long enough to die to the
        # state-based check.
        #
        # A default is stamped first and the prompt overwrites it, exactly as
        # the opponent-and-colour choice above works. The default is the middle
        # of the printed range because that is the only value the card's own
        # arithmetic makes defensible without knowing the board: the extremes
        # are a body that cannot fight (0 power) or one that dies to any ping
        # (1 toughness at the top of Shapeshifter's range), and a seat that
        # never answers should not be handed either.
        entry_lines = expand_card_lines(permanent.effective_card)
        for raw_line in entry_lines:
            bounds = choose_number_on_enter(raw_line)
            if bounds is None:
                continue
            low, high = bounds
            permanent.metadata["chosen_number"] = (low + high) // 2
            self.arm_pending_choice(
                "number_choice", caster_index,
                card_name=permanent.card.name, permanent=permanent,
                minimum=low, maximum=high,
                default_number=permanent.metadata["chosen_number"],
            )
            break

        # "As this creature enters, **pay any amount of life**." (Nameless
        # Race.) CR 614.1c puts it at entry for Shapeshifter's reason: the life
        # paid is what the creature's characteristic-defining P/T is *defined*
        # by, so a trigger would leave it on the battlefield as a 0/0 long
        # enough to die to the state-based check.
        #
        # The cap is the printed sum, counted now — the amounts the two halves
        # name are read through the same matchers every other filter goes
        # through, one for permanents and one for cards, because a card in a
        # zone has no computed characteristics at all (CR 613.1).
        #
        # Zero is stamped first and the prompt overwrites it, and zero is also
        # the stated policy for a seat that never answers: an optional life
        # payment is a cost nobody asked that seat to pay. Nameless Race then
        # enters as a 0/0 and dies, which is what the card does when its
        # controller declines.
        for raw_line in entry_lines:
            capped = pay_any_life_on_enter(raw_line, permanent.effective_card.name)
            if capped is None:
                continue
            permanent.metadata["life_paid_as_entered"] = 0
            maximum = self._nameless_race_cap(caster_index, capped)
            if maximum > 0:
                self.arm_pending_choice(
                    "number_choice", caster_index,
                    card_name=permanent.card.name, permanent=permanent,
                    minimum=0, maximum=maximum, default_number=0,
                    pay_life_onto=True,
                )
            break

        # "As this creature enters, sacrifice any number of untapped Forests."
        # (Wood Elemental.) CR 614.1c puts it at entry for the same reason
        # Shapeshifter's number is there: what the controller gives up is what
        # the creature's characteristic-defining P/T is *defined* by, so a
        # trigger would leave it on the battlefield as a 0/0 long enough to die
        # to the state-based check.
        #
        # The record is stamped at zero first and the answer overwrites it —
        # every other entry choice here works that way — and zero is also the
        # stated policy a non-interactive seat takes: an optional sacrifice is a
        # cost nobody asked that seat to pay. Wood Elemental then enters as a
        # 0/0 and dies, which is what the card does when its controller declines.
        for raw_line in entry_lines:
            offered = sacrifice_any_number_on_enter(
                raw_line, permanent.effective_card.name
            )
            if offered is None:
                continue
            permanent.metadata["sacrificed_as_entered"] = 0
            candidates = self._sacrifice_candidate_indices(
                self.players[caster_index], offered, None
            )
            # "Any number" of nothing is zero, already recorded — and arming a
            # prompt over an empty board would ask a question with one answer.
            if candidates:
                self.arm_forced_sacrifice(
                    caster_index, len(candidates), filter=offered,
                    reason=f"{permanent.card.name} enters",
                    up_to=True, count_onto=permanent,
                )
            break

        # "As this creature enters, exile X creature cards from your graveyard.
        # … For each creature card exiled this way, this creature enters with a
        # +2/+0, +1/+1, or +0/+2 counter on it." (Frankenstein's Monster.)
        #
        # CR 614.1c again, and for Wood Elemental's reason: what the controller
        # gives up is what the creature's *size* is defined by, so a trigger
        # would leave a 0/1 on the battlefield long enough to be blocked, killed
        # or counted at the wrong size.
        #
        # The other half of the same printed paragraph - "if you can't, put this
        # creature into its owner's graveyard instead of onto the battlefield" -
        # is the CR 614 interceptor in engine/replacements.py, asked before this
        # runs. So by the time this arms, the graveyard is known to hold enough:
        # the exile here is a cost that *can* be paid, and the only open
        # question is which cards pay it and which counter each one buys.
        required = entry_exile_requirement(
            permanent.effective_card, permanent.metadata.get("cast_x_value")
        )
        if required is not None and required["count"] > 0:
            self.arm_pending_choice(
                "entry_exile", caster_index,
                card_name=permanent.card.name, permanent=permanent,
                # Stamped here as well as by `_initialize_permanent_state`,
                # which does it only once `_perform_entry_state` returns: a
                # non-interactive seat's default is taken *at arm*, and it
                # needs the permanent the counters land on.
                _entering_permanent=permanent,
                count=required["count"],
                filter=dict(required["filter"]),
                counters=list(required["counters"]),
            )

        # "If this land would enter, sacrifice an untapped Mountain instead. If
        # you do, put this land onto the battlefield." (Balduvian Trading Post
        # and its four siblings.) CR 614.1a's entry toll, charged here for
        # Frankenstein's Monster's reason one branch up: the other half of the
        # same paragraph - "if you don't, put it into its owner's graveyard" -
        # is the interceptor in engine/replacements.py, and it declined to apply,
        # which is exactly the statement that the battlefield holds something
        # the toll accepts. So this is a cost that *can* be paid and the only
        # open question is which permanent pays it.
        #
        # Mandatory, not offered: the sentence says "sacrifice ... instead", so
        # ``up_to`` stays False and a non-interactive seat pays it inline
        # through the same deterministic pick every other forced sacrifice uses.
        #
        # ``exclude`` is CR 614.13a - the permanent that is entering can never
        # be chosen to pay for its own entry. It is on the battlefield by now,
        # so unlike the predicate's copy of the same exclusion this one has
        # something to exclude.
        toll = entry_sacrifice_requirement(permanent.effective_card)
        if toll is not None:
            described = dict(toll["filter"])
            owed = toll["count"]
            if owed == "all":
                # "instead sacrifice **each other permanent named Sheltered
                # Valley you control**" — a set rather than a number, so the
                # count is whatever the board holds and the player is offered no
                # choice at all. Zero is a legal answer and needs no prompt,
                # which is why this shape prints no "if you don't": an empty set
                # is something everybody can give up.
                owed = len(self._sacrifice_candidate_indices(
                    self.players[caster_index], described, permanent
                ))
            if owed:
                self.arm_forced_sacrifice(
                    caster_index, int(owed), filter=described, exclude=permanent,
                    reason=f"{permanent.card.name} enters",
                )

        # enters with fixed counters (Clockwork Beast). Track the counter count so
        # the end-of-combat trigger and the upkeep activated ability can adjust it.
        # "This Equipment enters with a soul counter on it." (Malefic Scythe) /
        # "Rasputin enters with seven dream counters on it." (Rasputin
        # Dreamweaver.) A CR 122.1 counter, so the word *and the number* are
        # data and the store is the one engine/named_counters.py owns — what the
        # counter means is whatever the card's other lines say, which for
        # Malefic Scythe is the P/T grant layer 7c derives from the same store
        # and for Rasputin is what two of his activated abilities spend.
        #
        # The card's name goes in because a card may write the subject as that
        # name, and the reader collapses it through the same seam the support
        # gate does.
        for raw_line in entry_lines:
            placed = enters_with_named_counter(
                raw_line, permanent.effective_card.name
            )
            if placed is not None:
                count, counter = placed
                add_named_counters(permanent, counter, count)

        # "This enchantment enters with **X ice** counters on it." (Iceberg.)
        # The named store above with the announced X (CR 601.2b) for its count,
        # which is the same separation the two P/T loops below make and for the
        # same reason: a printed number is read off the line, and X is read off
        # the cast. Iceberg spends those counters for mana, so entering with an
        # empty store made a card that compiled supported and could never pay
        # its own second ability.
        for raw_line in entry_lines:
            counter = enters_with_x_named_counters(
                raw_line, permanent.effective_card.name
            )
            if counter is None:
                continue
            x_value = permanent.metadata.get("cast_x_value")
            if not isinstance(x_value, int) or x_value <= 0:
                continue
            add_named_counters(permanent, counter, x_value)

        # "…enters with <N> <kind> counters on it." The count and the kind are
        # read off the line (engine/enter_effects.enters_with_pt_counters), so
        # Clockwork Beast's seven, Clockwork Avian's four and Triskelion's
        # three are one rule. They used to be two literal sentences, which is
        # why the first worked and the others did not.
        for raw_line in entry_lines:
            placement = enters_with_pt_counters(
                raw_line, permanent.effective_card.name
            )
            if placement is None:
                continue
            count, kind = placement
            if kind == "+1/+1":
                # Through the seam: entering with counters is a counter
                # placement like any other, so a replacement that modifies it
                # applies (CR 614.1c).
                self.place_plus1_counters(permanent, count)
            elif kind == "+1/+0":
                permanent.power_bonus += count
                permanent.metadata["plus_1_0_counters"] = count
            else:
                permanent.toughness_bonus += count
                permanent.metadata["plus_0_1_counters"] = count

        # "…enters with **X** <kind> counters on it" (Rock Hydra's +1/+1,
        # Balduvian Hydra's +1/+0). The count is the announced X rather than a
        # printed number, which is what separates it from the loop above; the
        # counter kind is read off the line there and here alike, so the two
        # Hydras are one rule. It was a literal sentence naming +1/+1, and
        # Balduvian Hydra printing the identical template one kind over was
        # unsupported for it.
        for raw_line in entry_lines:
            kind = enters_with_x_pt_counters(
                raw_line, permanent.effective_card.name
            )
            if kind is None:
                continue
            x_value = permanent.metadata.get("cast_x_value")
            if not isinstance(x_value, int) or x_value <= 0:
                continue
            if kind == "+1/+1":
                # Through the seam: entering with counters is a counter
                # placement like any other, so a Conclave Mentor raises it
                # (CR 614.1c's replacement applies as the permanent enters).
                self.place_plus1_counters(permanent, x_value)
            elif kind == "+1/+0":
                permanent.power_bonus += x_value
                permanent.metadata["plus_1_0_counters"] = x_value
            else:
                permanent.toughness_bonus += x_value
                permanent.metadata["plus_0_1_counters"] = x_value

        # copy-as-enter creature
        if any(COPY_CREATURE_ON_ENTER == line for line in program.static_lines) or COPY_CREATURE_ON_ENTER in text:
            source = self._resolve_copy_target(permanent, "creature")
            if source is None:
                source = next(
                    (
                        perm
                        for perm in self.all_permanents()
                        if perm is not permanent and perm.card.primary_type == "creature"
                    ),
                    None,
                )
            if source is not None:
                self._apply_copy(permanent, source)

        # copy-as-enter enchantment
        if COPY_ARTIFACT_ON_ENTER in text:
            # Honor the artifact the player chose when casting (Copy Artifact);
            # fall back to the first artifact for AI/untargeted casts.
            source = self._resolve_copy_target(permanent, "artifact")
            if source is None:
                source = next(
                    (
                        perm
                        for perm in self.all_permanents()
                        if perm is not permanent and perm.card.primary_type == "artifact"
                    ),
                    None,
                )
            if source is not None:
                # CR 707.2 with CR 707.9b's exception ("it's an enchantment in
                # addition to its other types"), recorded as a layer-1
                # contribution. ``permanent.card`` stays Copy Artifact, so the
                # copy evaporates when the permanent changes zones; what it
                # copies is the artifact's *copiable* values, which is why this
                # no longer reads ``source.effective_card`` — a text change on
                # the artifact is not copied (CR 707.2's last sentence).
                self._apply_copy(permanent, source)

        if any(instr.kind == "spell_pattern" and instr.value == NO_MAXIMUM_HAND_SIZE for instr in program.instructions) or NO_MAXIMUM_HAND_SIZE in text:
            self.players[caster_index].has_no_max_hand_size = True

        if SPEND_WHITE_AS_RED in text:
            self.players[caster_index].can_spend_white_as_red = True

        if SPEND_ANY_COLOR in text:
            self.players[caster_index].spends_mana_as_any_color = True

        if LOSE_LIFE_EQUAL_TO_TOTAL_ON_ENTER in text:
            controller = self.players[caster_index]
            life_loss = controller.life
            controller.life -= life_loss
            self.log.append(f"{permanent.card.name}: {controller.name} lost {life_loss} life on entry")

    def _apply_copy(self, permanent: Permanent, source: Permanent) -> None:
        """Make *permanent* a copy of *source* — CR 613 layer 1a, recorded by
        ``engine/copies.py``.

        One entry point for all three copiers, because CR 707.2 is one rule: the
        copy takes the copied object's *copiable* values, and the exceptions
        each card prints (Vesuvan Doppelganger's colour, Copy Artifact's added
        type, Vesuvan's granted re-copy ability) are read off the copier's own
        text by :func:`engine.copies.copy_exceptions`. Also used when Vesuvan's
        upkeep ability re-copies a different creature (CR 707.4), which is the
        same contribution re-recorded with a newer timestamp.

        What is deliberately *not* here: any stamped result. P/T, colours,
        keywords and types are all read back off the recorded contribution, so
        a non-copy effect on the source (a +1/+1 counter, an Aura, an animation,
        a text change, a "base power 0") cannot leak into the copy.
        """
        copies.become_copy(
            permanent,
            source,
            **copies.copy_exceptions(compile_card_oracle(permanent.card).normalized_text),
        )
        self._recalculate_lord_buffs()

    def create_token_copy(self, controller_index: int, source: Permanent) -> Permanent:
        """A token that is a copy of *source*, under *controller_index*.

        Two rules, kept apart. CR 111.1 says what a token is — an object on the
        battlefield with no card, stamped ``is_token`` so it ceases to exist
        rather than going to a graveyard (CR 111.7). CR 707.2 says what a copy
        is, and that is recorded as a layer 1a contribution here rather than
        stamped onto the token: everything a *non-copy* effect has done to the
        original — a +1/+1 counter, an Aura, an animation, a text change — is
        excluded by construction, because what is stored is the copiable values
        and not the current ones.

        Beside ``_apply_copy`` rather than in the handler, because this module
        is where layer 1 is applied and the guard in
        ``tests/engine/test_copy_reads.py`` says so. It is *not* ``_apply_copy``
        itself: that reads the copy exceptions off the copying permanent's own
        text (Vesuvan Doppelganger's colour, Copy Artifact's added type), and
        here the copier is a spell — the token's own text is the **copied**
        card's, so reading exceptions from it would apply the copied creature's
        printed quirks as if Sublime Epiphany had printed them.
        """
        # The base card carries **nothing but a name**, and the name only so a
        # log line reads like the board. Every characteristic comes from the
        # copy contribution below: seeding the base from the source's copiable
        # values as well would be a second statement of what the token is, free
        # to disagree with layer 1 the moment anything reads `perm.card`
        # directly — which is the whole reason layer 1 has one reader.
        token = Permanent(
            card=make_token_card(source.effective_card.name, None, None, "Token"),
            metadata={"is_token": True},
        )
        self._put_permanent_onto_battlefield(controller_index, token, None)
        # Recorded after entry: the contribution is what layer 1 reads, and the
        # entry is what gives the token its permanent id (CR 400.7).
        copies.become_copy(token, source)
        self._recalculate_lord_buffs()
        return token

    def _resolve_copy_target(self, permanent: Permanent, primary_type: str) -> Permanent | None:
        """Return the player-chosen permanent for a "copy as it enters" effect.

        The chosen target is recorded as ``copy_target = (player_index, perm_index)``
        when the spell is cast. Returns None if no legal choice was recorded so the
        caller can fall back to an arbitrary legal permanent.
        """
        copy_target = permanent.metadata.pop("copy_target", None)
        if copy_target is None:
            return None
        player_index, perm_index = copy_target
        if not isinstance(player_index, int) or not isinstance(perm_index, int):
            return None
        if not (0 <= player_index < len(self.players)):
            return None
        battlefield = self.players[player_index].battlefield
        if not (0 <= perm_index < len(battlefield)):
            return None
        candidate = battlefield[perm_index]
        if candidate is permanent or candidate.card.primary_type != primary_type:
            return None
        return candidate

    def _refresh_static_land_types(self, all_permanents: list[Permanent]) -> None:
        """Apply static basic-land-type changes (e.g. Conversion: "All Mountains
        are Plains."). Recomputed every call so a land reverts the moment the
        source enchantment leaves the battlefield (CR 611.3a/b).

        The *derived* land-type channel, cleared and rebuilt here together — a
        static's contribution is not recorded, because CR 611.3a means this runs
        constantly and a recorded one would accumulate an entry per pass. The
        recorded channel (an Aura's, a mire counter's) is untouched, so a
        Conversion leaving can no longer take a Phantasmal Terrain's type with
        it; the two are separate contributions and layer 4 sorts them by
        timestamp.

        **The statics chain in timestamp order (CR 613.7)**, each judged
        against the state the earlier ones left: with Blood Moon out first, a
        nonbasic land is a Mountain by the time Conversion asks "is this a
        Mountain?", so Conversion reaches it too. Each candidate is therefore
        evaluated against ``layer_bridge.types_before_timestamp`` — the seed
        plus every layer-4 effect stamped earlier, recorded *and* derived so
        far — rather than against a finished layer read (the circularity: this
        refresh computes layer 4's inputs) or against the layer-3 type line
        (which no earlier layer-4 effect can ever reach). And a static that
        applies does not stop the walk: 613.7 chains the effects, it does not
        pick one, so "All Mountains are Plains" beside "All Plains are Islands"
        turns a Mountain into an Island.
        """
        changes: list[tuple[dict, Permanent]] = []
        # "All lands are no longer snow." (Melting.) CR 205.4a's half of the
        # type line, collected in the same pass because it is the same
        # question — which board-wide statics are out — asked about a different
        # word. Its contributions go on their own channel (`layer_bridge
        # .DERIVED_LOST_SUPERTYPES`), because a supertype removal is not a
        # land-type replacement and folding the two would give every Conversion
        # a supertype field it must not set.
        removals: list[tuple[dict, Permanent]] = []
        for perm in all_permanents:
            for instr in compile_card_oracle(perm.effective_card).instructions:
                if instr.kind == "static_land_type_change":
                    changes.append((instr.payload, perm))
                elif instr.kind == STATIC_SUPERTYPE_REMOVAL_KIND:
                    removals.append((instr.payload, perm))
        # Both derived channels are cleared before anything is judged, so no
        # candidate can read a previous pass's contribution as this pass's
        # board (CR 611.3b: a static's effect lasts exactly as long as the
        # rebuild keeps putting it back).
        for perm in all_permanents:
            perm.metadata.pop(DERIVED_LOST_SUPERTYPES, None)
            clear_derived_land_types(perm)
        if not changes and not removals:
            return
        # One ordered walk over every board-wide layer-4 static, type changes
        # and supertype removals together, because CR 613.7 orders the layer
        # and not each kind separately.
        events: list[tuple[int, str, dict, Permanent]] = []
        for payload, source in changes:
            # "Basic lands of **the first chosen type** are **the second
            # chosen type**." (Illusionary Terrain.) The sentence names no
            # land type at all: both come from the ordered pair its
            # controller chose as it entered. Resolved once, against the
            # source, and then read like any other payload — a source that
            # has not chosen yet resolves to None and contributes nothing,
            # which is the honest answer rather than a static over every
            # land or none.
            resolved = resolve_static_land_type_change(payload, source)
            if resolved is None:
                continue
            events.append(
                (static_source_timestamp(source), "change", resolved, source)
            )
        for payload, source in removals:
            events.append(
                (static_source_timestamp(source), "removal", payload, source)
            )
        events.sort(key=lambda event: event[0])
        for perm in all_permanents:
            is_land = perm.card.primary_type == "land"
            lost: list[str] = []
            # Which lands a source reaches is `land_types.py`'s question, not
            # this loop's: Conversion names a land type and Blood Moon names a
            # missing supertype, and a second reading of either here would be
            # the gate/dispatch split this engine keeps finding. What this loop
            # owns is the order — and the intermediate state each candidate is
            # judged against, which is everything stamped before it, including
            # the contributions the walk itself has written so far.
            for stamp, kind, payload, source in events:
                if kind == "removal":
                    word = str(payload.get("supertype") or "")
                    if not word or word in lost:
                        continue
                    if static_supertype_removal_applies(
                        payload, types_before_timestamp(perm, stamp)
                    ):
                        lost.append(word)
                        perm.metadata[DERIVED_LOST_SUPERTYPES] = sorted(lost)
                elif is_land and static_land_type_change_applies(
                    payload, types_before_timestamp(perm, stamp)
                ):
                    add_derived_land_type(
                        perm,
                        str(payload.get("to_type", "")),
                        timestamp=stamp,
                        label=source.card.name,
                    )

    def _refresh_aspect_of_wolf(self) -> None:
        """Aspect of Wolf: enchanted creature gets +X/+Y where X/Y are half the
        aura controller's count of a basic land type (down/up). Recomputed
        continuously so it tracks lands entering and leaving (CR 611.3a).

        **The land type is read out of the Aura's own effective text**, not
        fixed at "forest". Magical Hack rewrites that word (CR 612.1), and
        matching a printed sentence while counting a hardcoded type is the same
        mistake made twice: after the change the sentence stopped matching at
        all, so the bonus quietly became +0/+0 rather than following the word.

        Contributed to the derived buff channel, so several Aspects on one
        creature simply add up and nothing needs unwinding.
        """
        for controller in self.players:
            controlled = list(self.controlled_by(controller))
            for aura in controlled:
                match = _HALF_LAND_COUNT_RE.search(
                    aura.effective_card.oracle_text.lower()
                )
                if match is None:
                    continue
                land_type = singular_land_type(match.group(1))
                if land_type not in BASIC_LAND_WORDS:
                    continue
                creature = aura.metadata.get("attached_to")
                if creature is None or creature.card.primary_type != "creature":
                    continue
                lands = sum(
                    1
                    for perm in controlled
                    if perm.card.primary_type == "land" and perm.has_type(land_type)
                )
                _add_static_pt(creature, lands // 2, (lands + 1) // 2)

    def _refresh_board_counted_penalties(self) -> None:
        """Snowblind: "Enchanted creature gets -X/-Y", where X counts a class of
        permanent on **whichever** board the combat points at, and Y is clamped
        so the creature is never killed by it.

        Derived rather than remembered, like every other Aura contribution: X
        changes when a land enters and when the creature attacks, and neither
        of those is a moment anything could hook. CR 611.3a says a continuous
        effect applies whenever its criteria are met, and "the number of snow
        lands defending player controls" is a criterion re-read on every pass.

        **The toughness the clamp reads is the toughness without this effect.**
        The derived channel this contributes to was cleared at the top of the
        refresh, so ``effective_toughness`` here is base P/T plus every other
        layer — which is the reading the printed clamp means: "toughness minus
        1" is what makes Snowblind unable to kill, and reading a toughness this
        effect had already reduced would make the clamp chase itself.
        """
        from ..auras import aura_board_counted_penalty, auras_attached_to
        from ..subject_filters import subject_matches

        for seat, host in self.permanents_with_controller():
            for aura in auras_attached_to(host):
                payload = aura_board_counted_penalty(
                    aura.effective_card.oracle_text
                )
                if payload is None:
                    continue
                # CR 506.2: the board is the *defending player's* while the
                # creature is attacking, and its own controller's otherwise.
                # The defending seat is stamped on the attacker at declaration,
                # so this is a read rather than a search — and an attacker
                # whose defender is gone falls back to its controller, which is
                # the sentence's own "otherwise".
                counted_seat = seat
                if host.attacking and isinstance(host.defending_player_index, int):
                    counted_seat = host.defending_player_index
                if not (0 <= counted_seat < len(self.players)):
                    continue
                described = payload["filter"]
                amount = sum(
                    1
                    for perm in self.controlled_by(counted_seat)
                    if subject_matches(self, perm, described)
                )
                if amount <= 0:
                    continue
                clamp = max(0, host.effective_toughness - 1)
                _add_static_pt(host, -amount, -min(amount, clamp))

    def _refresh_linked_tapped_pumps(self, all_permanents) -> None:
        """"…gets +2/-2 for as long as this artifact remains tapped."
        (Ashnod's Battle Gear, Tawnos's Weaponry.)

        The boost is recorded on the *source* by the handler and contributed
        here, into the same derived channel every other conditional layer-7c
        effect uses — so it is rebuilt from the board on every recompute and
        ends the instant the source stops being tapped. Nothing schedules its
        removal, which is the point: an effect that ends on a *condition*
        rather than at a step boundary has no moment anyone could hook, and a
        remembered delta would have to be unwound at one.

        Three ways the contribution simply stops, none of them special-cased:
        the source untaps, the source leaves the battlefield (its record leaves
        with it), or the pumped permanent leaves (its id no longer resolves).
        """
        from ..handlers.pump import PUMP_WHILE_TAPPED_KEY

        for source in all_permanents:
            record = source.metadata.get(PUMP_WHILE_TAPPED_KEY)
            if not record or not source.tapped:
                continue
            target = self.permanent_by_id(record.get("target_id"))
            if target is None:
                continue
            _add_static_pt(target, int(record.get("power", 0)), int(record.get("toughness", 0)))

    def _refresh_dynamic_creatures(self) -> None:
        all_permanents = list(self.all_permanents())
        # Clear the derived layer-7c channel this method rebuilds. Everything
        # contributed below is a *conditional* continuous effect, so it is
        # recomputed from the current board rather than adjusted incrementally.
        for perm in all_permanents:
            perm.metadata.pop("derived_buff_power", None)
            perm.metadata.pop("derived_buff_toughness", None)
        # Every land animator currently on the battlefield, read off the
        # compiled program rather than matched by name. Two `card.name ==`
        # comparisons stood here; the payload carries the land type, the P/T and
        # the colour, so a third animator needs no code (engine/land_animation.py).
        animations = [
            land_animation_from_payload(instr.payload)
            for perm in all_permanents
            for instr in compile_card_oracle(perm.effective_card).instructions
            if instr.kind == LAND_ANIMATION_KIND
        ]
        self._refresh_linked_tapped_pumps(all_permanents)
        self._refresh_global_statics(all_permanents)
        self._refresh_static_land_types(all_permanents)
        # Layer 4 before layer 7: a characteristic-defining P/T that counts
        # creatures must see the lands this pass animates, not last pass's.
        self._refresh_land_animation(all_permanents, animations)
        self._refresh_aspect_of_wolf()
        # After the other 7c contributions, because its clamp reads the
        # toughness the creature has *without* it — see the method.
        self._refresh_board_counted_penalties()

        # "Attacking creatures you control get +X/+Y" (Orcish Oriflamme) used to
        # be counted here, into a channel of its own, because the lord-buff
        # consumer could not express a state qualifier. It is an ordinary lord
        # buff now — engine/lord_buffs.py derives the qualifier and
        # _recalculate_lord_buffs contributes it — so there is nothing here to
        # keep in step with it.
        for seat, permanent in self.permanents_with_controller():
            player = self.players[seat]
            prog = compile_card_oracle(permanent.effective_card)
            instr_kinds = {instr.kind for instr in prog.instructions}

            # Characteristic-defining P/T (CR 604.3, layer 7a). The
            # instruction says what to count; there is one counter, and a
            # new CDA card adds no code here at all.
            dynamic_pt = next(
                (i for i in prog.instructions if i.kind == "dynamic_pt_count"), None
            )
            if dynamic_pt is not None:
                spec = dynamic_pt.payload.get("count_spec")
                # A CDA counting *cards in a zone* asks the shared evaluator, not
                # the battlefield tally: a card in a graveyard has no computed
                # characteristics (CR 613.1), so it is a different question of a
                # different matcher — and the same evaluator the computed 7c
                # bonus below uses, so one phrase means one number wherever it
                # is printed.
                # The permanent being refreshed *is* the source of its own
                # characteristic-defining ability, and it is handed over here
                # for the reason the computed 7c bonus below hands it over: a
                # spec may name a relation to it ("other Rats on the
                # battlefield", "Auras attached to it") rather than only a set
                # of characteristics, and an evaluator with no source answers
                # such a spec by counting all of the set or none of it. Both
                # are silent, and a CDA is recomputed continuously (CR 604.3),
                # so either would be wrong every time anything read the
                # creature.
                value = (
                    evaluate_count(
                        self, player, spec, source=permanent, exclude=permanent
                    )
                    if spec is not None
                    else _count_dynamic_pt(self, player, permanent, dynamic_pt.payload)
                )
                # "…**power** is equal to" leaves the printed toughness alone
                # (Kinetic Augur is */4). ``set_base_pt`` takes None for "leave
                # this one tracking whatever else applies", which is exactly the
                # difference and is why it is not two instruction kinds.
                # "…and its toughness is equal to 7 minus that number"
                # (Shapeshifter). The second half is derived from the same
                # value rather than counted again, which is what makes the
                # printed total a payload number instead of a second template.
                complement = dynamic_pt.payload.get("complement")
                if complement is not None:
                    set_base_pt(permanent, value, max(0, int(complement) - value))
                elif dynamic_pt.payload.get("defines") == "power":
                    # "…and its toughness is equal to **that number plus 1**"
                    # (Lhurgoyf, printed */1+*). Derived from the same value
                    # rather than counted again — the same reason Shapeshifter's
                    # complement is one number and not a second template — so a
                    # card printed "plus 2" is this row with a different
                    # payload. Absent, the printed toughness stands (Kinetic
                    # Augur is */4), which is what the None says.
                    bonus = dynamic_pt.payload.get("toughness_plus")
                    set_base_pt(
                        permanent,
                        value,
                        None if bonus is None else value + int(bonus),
                    )
                elif dynamic_pt.payload.get("defines") == "toughness":
                    # "…**toughness** is equal to the number of Forests you
                    # control" (People of the Woods, a 0/*). The mirror of the
                    # branch above and the same None: the printed power keeps
                    # tracking whatever else applies to it.
                    set_base_pt(permanent, None, value)
                else:
                    set_base_pt(permanent, value, value)

            # A layer-7c bonus whose *size* is computed (Carrion Grub). The
            # spec is the one every reader of a computed amount shares, so the
            # amount here and the amount a where-clause resolves at resolution
            # are the same function of the same board — which is the whole
            # reason this needed no counter of its own.
            for bonus in prog.instructions:
                if bonus.kind != "dynamic_pt_bonus":
                    continue
                # The permanent being refreshed *is* the source of its own
                # static ability, which is what lets a spec name a relation to
                # it ("Auras attached to it") rather than only a set of
                # characteristics.
                value = evaluate_count(
                    self, player, bonus.payload.get("x_from_count") or {},
                    source=permanent,
                )
                _add_static_pt(
                    permanent,
                    resolve_amount(bonus.payload.get("power", 0), value),
                    resolve_amount(bonus.payload.get("toughness", 0), value),
                )

            land_bonus_instr = next(
                (i for i in prog.instructions if i.kind == "conditional_land_bonus"), None
            )
            if land_bonus_instr is not None:
                land_type = land_bonus_instr.payload["land_type"]
                has_land = any(
                    perm.card.primary_type == "land" and perm.has_type(land_type)
                    for perm in self.controlled_by(seat)
                )
                _apply_conditional_bonus(
                    permanent, "conditional_land_bonus", has_land,
                    int(land_bonus_instr.payload["power"]), int(land_bonus_instr.payload["toughness"]),
                )

            untapped_bonus_instr = next(
                (i for i in prog.instructions if i.kind == "conditional_untapped_bonus"), None
            )
            if untapped_bonus_instr is not None:
                _apply_conditional_bonus(
                    permanent, "conditional_untapped_bonus", not permanent.tapped,
                    int(untapped_bonus_instr.payload["power"]), int(untapped_bonus_instr.payload["toughness"]),
                )

            # The general conditional static (engine/static_bonuses.py): its
            # P/T half contributes to this same derived 7c channel. The
            # keyword half lives with the derived grants in
            # _recalculate_lord_buffs — that pass owns their clear/rebuild —
            # and "can't be blocked" is asked at block-legality time.
            for cs in prog.instructions:
                if cs.kind != "conditional_static":
                    continue
                cs_power = int(cs.payload.get("power", 0))
                cs_toughness = int(cs.payload.get("toughness", 0))
                # "…gets +2/+1 as long as it's black. **Otherwise**, it gets
                # -1/-2." (Phyrexian Boon.) The complement arm, on the same
                # instruction as the arm it complements — so the criteria are
                # evaluated **once** and the answer selects which delta applies,
                # rather than two instructions asking two questions that can
                # both come back true.
                #
                # Read before the "no delta" skip below, because an arm that is
                # 0/0 while its complement is not is still a live effect: the
                # skip is for a keyword-only conditional static, which has no
                # delta on either side.
                other_power = int(cs.payload.get("otherwise_power", 0))
                other_toughness = int(cs.payload.get("otherwise_toughness", 0))
                if not (cs_power or cs_toughness or other_power or other_toughness):
                    continue
                holds = conditional_static_holds(
                    self, seat, permanent, cs.payload.get("condition") or {}
                )
                if not holds and (other_power or other_toughness):
                    # The other arm is not "the absence of this one": it is a
                    # contribution in its own right, applied by the same channel
                    # and cleared by the same rebuild.
                    cs_power, cs_toughness, holds = other_power, other_toughness, True
                # "**Enchanted** creature gets +2/+2 as long as an opponent
                # controls a black permanent" (Ice Age's five Scarabs). The
                # sentence an Aura prints about its host, on the same
                # instruction and the same evaluator as the one a creature
                # prints about itself — only the permanent the delta lands on
                # differs, and that is what `subject` says.
                #
                # The seat stays the Aura's controller (CR 109.5: the ability is
                # the Aura's), so "an opponent" is measured from whoever
                # controls the Aura rather than from whoever controls the
                # creature it is stuck to. Those are different players whenever
                # the Aura is on an opponent's creature, which is exactly what
                # these five cards are for.
                recipient = permanent
                if cs.payload.get("subject") == "attached":
                    # The **live** record: CR 611.3b, a continuous effect
                    # applies only while it is attached, and an Equipment that
                    # unattaches stays on the battlefield with the last-known
                    # host still recorded on it.
                    recipient = attached_host(self, permanent, last_known=False)
                    if recipient is None:
                        continue
                _apply_conditional_bonus(
                    recipient, "conditional_static", holds, cs_power, cs_toughness
                )

    def _apply_chosen_body(self, permanent: Permanent, body: dict) -> None:
        """Set a "your choice of" creature's P/T, granted keyword and subtypes.

        Base P/T through engine/pt.py (layer 7b) and the keyword through the
        layer-6 grant API, so the body is the object's characteristics rather
        than a rewritten card — the mistake Animate Artifact used to make.

        The **subtypes** are neither: they are layer 4, and layer 4 is derived
        on every recompute rather than written. So the chosen body is recorded
        and `collect_type_effects` reads it — which is also what makes replacing
        one body with another free, since the previous body's types were never
        stored anywhere to undo.
        """
        from ..keywords import grant_keyword, remove_keyword

        for option in permanent.metadata.get("body_options") or ():
            if option.get("keyword"):
                remove_keyword(permanent, option["keyword"])
        set_base_pt(permanent, int(body["power"]), int(body["toughness"]))
        if body.get("keyword"):
            grant_keyword(permanent, body["keyword"])
        permanent.metadata["chosen_body"] = dict(body)
        self._recompute_continuous_effects()

    def confirm_enter_body_choice(self, player_index: int, option_index: int) -> bool:
        """Answer a pending "your choice of <body>" prompt."""
        return self.resolve_pending_choice("body_choice", player_index, option_index=option_index)

    def _resolve_body_choice(self, choice, option_index: int) -> bool:
        options = choice.data["options"]
        if not (0 <= option_index < len(options)):
            return False
        permanent = choice.data["permanent"]
        chosen = options[option_index]
        self._apply_chosen_body(permanent, chosen)
        self.log.append(
            f"{permanent.card.name} entered as a "
            f"{chosen['power']}/{chosen['toughness']}"
            + (f" with {chosen['keyword']}" if chosen["keyword"] else "")
        )
        self.discard_pending_choice(choice)
        return True

    # -- "As this creature enters, exile X <cards> from your graveyard" -------

    def _entry_exile_candidates(self, choice) -> list[int]:
        """Graveyard positions the printed noun phrase admits, oldest first.

        The picker's hint and the answer's re-check are this one list (idiom 9):
        a client offering the whole graveyard would otherwise turn "X creature
        cards" into "X cards".
        """
        from ..handlers._common import _card_matches_filter

        described = dict(choice.data.get("filter") or {})
        graveyard = self.players[choice.player_index].graveyard
        return [
            index
            for index, card in enumerate(graveyard)
            if _card_matches_filter(card, described)
        ]

    def _resolve_entry_exile(self, choice, picks) -> bool:
        """Exile the chosen cards and place the counter each one buys.

        Every pick is validated before anything moves - a single bad entry
        rejects the whole answer and leaves the prompt queued, so a malformed
        request cannot exile half a payment and leave the creature the wrong
        size. The count is exact rather than "up to": the card says *X* cards,
        and a short answer is the case the CR 614 interceptor already refused
        the entry for.
        """
        player = self.players[choice.player_index]
        permanent = choice.data.get("_entering_permanent") or choice.data.get("permanent")
        wanted = int(choice.data.get("count", 0))
        offered = tuple(choice.data.get("counters") or ())
        legal = set(self._entry_exile_candidates(choice))
        if not isinstance(picks, list) or len(picks) != wanted:
            return False
        chosen: list[tuple[int, str | None]] = []
        seen: set[int] = set()
        for pick in picks:
            index = pick.get("index") if isinstance(pick, dict) else None
            counter = pick.get("counter") if isinstance(pick, dict) else None
            if not isinstance(index, int) or index not in legal or index in seen:
                return False
            seen.add(index)
            if offered:
                if counter not in offered:
                    return False
            elif counter is not None:
                return False
            chosen.append((index, counter))
        # Idiom 11: in a graveyard two copies of one card are literally one
        # object, so the answer's indices are turned into removals highest-first
        # rather than resolved by value - popping in that order is the only
        # walk under which no earlier removal renumbers a later pick.
        exiled: list[tuple[object, str | None]] = []
        for index, counter in sorted(chosen, key=lambda pick: -pick[0]):
            card = player.graveyard.pop(index)
            player.exile.append(card)
            exiled.append((card, counter))
        for _card, counter in exiled:
            if counter is None or permanent is None:
                continue
            if counter == "+1/+1":
                # Through the seam: entering with counters is a counter
                # placement like any other, so a Conclave Mentor raises it
                # (CR 614.1c's replacement applies as the permanent enters).
                self.place_plus1_counters(permanent, 1)
            else:
                add_pt_counters(permanent, counter)
        self.log.append(
            f"{player.name} exiled "
            + (", ".join(card.name for card, _ in exiled) if exiled else "nothing")
            + f" for {choice.data.get('card_name', 'an entering permanent')}"
        )
        self.discard_pending_choice(choice)
        self._recompute_continuous_effects()
        return True

    def _default_entry_exile(self, choice) -> None:
        """The stated policy for a seat nobody asks (idiom 8).

        **Which cards**: the cheapest matching cards first, ties by graveyard
        order. The exile is a cost with no upside of its own - each card bought
        exactly one counter whichever card it was - so the only question is what
        the graveyard loses, and mana value is the engine's own measure of that.

        **Which counter**: the offered kind that raises both halves furthest
        (``min(power, toughness)``, then the total, then printed order). For the
        three this card prints that is ``+1/+1``: ``+2/+0`` leaves a creature
        that dies to any ping it trades with and ``+0/+2`` leaves one that never
        kills anything, and the balanced counter is the only one that both
        survives and threatens.
        """
        player = self.players[choice.player_index]
        wanted = int(choice.data.get("count", 0))
        offered = tuple(choice.data.get("counters") or ())
        candidates = sorted(
            self._entry_exile_candidates(choice),
            key=lambda index: (player.graveyard[index].cmc or 0, index),
        )[:wanted]
        counter = None
        if offered:
            counter = max(
                offered,
                key=lambda kind: (
                    min(pt_counter_deltas(kind)),
                    sum(pt_counter_deltas(kind)),
                    -offered.index(kind),
                ),
            )
        picks = [{"index": index, "counter": counter} for index in sorted(candidates)]
        if not self._resolve_entry_exile(choice, picks):
            # The graveyard cannot have shrunk between the interceptor's count
            # and this arm, so a rejection here is a bug and not a board state.
            # Dropping the prompt rather than leaving it queued keeps a
            # headless seat from stalling on it forever.
            self.discard_pending_choice(choice)

    def _refresh_global_statics(self, all_permanents: list[Permanent]) -> None:
        """Record which permanents each board-wide static currently applies to.

        The list holds the **source permanents**, not a materialised effect, so
        `layer_bridge` derives the characteristics from the source's text on
        every recompute — and a source leaving the battlefield ends its effect
        by dropping out of this list. That is the same shape attached Auras use,
        and it is why there is no flag here to clear.

        Rebuilt from scratch each pass rather than adjusted, for the reason
        recorded on `_add_static_pt`: an adjustment that does not exactly match
        what it undid compounds, and CR 611.3a means this runs constantly.
        """
        from ..global_statics import global_static_sources

        sources = global_static_sources(all_permanents)

        # A static that outlives its source (Titania's Song: "if this
        # enchantment leaves the battlefield, this effect continues until end of
        # turn"). Detected here rather than on a leave-battlefield hook because
        # this method already knows which sources were applying: one that was in
        # the list and is no longer on a battlefield has left, whichever way it
        # went. The cleanup step drops the lingering list (CR 514.2).
        on_battlefield = {id(perm) for perm, _ in sources}
        for perm, static in self._global_static_sources_last:
            if static.continues_until_eot and id(perm) not in on_battlefield:
                if not any(existing is perm for existing, _ in self.lingering_global_statics):
                    self.lingering_global_statics.append((perm, static))
        self._global_static_sources_last = list(sources)
        sources = sources + [
            (perm, static) for perm, static in self.lingering_global_statics
        ]
        for perm in all_permanents:
            # **A static's own source is not exempt.** The scope is whatever
            # the printed sentence says, and none of these templates says
            # "other" — "Creatures you control attack each combat if able" (the
            # Pirate token Pursued Whale gives each opponent) is a creature its
            # controller controls, so CR 508.1d compels the token itself along
            # with the rest of that seat's board. Skipping the source silently
            # exempted exactly the permanent the card is printed on, which for
            # this one is half the drawback the Whale's controller is paid for.
            #
            # The blanket skip cost the other two templates nothing and so hid
            # this: Energy Flux and The Tabernacle at Pendrell Vale are
            # enchantments and a land, and Titania's Song asks for a noncreature
            # *artifact* — each of them is excluded by
            # `_global_static_applies` on its own merits, which is where a
            # scope belongs.
            applying = [
                source
                for source, static in sources
                if self._global_static_applies(static, perm, source, self)
            ]
            if applying:
                perm.metadata["global_static_sources"] = applying
            else:
                perm.metadata.pop("global_static_sources", None)

    #: The printed colour word a ``GlobalStatic``'s scope carries, as the symbol
    #: every filter payload in the engine spells a colour with. One map rather
    #: than a symbol in the table, because the *table* holds what the card
    #: prints.
    _COLOR_SYMBOLS = {
        "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
    }

    @staticmethod
    def _global_static_applies(static, permanent: Permanent, source=None, game=None) -> bool:
        """Whether *static* covers *permanent*.

        "Noncreature artifact" reads the **printed** type line for the creature
        half: asking whether it is currently a creature would include the type
        this very effect adds, and the answer would then depend on whether it
        had already been asked.

        *source* and *game* are needed only by a scope that is **relative** —
        "creatures **you** control" is a comparison between two seats (CR 109.5),
        which no read of the affected permanent alone can answer. A scope that
        needs them and is handed neither answers False, which is the safe
        direction: a board-wide effect applying to the wrong side is worse than
        one that does not apply.
        """
        if static.applies_to in ("artifact", "creature"):
            # Through the layer-6/4 accessors rather than the printed line, so
            # an animated land is a creature to The Tabernacle at Pendrell Vale
            # and a Clone of an artifact is an artifact to Energy Flux.
            if not permanent.has_type(static.applies_to):
                return False
            # "**Green** creatures have …" (Breath of Dreams). Asked through
            # ``subject_matches``, the one reader of what a printed noun phrase
            # means, so "green" here is the same question a targeting line or a
            # trigger's subject asks — and layer 5 for the same reason the type
            # word above is layer 4: a creature a lace has turned green is a
            # green creature, and one that stops being green stops paying the
            # upkeep with nothing to undo.
            if static.colors:
                from ..subject_filters import subject_matches

                if game is None:
                    return False
                return all(
                    subject_matches(
                        game, permanent,
                        {"color_filter": PermanentStateMixin._COLOR_SYMBOLS[colour]},
                    )
                    for colour in static.colors
                )
            return True
        if static.applies_to == "noncreature_artifact":
            printed = permanent.card.type_line.lower()
            return "artifact" in printed and "creature" not in printed
        if static.applies_to == "creature_you_control":
            if source is None or game is None or not permanent.is_creature:
                return False
            return (
                game.controller_index_of(permanent)
                == game.controller_index_of(source)
            )
        return False

    def _enters_tapped_by_a_static(self, permanent: Permanent) -> bool:
        """Whether a static already on the battlefield taps *permanent* as it
        enters (CR 614.1c).

        Whose permanents such a static reaches is relative to **its own**
        controller (CR 109.5), so the observer handed to ``subject_matches`` is
        the source's seat and never the entering permanent's. Read the other way
        round, Kismet would tap its controller's permanents and leave the
        opponent's alone — the card backwards, and right-looking on every board
        where only one player is doing anything.

        Through ``subject_matches`` rather than a comparison here, so "artifacts,
        creatures, and lands your opponents control" means on this seam exactly
        what it means on a trigger's subject or in a sweep. The permanent is
        already on its controller's battlefield by the time this runs
        (``Game._enter_battlefield`` appends before initializing), which is what
        lets the matcher answer a relative key at all.
        """
        for source_seat, source in self.permanents_with_controller():
            for instr in compile_card_oracle(source.effective_card).instructions:
                if instr.kind != ENTER_TAPPED_STATIC_KIND:
                    continue
                described = enter_tapped_filter_from_payload(instr.payload)
                if subject_matches(
                    self, permanent, described, observer=source_seat, source=source
                ):
                    return True
        return False

    def _refresh_land_animation(
        self, all_permanents: list[Permanent], animations: list[LandAnimation]
    ) -> None:
        """Land animators turn lands of a named type into creatures while the
        source is on the battlefield (CR 613 layer 4).

        *animations* is what the sources on the battlefield derive from their
        own printed text (engine/land_animation.py). Nothing here knows which
        cards they are: Kormus Bell's colour and Living Lands' silence about
        colour are both payload.

        Its own pass, ahead of everything that asks "is this a creature?".
        This ran inside the same per-permanent loop as the layer-7a
        characteristic-defining P/T below, so within a single refresh a CDA
        counting creatures saw whatever the animation state had been at the
        *end of the previous pass* — a land animated this pass counted only
        from the next one. CR 613.1 applies layer 4 before layer 7 in one
        application, not across successive ones.

        Recomputed every call so the lands revert the moment the animating
        enchantment leaves (CR 611.3a/b). A land-type override (Evil Presence /
        Phantasmal Terrain) REPLACES the printed type (CR 305.7), so an
        overridden land animates by its override, not its printed type line.
        """
        for permanent in all_permanents:
            animation = (
                next(
                    (
                        a for a in animations
                        # ``land_type`` None is the untyped printing — "All
                        # lands are 1/1 creatures that are still lands" (Living
                        # Plane) — which restricts nothing beyond being a land,
                        # already established by the guard below.
                        if a.land_type is None or permanent.has_type(a.land_type)
                    ),
                    None,
                )
                if permanent.card.primary_type == "land"
                else None
            )
            if animation is not None:
                permanent.metadata["land_animated"] = True
                set_base_pt(permanent, animation.power, animation.toughness)
                if animation.color:
                    permanent.metadata["color_override"] = animation.color
            elif permanent.metadata.get("land_animated"):
                # The animating source is gone: the land is no longer a creature.
                permanent.metadata.pop("land_animated", None)
                clear_base_pt(permanent)
                permanent.metadata.pop("color_override", None)

    def _has_keyword(self, permanent: Permanent, keyword: str) -> bool:
        """Whether *permanent* currently has a keyword ability.

        Printed abilities are part of the object's copiable values and so are
        seeded before layer 1; grants and removals are continuous effects
        sharing CR 613's layer 6, resolved by timestamp. That means a removal
        can take a *printed* ability away and a later grant can put it back —
        neither of which the previous per-keyword if-chain could express, since
        it checked removals first and fell back to scanning oracle text.
        """
        return permanent.has_keyword(keyword)

    def _effective_colors(self, permanent: Permanent) -> set[str]:
        """The color symbols a permanent currently has (honoring color overrides
        and copied colors). Delegates to the shared handler helper."""
        from ..handlers._common import permanent_effective_colors

        return permanent_effective_colors(permanent)

    def _dominant_nontoken_color(self, player: PlayerState) -> str:
        """The color *player* controls most of among nontoken permanents — the
        deterministic default for Jihad's "choose a color" (a color the chosen
        opponent actually controls keeps the enchantment alive)."""
        counts: dict[str, int] = {}
        for perm in self.controlled_by(player):
            if perm.metadata.get("is_token"):
                continue
            for color in self._effective_colors(perm):
                counts[color] = counts.get(color, 0) + 1
        if not counts:
            return "W"
        return max(sorted(counts), key=lambda c: counts[c])

    def _default_chosen_creature_type(self, caster_index: int) -> str:
        """The creature type An-Zerrin Ruins takes when nobody chooses.

        The type *caster_index*'s opponents have most of among nontoken
        creatures — the choice a player would make with the card, and the
        reason a default is stated rather than left to the first word of a
        catalog (idiom 8): a type nobody controls makes the enchantment inert,
        which is legal and pointless.

        Read through ``computed_types``, so a creature whose type line a layer-4
        effect rewrote counts as what it *is* rather than as what it was
        printed as — the same read ``subject_matches`` will make when the
        restriction is applied.

        "Human" when no opponent controls a creature at all: any word is a legal
        choice there, and the printed catalog's most common type is the one most
        likely to matter if a board arrives later.
        """
        from ..layer_bridge import computed_types

        counts: dict[str, int] = {}
        for seat, player in enumerate(self.players):
            if seat == caster_index or player.lost:
                continue
            for perm in self.controlled_by(seat):
                if perm.metadata.get("is_token"):
                    continue
                card_types, subtypes = computed_types(perm)
                if "creature" not in card_types:
                    continue
                for subtype in subtypes:
                    counts[subtype] = counts.get(subtype, 0) + 1
        if not counts:
            return "human"
        return max(sorted(counts), key=lambda word: counts[word])

    def _default_terrain_land_types(self, caster_index: int) -> tuple[str, str]:
        """The ordered pair Illusionary Terrain takes when nobody chooses.

        The type *caster_index*'s opponents control most of, turned into the one
        they control least — the choice a player would make with the card, and
        the reason a default is stated rather than left to the first two words
        of a list (idiom 8): a pair naming a type nobody has makes the
        enchantment inert, which is legal and pointless.

        Counted through ``basic_land_types`` (layer 4), so a land some earlier
        effect already changed is counted as what it is now.
        """
        from ..grammar.phrases import BASIC_LAND_WORDS

        counts = {word: 0 for word in BASIC_LAND_WORDS}
        for seat, player in enumerate(self.players):
            if seat == caster_index or player.lost:
                continue
            for perm in self.controlled_by(seat):
                for land_type in perm.basic_land_types:
                    if land_type in counts:
                        counts[land_type] += 1
        first = max(BASIC_LAND_WORDS, key=lambda word: (counts[word], -BASIC_LAND_WORDS.index(word)))
        second = min(
            (word for word in BASIC_LAND_WORDS if word != first),
            key=lambda word: (counts[word], BASIC_LAND_WORDS.index(word)),
        )
        return first, second

    def _chosen_color_permanent_condition(self, source_perm: Permanent) -> bool:
        """Jihad: whether "the chosen player controls a nontoken permanent of
        the chosen color" currently holds for *source_perm*'s stored choices."""
        seat = source_perm.metadata.get("chosen_player_index")
        color = source_perm.metadata.get("chosen_color")
        if not isinstance(seat, int) or not (0 <= seat < len(self.players)) or not color:
            return False
        return any(
            not perm.metadata.get("is_token") and color in self._effective_colors(perm)
            for perm in self.controlled_by(seat)
        )

    def _chosen_color_most_common_condition(self, source_perm: Permanent) -> bool:
        """Call to Arms: whether "the chosen color is the most common color
        among nontoken permanents the chosen player controls **but isn't tied
        for most common**" holds for *source_perm*'s stored choices.

        A strict maximum, which is what the second half of the clause says and
        why it is one predicate rather than a superlative plus a rider. A
        multicoloured permanent is counted once for every colour it is
        (CR 105.2 makes it one object of several colours, not several objects),
        and a colourless board has no most common colour at all — every colour
        is tied at nothing, so the answer is False rather than vacuously True.

        The sibling condition beside this one asks "controls **a**"; the census
        is the only difference, which is why the two live in one table.
        """
        seat = source_perm.metadata.get("chosen_player_index")
        color = source_perm.metadata.get("chosen_color")
        if not isinstance(seat, int) or not (0 <= seat < len(self.players)) or not color:
            return False
        counts: dict[str, int] = {}
        for perm in self.controlled_by(seat):
            if perm.metadata.get("is_token"):
                continue
            for other in self._effective_colors(perm):
                counts[other] = counts.get(other, 0) + 1
        mine = counts.get(color, 0)
        if mine <= 0:
            return False
        return all(count < mine for other, count in counts.items() if other != color)

    @staticmethod
    def _protection_quality_of(word: str) -> tuple[str, str] | None:
        """The canonical quality one word of a protection clause names, or None.

        Four families (CR 702.16, the qualities this engine models): a colour
        ("white"), "multicolored" (Basri's Lieutenant), a card type
        ("planeswalkers", Sparkhunter Masticore), and a creature subtype
        ("Demons", Baneslayer Angel; "Dogs", Pack Leader's flock). Subtypes
        print pluralized, the catalog stores singulars.
        """
        word = word.strip().lower()
        if not word:
            return None
        symbol = _COLOR_WORD_TO_SYMBOL.get(word)
        if symbol:
            return ("color", symbol)
        if word == "multicolored":
            return ("multicolored", "")
        if word in ("planeswalker", "planeswalkers"):
            return ("card_type", "planeswalker")
        from ..grammar.vocabulary import CREATURE_TYPES

        singular = word[:-1] if word.endswith("s") else word
        if word in CREATURE_TYPES:
            return ("subtype", word)
        if singular in CREATURE_TYPES:
            return ("subtype", singular)
        return None

    def _lord_buff_matches(self, target_perm, source_perm, buff) -> bool:
        """Whether *buff*, contributed by *source_perm*, reaches *target_perm*.

        Every field of the derived filter, checked through the CR 613 accessors
        — an animated Swamp is a creature by layer 4 before a creature anthem is
        considered in layer 7c, and the printed type line is not the authority on
        either that or the subtype.

        A method rather than a local because two readers ask it now: the layer-7c
        refresh that applies the P/T, and the protection reader that derives a
        granted quality from the same buff. Two copies would be two answers to
        "does this lord reach this creature?".
        """
        filt = buff.filter
        if not target_perm.is_creature:
            return False
        if filt.other_than_source and target_perm is source_perm:
            return False
        if filt.colors and not (set(filt.colors) & self._effective_colors(target_perm)):
            return False
        if any(not target_perm.has_type(subtype) for subtype in filt.subtypes):
            return False
        # "**Legendary** creatures you control have …" (Legends' five banding
        # lands). A supertype is not a type: ``has_type`` answers about card
        # types and creature types and would say no to every legend, so this
        # reads the type line through the same helper
        # ``permanent_matches_filter`` uses for the ``supertypes`` payload key.
        # ``effective_card``, so a copy answers with the line it copied
        # (CR 707.2) and a text change is folded in.
        if filt.supertypes:
            held = target_perm.effective_supertypes
            if not all(word in held for word in filt.supertypes):
                return False
        # "…with a +1/+1 counter on it" (Pridemalkin): the counter record, not
        # the P/T bonus — a pump writes power_bonus and places no counter, so
        # reading the bonus would buff the wrong creatures.
        if filt.with_plus1_counter and int(
            target_perm.metadata.get("plus_counters", 0)
        ) <= 0:
            return False
        # "Creatures named Kobolds of Kher Keep" (Rohgahh of Kher Keep). By
        # *name*, never identity — a second copy and a token wearing the name
        # both match, and the buffing lord matches itself when it shares it
        # (Ivory Guardians prints no "other"). ``effective_card``, so a copy
        # answers with the name it copied (CR 707.2); ``name_key`` on both
        # sides, so the parser's lowercase rendering equals Oracle's spelling
        # — the same comparison ``permanent_matches_filter`` makes for the
        # payload key this field mirrors.
        if filt.named and name_key(
            target_perm.effective_card.name
        ) != name_key(str(filt.named)):
            return False
        # "Creatures **with flying** get +1/+1." (Serra Aviary.) Layer 6 asked
        # from layer 7c — ``has_keyword``, never ``card.keywords``, so a
        # creature wearing an Aura's flying is in the anthem (CR 613.1f) and one
        # a removal took it from is out. The reads-not-recompute direction is
        # what makes that free: this predicate runs on every recompute and the
        # answer is derived each time, so a word gained or lost moves the
        # creature in or out with nothing to add back or subtract (CR 613.5).
        if any(not target_perm.has_keyword(word) for word in filt.with_keywords):
            return False
        # "Creatures **without flying** have reach." (Chaosphere.) The same
        # layer-6 question negated, through the same accessor -- so a creature
        # given flying leaves the anthem on the next read and one that lost it
        # joins, with nothing to add back or subtract (CR 613.5).
        if any(target_perm.has_keyword(word) for word in filt.without_keywords):
            return False
        return True

    def _protection_qualities(self, permanent: Permanent) -> set[tuple[str, str]]:
        """The qualities this permanent has protection from (CR 702.16).

        Sourced from a printed "protection from [quality]" line (static or
        comma-joined keyword form), from an attached Aura (the Ward cycle), or
        from a ``protection_from_<color>`` metadata flag. A word naming no
        modelled quality contributes nothing — but such a line never compiles
        in the first place: the keyword gate refuses it with the clause named.
        """
        qualities: set[tuple[str, str]] = set()
        program = compile_card_oracle(permanent.effective_card)

        def _absorb(clause: str) -> None:
            # CR 702.16g/h/i: "protection from [A] and from [B]" (and comma
            # separated variants) is shorthand for several separate protection
            # abilities.
            for word in re.split(r",|\band from\b|\band\b", clause):
                quality = self._protection_quality_of(word)
                if quality is not None:
                    qualities.add(quality)

        for instr in program.instructions:
            if instr.kind == "static_line" and instr.value.startswith("protection from "):
                _absorb(instr.value[len("protection from "):].strip())
            elif instr.kind == "keyword_line":
                # Protection also rides comma-joined keyword lines ("Flying,
                # first strike, lifelink, protection from Demons and from
                # Dragons"), and a standalone protection line is admitted as a
                # keyword line too — same shorthand, same reading as the
                # static form above.
                for part in instr.value.split(","):
                    part = part.strip()
                    if part.startswith("protection from "):
                        _absorb(part[len("protection from "):].strip())
        # Two sources with different lifetimes, which is why both exist.
        #
        # An Aura's protection lasts exactly as long as it is attached, so it is
        # read off the Aura (the Ward cycle) and ends when the Aura leaves with
        # nothing having to remove it. That grant used to be stamped into the
        # metadata channel below and cleaned up by name on removal.
        for aura in auras_attached_to(permanent):
            for word in aura_protection_colors(aura.effective_card.oracle_text):
                symbol = _COLOR_WORD_TO_SYMBOL.get(word)
                if symbol:
                    qualities.add(("color", symbol))
        # A lord's grant ("Other Cats you control … have protection from Dogs",
        # Feline Sovereign). **Derived**, exactly as the Aura grant above is: a
        # lord buff is cleared and rebuilt on every recompute, so a grant stamped
        # into metadata would be one nothing clears — and reading it off the
        # lord means it ends when the lord leaves with nothing having to remove
        # it.
        for lord_seat, lord in self.permanents_with_controller():
            for instr in compile_card_oracle(lord.effective_card).instructions:
                if instr.kind != LORD_BUFF_KIND:
                    continue
                buff = lord_buff_from_payload(instr.payload)
                if not buff.protection_from:
                    continue
                # A conditional lord grants nothing while its condition fails.
                # Asked here as well as at the P/T recompute, because this
                # reader derives from the compiled program directly — a buff
                # read past its own condition would grant protection on a board
                # the card says it does not.
                if buff.condition and not self._lord_buff_condition(
                    lord_seat, lord, buff.condition
                ):
                    continue
                if not self._lord_buff_matches(permanent, lord, buff):
                    continue
                for word in buff.protection_from:
                    quality = self._protection_quality_of(word)
                    if quality is not None:
                        qualities.add(quality)
        # The metadata channel, for protection granted with a lifetime of its own
        # (Feat of Resistance, until end of turn). Any quality, not just a
        # colour: the key is written from the same reader that parses a printed
        # clause, so a granted "protection from Demons" reads the same as a
        # printed one.
        for key in permanent.metadata:
            if key.startswith("protection_from_"):
                quality = self._protection_quality_of(key[len("protection_from_"):])
                if quality is not None:
                    qualities.add(quality)
        # No Sleight of Mind step here: the clause above was read off
        # ``effective_card``, whose text layer 3 has already rewritten, so
        # "protection from blue" already reads "protection from red". Remapping
        # again applied the change twice — invisible for the one-effect case
        # only because the second application had nothing left to match.
        return qualities

    def _protection_colors(self, permanent: Permanent) -> set[str]:
        """The colour slice of :meth:`_protection_qualities`, kept for the
        consumers whose question genuinely is a colour (the Aura-attach checks,
        the Circle prompts)."""
        return {
            value
            for kind, value in self._protection_qualities(permanent)
            if kind == "color"
        }

    def _permanent_has_quality(
        self, source: Permanent, quality: tuple[str, str], *,
        as_damage_source: bool = False,
    ) -> bool:
        """Whether *source* has *quality* (CR 702.16e/f).

        *as_damage_source* asks the colour half of the question about the source
        **as a source of damage** (CR 609.7b) rather than about the object:
        Ghostly Flame makes a red creature a colorless source of damage and
        leaves the creature red, so its combat damage is not prevented by
        protection from red while the creature is still an illegal target for
        "enchant red creature". Only the damage paths pass it.
        """
        kind, value = quality
        if kind == "color":
            if as_damage_source:
                from ..damage_source_colors import damage_source_colors

                return value in damage_source_colors(self, source)
            return value in self._effective_colors(source)
        if kind == "multicolored":
            # Deliberately not rewritten by a damage-source static: "colorless
            # sources of damage" says what colour the source is, and a
            # colourless object is not multicoloured either — but no card in
            # this pool prints protection from multicoloured *and* meets one, so
            # widening the rewrite to a quality nothing exercises would be a
            # claim with nothing behind it.
            return len(self._effective_colors(source)) >= 2
        if kind in ("card_type", "subtype"):
            # has_type resolves through the layer system, so a granted or
            # layer-4 type counts exactly as a printed one.
            return source.has_type(value)
        return False

    def _card_has_quality(self, card: CardDefinition, quality: tuple[str, str]) -> bool:
        """The same question of a *card* — a spell on the stack, which has no
        permanent to ask the layers about."""
        kind, value = quality
        if kind == "color":
            return value in card.colors
        if kind == "multicolored":
            return len(set(card.colors)) >= 2
        if kind in ("card_type", "subtype"):
            return value in (card.type_line or "").lower().split()
        return False

    def _is_protected_from(
        self, victim: Permanent, source: Permanent, *, as_damage_source: bool = False,
    ) -> bool:
        """True if *victim* has protection from a quality *source* has
        (CR 702.16e/f).

        *as_damage_source* is passed by the damage half of protection
        (CR 702.16e, the combat damage step) and **not** by the blocking half
        (CR 702.16d/509.1b, the declare-blockers step): a static that rewrites a
        source's colour *for damage* changes which damage is prevented and not
        which creatures may block, and reading it at both would be a strictly
        different card.
        """
        return any(
            self._permanent_has_quality(
                source, quality, as_damage_source=as_damage_source
            )
            for quality in self._protection_qualities(victim)
        )

    def _can_be_targeted(
        self,
        target: Permanent,
        source_card: CardDefinition | None,
        *,
        caster_index: int | None = None,
        ability_source=None,
        source_spec: dict | None = None,
    ) -> bool:
        """Whether *target* is a legal target for *source_card*
        (CR 702.16b/702.18/702.11).

        Shroud forbids any targeting; protection forbids targeting by sources of
        the protected color. A ``None`` source is treated as colorless.

        *ability_source* is the object whose **ability** is choosing this target,
        and passing it is what says the choice belongs to an ability rather than
        to a spell. Its presence is the flag rather than a separate boolean: an
        immunity narrowed to a class of source ("can't be the target of
        abilities from artifact sources", Artifact Ward; "…or abilities from
        white sources", Raiding Party) needs the source object itself, because
        an animated artifact land is an artifact source and its printed type
        line says otherwise, and because a colour is a layer question. Every
        caller that leaves it out is aiming a spell, where the immunity does
        not apply.

        Hexproof (CR 702.11b/d) forbids targeting by spells and abilities an
        *opponent* of the target's controller controls, so it is asked only when
        the caller says who is casting — a probe with no seat keeps the
        seat-blind answer. "Hexproof from <colour>" narrows the same rule to
        sources of that colour; it is a different keyword from bare hexproof
        (a colour word in the abilities set, seeded from the ingested keywords
        field), which is why both spellings are consulted.

        *source_spec* is the **target description** the chooser announced, for
        the one restriction that is about the description rather than about the
        source: "can't be the target of spells that can target only Walls"
        (Wall of Shadows). A spell's is derived here from its own card, so the
        three casting callers need pass nothing; an ability's cannot be — a
        permanent may carry several abilities that target differently, and
        ``ability_source`` names the object, not which of its abilities is
        choosing — so the enumerator, which is holding the spec it is
        enumerating, hands it over.
        """
        if self._has_keyword(target, "shroud"):
            from ..target_immunity import shroud_waived_for

            # "Until end of turn, Autumn Willow can be the target of spells and
            # abilities controlled by **target player** as though it didn't
            # have shroud." (CR 702.18 with CR 609.4's hole in it.) The waiver
            # is per seat, so it is asked with the seat whose spell or ability
            # is choosing: the caster for a spell, and the *controller of the
            # source* for an ability, which is CR 109.5's answer and not
            # necessarily the same seat.
            #
            # A caller that names neither gets the shroud, which is the
            # direction that cannot let an illegal targeting through — the same
            # answer every other seat-relative immunity here gives a seat-blind
            # probe.
            chooser = caster_index
            if chooser is None and ability_source is not None:
                chooser = self.controller_index_of(ability_source)
            if not shroud_waived_for(target, chooser):
                return False
        # "…can't be the target of Aura spells" (Bartel Runeaxe, Tetsuo
        # Umezawa), "…can't be the target of spells" (Anti-Magic Aura). Asked
        # only when the chooser is a *spell*, which `ability_source is None`
        # says: these clauses narrow shroud to spells, and Artifact Ward's
        # sibling below narrows it to abilities. A spell and an ability are
        # separately targeted (CR 115.1a, CR 115.1c/d) and a card may print
        # either without the other, so neither may answer for both.
        if ability_source is None and source_card is not None:
            from ..target_immunity import (
                spell_is_in_class,
                spell_target_immunity_classes,
            )

            if any(
                spell_is_in_class(source_card, spell_class)
                for spell_class in spell_target_immunity_classes(target)
            ):
                return False
        if ability_source is not None:
            from ..target_immunity import (
                ability_source_immunity_classes,
                source_is_in_class,
            )

            if any(
                source_is_in_class(self, ability_source, source_class)
                for source_class in ability_source_immunity_classes(target)
            ):
                return False
        # "…can't be the target of spells that can target only Walls or of
        # abilities that can target only Walls" (Wall of Shadows). A narrowed
        # shroud again, but narrowed along the *other* axis: the two clauses
        # above ask what the source **is**, this one asks what the source's own
        # target description **admits**. Tunnel ("Destroy target Wall") is
        # stopped; Terror ("Destroy target creature") is not, however plainly it
        # could kill the same Wall.
        #
        # Asked per source kind, because a spell and an ability are separately
        # targeted (CR 115.1a, CR 115.1c/d) so a card can stop one and not the
        # other, and the two answers come from different places: a spell's
        # description is derived from its card right here, while an ability's
        # must be handed in — ``ability_source`` names the permanent, and a
        # permanent may carry several abilities that target differently.
        if source_card is not None or source_spec is not None:
            from ..target_immunity import (
                ABILITY_SOURCE,
                SPELL_SOURCE,
                narrow_source_immunity_subtypes,
            )

            forbidden = narrow_source_immunity_subtypes(
                target, ABILITY_SOURCE if ability_source is not None else SPELL_SOURCE
            )
            if forbidden:
                from ..targeting import derive_cast_spec, spec_only_subtype

                spec = source_spec
                if spec is None and ability_source is None:
                    from ..oracle import compile_card_oracle

                    spec = derive_cast_spec(
                        source_card, compile_card_oracle(source_card)
                    )
                only = spec_only_subtype(spec)
                if only is not None and only in forbidden:
                    return False
        if source_card is not None and any(
            self._card_has_quality(source_card, quality)
            for quality in self._protection_qualities(target)
        ):
            return False
        if caster_index is not None and caster_index != self.controller_index_of(target):
            if self._has_keyword(target, "hexproof"):
                return False
            if source_card is not None:
                source_colors = set(source_card.colors)
                for word, symbol in _COLOR_WORD_TO_SYMBOL.items():
                    if symbol in source_colors and self._has_keyword(
                        target, f"hexproof from {word}"
                    ):
                        return False
        return True

    def _recalculate_lord_buffs(self) -> None:
        """Apply every lord buff on the battlefield (CR 611.3a, layers 6 and 7c).

        A static ability is not locked in: it applies whenever its criteria are
        met, so this is recomputed from the current board rather than adjusted
        incrementally. What each source gives and who it reaches is derived from
        its own printed sentence by ``engine/lord_buffs.py`` — this method reads
        that table and honours every field of it. Before the table it read the
        colour and the controller off a bare ``static_line`` and nothing else,
        with the subtype lords re-parsed by a second regex further down, so a
        subtype, an "other", or a state qualifier had to become either a new
        instruction kind or a silently dropped restriction.

        Nothing accumulates. Every channel written below is cleared by this same
        function immediately before it is rebuilt, which is what makes removal
        the absence of a contribution rather than a delta someone has to
        remember and subtract (CR 611.3b).
        """
        all_perms = list(self.all_permanents())

        # Step 1: clear the derived channels this function owns.
        for perm in all_perms:
            perm.metadata.pop("static_buff_power", None)
            perm.metadata.pop("static_buff_toughness", None)
            perm.metadata.pop(QUALIFIED_BUFFS, None)
            clear_derived_grants(perm)
            for flag in perm.metadata.pop("_lord_granted_flags", None) or ():
                perm.metadata.pop(flag, None)

        def _add_static_buff(perm: Permanent, buff: LordBuff) -> None:
            if not (buff.power or buff.toughness):
                return
            qualifiers = buff.filter.qualifiers
            if not qualifiers:
                perm.metadata["static_buff_power"] = (
                    int(perm.metadata.get("static_buff_power", 0)) + buff.power
                )
                perm.metadata["static_buff_toughness"] = (
                    int(perm.metadata.get("static_buff_toughness", 0)) + buff.toughness
                )
                return
            # A qualified buff is contributed here but *evaluated* when P/T is
            # read (layer_bridge.qualifier_holds), so it tracks a creature
            # tapping or attacking between recomputes.
            # Keyed by the whole tuple of states, so two buffs are summed
            # together only when they answer to the same description. Keying by
            # one word would merge "untapped" with "untapped and not attacking"
            # and apply the stricter buff on the looser test.
            qualified = perm.metadata.setdefault(QUALIFIED_BUFFS, {})
            power, toughness = qualified.get(qualifiers, (0, 0))
            qualified[qualifiers] = (power + buff.power, toughness + buff.toughness)

        def _grant_ability(perm: Permanent, flag: str) -> None:
            perm.metadata[flag] = True
            tracked = perm.metadata.setdefault("_lord_granted_flags", [])
            if flag not in tracked:
                tracked.append(flag)

        # A copy uses the copied creature's copiable card (types + abilities), so
        # lord static abilities and subtype checks resolve against it (CR 707.2).
        # ``Permanent.effective_card`` is that answer, and it also applies the
        # CR 613 layer-3 text change — a local re-implementation of the copy half
        # silently skipped the text half, which is the second-opinion bug this
        # whole pass exists to remove.
        def _eff_card(perm: Permanent):
            return perm.effective_card

        # A Magical Hack land-word swap on the lord itself needs nothing here.
        # It rewrites the walk in the lord's *text* (mountainwalk ->
        # islandwalk on Goblin King), so the buff this loop derives is compiled
        # from the changed line and already says islandwalk. Patching the
        # derived keywords a second time was the layer-3-at-each-reader shape.

        _matches = self._lord_buff_matches

        # Step 2: re-apply from every permanent currently on the battlefield.
        #
        # **Gathered first, then applied in two passes, in CR 613's own order.**
        # A lord contributes to two layers — 6 (the keyword grants and removals)
        # and 7c (the P/T delta) — and layer 6 is applied first (CR 613.3,
        # CR 613.4). That was invisible while every filter asked only about
        # printed characteristics; "Creatures **with flying** get +1/+1" (Serra
        # Aviary) makes the 7c pass ask a layer-6 question, so a single pass
        # would answer it off a half-built layer 6 and the anthem would reach
        # or miss a creature depending on the order the battlefield happens to
        # hold its lords in.
        #
        # A keyword-filtered buff that itself *grants* a keyword is CR 613.8b's
        # dependency loop, and it gets 613.8b's answer: pass 2a reads layer 6 as
        # it stood when the recompute began, which is timestamp order.
        gathered: list[tuple] = []
        for ctrl_seat, source_perm in self.permanents_with_controller():
            ctrl_player = self.players[ctrl_seat]
            program = compile_card_oracle(_eff_card(source_perm))
            for instr in program.instructions:
                if instr.kind != LORD_BUFF_KIND:
                    continue
                buff = lord_buff_from_payload(instr.payload)
                if buff.condition and not self._lord_buff_condition(
                    ctrl_seat, source_perm, buff.condition
                ):
                    continue
                if buff.per_counter:
                    # "All creatures get +1/+0 **for each time counter on this
                    # artifact**." (Infinite Hourglass.) The delta is read off
                    # the *source* at every recompute, which is what CR 613.4b
                    # asks of a value that keeps changing — and why the counter
                    # word travels on the buff rather than the size being
                    # frozen when the sentence compiled. Zero counters is no
                    # contribution at all, not a zero one: the buff carries only
                    # a P/T delta (``lord_buffs.LordBuff.per_counter`` refuses
                    # the combination with anything else), so there is nothing
                    # else it could still be giving.
                    scale = counters_on(source_perm, buff.per_counter)
                    if scale <= 0:
                        continue
                    buff = replace(
                        buff, power=buff.power * scale, toughness=buff.toughness * scale
                    )
                if buff.filter.controller == "you":
                    scope = [ctrl_player]
                elif buff.filter.controller == "opponent":
                    # "Creatures your opponents control get -1/-0" (Waker of
                    # Waves). Spelled out rather than folded into the
                    # everyone-else default: read as "every player" the source
                    # would shrink its own side too.
                    scope = [p for p in self.players if p is not ctrl_player]
                else:
                    scope = self.players
                flag = (
                    GRANTED_ACTIVATED_ABILITIES[buff.granted_ability]
                    if buff.granted_ability
                    else None
                )
                gathered.append((source_perm, buff, flag, scope))

        def _reached_by(source_perm, buff, scope):
            for player in scope:
                for target_perm in self.controlled_by(player):
                    if _matches(target_perm, source_perm, buff):
                        yield target_perm

        # Pass 2a — layer 6 (CR 613.3): every ability this board's lords grant
        # or take away ("Other Goblins … have mountainwalk", Gravity Sphere's
        # "All creatures lose flying").
        for source_perm, buff, _flag, scope in gathered:
            if not (buff.keywords or buff.lost_keywords):
                continue
            for target_perm in _reached_by(source_perm, buff, scope):
                for keyword in buff.keywords:
                    add_derived_grant(target_perm, keyword)
                for keyword in buff.lost_keywords:
                    add_derived_removal(target_perm, keyword)

        # Pass 2b — layer 7c (CR 613.4c) and the granted activated ability,
        # over a board whose layer 6 is complete.
        for source_perm, buff, flag, scope in gathered:
            for target_perm in _reached_by(source_perm, buff, scope):
                _add_static_buff(target_perm, buff)
                if flag is not None:
                    _grant_ability(target_perm, flag)

        # Step 3: conditional self-grants — the keyword half of "…as long as
        # <condition>" (Sigiled Contender's lifelink, Gnarled Sage's
        # vigilance). Written in this pass because it owns the derived-grant
        # channel's clear/rebuild: a grant written by any other pass would be
        # wiped whenever this one runs alone. The P/T half is contributed by
        # _refresh_dynamic_creatures into its own derived channel.
        for cs_seat, cs_perm in self.permanents_with_controller():
            for cs in compile_card_oracle(_eff_card(cs_perm)).instructions:
                if cs.kind != "conditional_static":
                    continue
                cs_keywords = cs.payload.get("keywords") or ()
                if not cs_keywords:
                    continue
                if not conditional_static_holds(
                    self, cs_seat, cs_perm, cs.payload.get("condition") or {}
                ):
                    continue
                # "Enchanted creature has first strike as long as it's blocking
                # and you control a snow land." (Snow Devil.) The same
                # instruction with the grant landing on the host, read off the
                # same ``subject`` key ``_refresh_dynamic_creatures`` already
                # reads for the P/T half — one sentence, one instruction, one
                # answer about which permanent it is about.
                #
                # The seat stays the Aura's (CR 109.5), so "you control a snow
                # land" is measured from whoever controls the Aura even when
                # the creature belongs to somebody else.
                #
                # **Here rather than in ``layer_bridge``**, where the
                # unconditional Aura keyword grants live and where the CR 613.7e
                # attach timestamp is available. ``collect_ability_effects`` is
                # deliberately game-free — the board half of this condition
                # needs both the game and a seat, and giving a layer collector a
                # game handle is the read `tests/engine/test_layer_reads.py`
                # exists to keep out. The cost is the timestamp: this grant
                # sorts with the derived channel rather than at the Aura's
                # attach time. Nothing in the pool orders two contending
                # keyword grants, and a keyword granted twice is granted once.
                recipient = cs_perm
                if cs.payload.get("subject") == "attached":
                    recipient = attached_host(self, cs_perm, last_known=False)
                    if recipient is None:
                        continue
                for keyword in cs_keywords:
                    add_derived_grant(recipient, keyword)

    # Conditions a lord buff may hang on, keyed by what engine/lord_buffs.py
    # derives. A condition that table can name with no predicate here would be a
    # buff applied unconditionally, which is the failure this whole family had;
    # tests/engine/test_lord_buff_table.py holds the two lists to each other.
    _LORD_BUFF_CONDITIONS = {
        "chosen_color_permanent": "_chosen_color_permanent_condition",
        "chosen_color_most_common": "_chosen_color_most_common_condition",
    }

    def _lord_buff_condition(
        self, seat: int, source_perm: Permanent, condition: str | dict
    ) -> bool:
        # A dict is a lowered condition payload from the grammar's statics
        # production ("as long as an opponent controls a nontoken red
        # permanent", Ivory Guardians), answered by the same evaluator every
        # ``conditional_static`` payload gets — the lowering refused anything
        # that evaluator does not test. A string is a key into the legacy
        # table above (Jihad, whose stored choices no payload can express).
        if isinstance(condition, dict):
            return conditional_static_holds(self, seat, source_perm, condition)
        return getattr(self, self._LORD_BUFF_CONDITIONS[condition])(source_perm)

    def _nameless_race_cap(self, seat: int, described: dict) -> int:
        """The most life "the amount you pay can't be more than …" allows.

        Two halves the printed sentence adds: matching permanents the opponents
        control, and matching cards in their graveyards. Through the control
        seam for the first (``controls`` is a seat question, CR 109.5) and the
        card matcher for the second, because a card in a zone has no computed
        characteristics at all (CR 613.1).
        """
        from ..handlers._common import _card_matches_filter, permanent_matches_filter

        total = 0
        for opponent in self.opponents_of(seat):
            for perm in self.controlled_by(opponent):
                if permanent_matches_filter(perm, described["battlefield"]):
                    total += 1
            for card in self.players[opponent].graveyard:
                if _card_matches_filter(card, described["graveyard"]):
                    total += 1
        return total
