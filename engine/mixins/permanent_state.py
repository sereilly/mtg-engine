"""A permanent's state as it enters (CR 614.1c), and the copies it can become.

``_initialize_permanent_state`` runs once for every permanent on its way onto
the battlefield and performs each entry replacement its text or the board's
statics print: **the copy first** (CR 614.12, CR 707.5), because a "you may
have this enter as a copy" choice decides which of the others apply at all;
then entering tapped (its own line, or a static already on the battlefield,
``_enters_tapped_by_a_static``), entering with counters, "as this enters,
choose ..." and the entry tolls. A choice it arms is stamped with the
permanent it is about, because a permanent whose entry choice is still owed
has not finished entering.

The copy effects live beside it because the first of them *is* an entry
replacement and the others share its one write (``engine/copies.py``'s
``become_copy``): a permanent entering as a copy, a token that is a copy
(``create_token_copy``). ``_has_keyword`` and ``_effective_colors`` are the
two layer reads (CR 613 layers 6 and 5) every part of a permanent's state
asks.

This module was one 4,737-line class. What else it held is one mixin each,
composed onto ``Game`` immediately after ``PermanentStateMixin``:

    entry_choices      EntryChoicesMixin      what an entering permanent chooses,
                                              and what a seat nobody asks chooses
    board_statics      BoardStaticsMixin      board-wide statics and the layer-4 pass
    dynamic_creatures  DynamicCreaturesMixin  the recompute's layer-1 and -7 half
    lords              LordBuffsMixin         lord buffs (layers 6 and 7c)
    protection         ProtectionMixin        protection (CR 702.16), targetability

They are disjoint (no method is defined twice, none calls ``super()``), so
their order among themselves carries no meaning; each reaches the others
through ``self``.
"""

from __future__ import annotations

import re

from ..enter_effects import (ENTERED_BATTLEFIELD_TURN,
                             entry_exile_requirement,
                             entry_sacrifice_requirement,
                             sacrifice_any_number_on_enter,
                             sacrifice_all_on_enter, discards_hand_on_enter,
                             CHOOSE_COLOR_AND_OPPONENT_ON_ENTER,
                             chooses_color_on_enter,
                             chooses_color_and_creature_type_on_enter,
                             chooses_two_land_types_on_enter,
                             chooses_creature_type_on_enter,
                             chooses_land_type_on_enter,
                             choose_one_of_two_on_enter,
                             chooses_two_card_names_on_enter,
                             chooses_card_name_on_enter,
                             chooses_opponent_on_enter,
                             chooses_opponent_and_card_name_on_enter,
                             COPY_ARTIFACT_ON_ENTER, COPY_CREATURE_ON_ENTER,
                             ENTERS_TAPPED, enters_with_counted_pt_counters,
                             enters_with_x_pt_counters,
                             enters_with_x_named_counters,
                             choose_number_on_enter, pay_any_life_on_enter,
                             enters_with_pt_counters, kicked_entry,
                             enters_with_named_counter,
                             LOSE_LIFE_EQUAL_TO_TOTAL_ON_ENTER)
from ..entry_choices import (LIFE_PAID_AS_ENTERED, CHOSEN_COLOR_KEY,
                             CHOSEN_LAND_TYPE_KEY, choosable_bodies)
from .. import copies
from ..named_counters import add_counters as add_named_counters
from ..cast_costs import KICKED, KICKED_WITH
from ..keywords import grant_ability_line, grant_keyword
from ..tokens import make_token_card
from ..enter_tapped_statics import (ENTER_TAPPED_STATIC_KIND,
                                    enter_tapped_filter_from_payload)
from ..cast_bans import CHOSEN_CARD_NAMES
from ..land_types import CHOSEN_LAND_TYPES
from ..handlers._amounts import evaluate_count
from ..subject_filters import subject_matches
from ..models import Permanent
from ..oracle import compile_card_oracle
from ..line_rewrites import expand_card_lines


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
        # **The copy first** (CR 614.12, CR 707.5). Every entry replacement below
        # — enters tapped, enters with counters, "as this enters, choose" — is
        # asked of the permanent "as it would exist on the battlefield, taking
        # into account replacement effects that have already modified how it
        # enters", and a copy-as-enter choice is exactly such a replacement:
        # its result decides which of the others apply at all. So it is made
        # before any of them, and everything after reads ``effective_card``.
        #
        # Reading the printed card instead, a Clone copying Spike Feeder entered
        # as a 0/0 with no counters and died, and a token copy (whose own card
        # carries nothing but a name, ``create_token_copy``) of Leviathan
        # entered untapped and — with no type to stamp below — was never
        # summoning sick at all: every Dance of Many, Dual Nature and Sublime
        # Epiphany token could attack the turn it was made.
        self._enter_as_a_copy(permanent)
        if permanent.effective_card.primary_type in ("creature", "land", "artifact"):
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
        program = compile_card_oracle(permanent.effective_card)
        text = program.normalized_text

        # CR 306.5b: a planeswalker enters with loyalty counters equal to its
        # printed loyalty number — an intrinsic replacement effect, so it is
        # part of entering, not a triggered ability. Unconditional for the card
        # type: the ability is not printed text, so there is no phrase in
        # engine/enter_effects.py to probe for.
        # (Of the permanent as it enters — its copiable values, CR 707.2 —
        # and not of the card it is printed on: a copy enters with the
        # copied planeswalker's loyalty.)
        if permanent.has_type("planeswalker"):
            printed = permanent.effective_card.loyalty
            if printed is not None and printed.strip().lstrip("-").isdigit():
                permanent.metadata["loyalty_counters"] = int(printed)

        # enters tapped (static creature/permanent lines or normalized text).
        # The phrases probed for here live in engine/enter_effects.py, which
        # engine/grammar/registries.py also reads to tell the parser these lines
        # are already implemented — one string, two readers, so they cannot
        # drift apart.
        #
        # "…enters tapped **unless** …" is a condition on the tapping and is
        # not this unconditional line's to perform — which is a question about
        # the *sentence* that says the land enters so. It was asked of the whole
        # text, so a card whose **other** sentence said "unless" never entered
        # tapped: "This land enters tapped. When this land enters, sacrifice it
        # unless you return an untapped Plains you control to its owner's
        # hand." — Karoo and its four siblings (Coral Atoll, Dormant Volcano,
        # Everglades, Jungle Basin) came in untapped, five of the 91 cards in
        # the pool that say the words and the only five the two readings
        # disagree about.
        if any(line for line in program.static_lines if ENTERS_TAPPED in line) or any(
            ENTERS_TAPPED in sentence and "unless" not in sentence
            for sentence in re.split(r"[.\n]", text)
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
            # *other* bodies before granting the chosen one's, which is what
            # lets the prompt's answer replace the default body applied here.
            # (It used to be load-bearing a second way: layer 6's seed read
            # "with flying" and "with defender" off this sentence, so every
            # Primal Clay had both until that clear ran. The seed reads keyword
            # lines only now -- ``layer_bridge._printed_abilities_cached``.)
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
        # "As this artifact enters, choose an opponent **and a card name other
        # than a basic land card name**." (Booby Trap.) The same pair one
        # characteristic over: a seat and a second value, asked in one prompt.
        # It shares this branch rather than getting one of its own because
        # everything about the seat half is identical — the default, the
        # opponent list, the metadata key — and only which second question is
        # asked differs, which is what the two flags say.
        needs_name = chooses_opponent_and_card_name_on_enter(text)
        if needs_color or needs_name or chooses_opponent_on_enter(text):
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
            default_name = None
            if needs_name:
                # The default names a card the chooser can actually see — one
                # in an opponent's graveyard, else one of their permanents — for
                # Runed Halo's stated reason: naming nothing makes the trap
                # inert, which is legal and is not a choice any player would
                # make (idiom 8).
                #
                # Asked of the **caster**, which is what ``_nameable_cards``
                # means by its argument: it returns what every *other* seat
                # shows, so the caster's own board is excluded and the chosen
                # player's is exactly what is offered. Passing the chosen seat
                # would offer the caster their own cards, which is the one set
                # this trap can never catch.
                default_name = self._default_named_card(
                    caster_index, exclude=permanent.card.name
                )
                permanent.metadata["chosen_card_name"] = default_name or ""
            if needs_color or needs_name or len(opponents) > 1:
                self.arm_pending_choice(
                    "enter_choice", caster_index,
                    card_name=permanent.card.name, permanent=permanent,
                    needs_color=needs_color, opponents=opponents,
                    default_seat=chosen, default_color=default_color,
                    # Absent for every entry written before Booby Trap, so the
                    # prompt those cards raise is byte-identical.
                    **(
                        {
                            "needs_card_name": True,
                            "default_card_name": default_name or "",
                            "choices": self._nameable_cards(
                                caster_index, exclude=permanent.card.name
                            ),
                        }
                        if needs_name else {}
                    ),
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
            default_color = self._default_chosen_color(caster_index)
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
        # "As this artifact enters, choose **a color and a creature type**."
        # (Volrath's Laboratory.) Both halves of one CR 614.1c choice, so one
        # prompt with two answers — the shape Jihad's colour-and-opponent pair
        # already has, with a second catalog where that one has a seat.
        #
        # Its own branch and not the two singular ones firing together, because
        # ``chooses_color_on_enter`` declines "choose a color and …" by design:
        # the lookahead that keeps Jihad's opponent from being dropped would
        # drop this card's creature type the same way. Two prompts would also be
        # two decisions where the card prints one.
        #
        # Both defaults are the opponents'-board reading the singular branches
        # take (idiom 8): a colour and a type nobody controls make the token
        # this artifact prints inert, which is legal and is not a choice any
        # player would make.
        chooses_pair = chooses_color_and_creature_type_on_enter(text)
        if chooses_pair:
            default_color = self._default_chosen_color(caster_index)
            permanent.metadata["chosen_color"] = default_color
            permanent.metadata["chosen_creature_type"] = (
                self._default_chosen_creature_type(
                    caster_index, permanent.effective_card
                )
            )
            self.arm_pending_choice(
                "enter_choice", caster_index,
                card_name=permanent.card.name, permanent=permanent,
                needs_color=True, opponents=[], default_seat=None,
                default_color=default_color, needs_creature_type=True,
                default_creature_type=permanent.metadata["chosen_creature_type"],
            )
        if chooses_creature_type_on_enter(text) and not chooses_pair:
            permanent.metadata["chosen_creature_type"] = (
                self._default_chosen_creature_type(
                    caster_index, permanent.effective_card
                )
            )
            self.arm_pending_choice(
                "enter_choice", caster_index,
                card_name=permanent.card.name, permanent=permanent,
                needs_color=False, opponents=[], default_seat=None,
                default_color=None, needs_creature_type=True,
                default_creature_type=permanent.metadata["chosen_creature_type"],
            )

        # "As this enchantment enters, choose **a land type**." (Shimmer.) The
        # fourth quality this one sentence names, and a different catalog from
        # the *basic* pair above: CR 205.3i's land types include Desert and
        # Urza's, which no "basic land type" clause may name. Armed exactly as
        # the creature type is, with the record stamped first so an AI or
        # headless controller never blocks.
        #
        # The static beside it reads the record ("Each land of the chosen type
        # has phasing"), and the record did not exist when the entry
        # recalculation ran — so recompute, the way Illusionary Terrain's pair
        # and Jihad's anthem both do.
        if chooses_land_type_on_enter(text):
            permanent.metadata["chosen_land_type"] = (
                self._default_chosen_land_type(caster_index)
            )
            self._recalculate_lord_buffs()
            self.arm_pending_choice(
                "enter_choice", caster_index,
                card_name=permanent.card.name, permanent=permanent,
                needs_color=False, opponents=[], default_seat=None,
                default_color=None, needs_land_type=True,
                default_land_type=permanent.metadata["chosen_land_type"],
            )

        # "As this enchantment enters, choose **black or red**." (Mangara's
        # Equity) / "…choose **Island or Swamp**." (Roots of Life.) The same
        # two choices the branches above make, with the *sentence* naming what
        # may be chosen instead of a catalog — so it writes the same two
        # records ("chosen_color", "chosen_land_type") and arms the same two
        # prompt shapes, narrowed by an options list.
        #
        # Narrowed rather than a seventh shape, because the offer is the whole
        # of the difference: a picker showing five colours where the card
        # prints two is a strictly better card, and the resolver refusing an
        # unprinted answer is what makes the picker's list true (idiom 9).
        #
        # Asked after the catalog-named readers above, which it does not
        # collide with — "choose a color" and "choose black or red" share no
        # cursor — so the position is documentation rather than precedence.
        # Whole-line rather than the substring probes above, and read through
        # ``expand_card_lines`` for the reason every other reader of a card's
        # lines starts there: the pattern is anchored on the end of its
        # sentence, so what may be chosen cannot be read off a line that says
        # more.
        two_options = next(
            (
                found
                for line in expand_card_lines(permanent.effective_card)
                for found in (choose_one_of_two_on_enter(line, permanent.effective_card.name),)
                if found is not None
            ),
            None,
        )
        if two_options is not None:
            record_key, options = two_options
            default = self._default_entry_choice_option(
                caster_index, record_key, options
            )
            permanent.metadata[record_key] = default
            # A static may read either record ("permanents of the chosen
            # color", "each land of the chosen type"), and the record did not
            # exist when the entry recalculation ran — so recompute, exactly as
            # the colour and land-type branches above do.
            self._recalculate_lord_buffs()
            self.arm_pending_choice(
                "enter_choice", caster_index,
                card_name=permanent.card.name, permanent=permanent,
                needs_color=record_key == CHOSEN_COLOR_KEY,
                opponents=[], default_seat=None,
                default_color=default if record_key == CHOSEN_COLOR_KEY else None,
                needs_land_type=record_key == CHOSEN_LAND_TYPE_KEY,
                default_land_type=(
                    default if record_key == CHOSEN_LAND_TYPE_KEY else None
                ),
                # The list the picker offers and the resolver checks against —
                # one field, read by both, so they cannot come to disagree
                # about what the sentence printed.
                entry_choice_options=list(options),
            )

        # "As this enchantment enters, **you and an opponent each** choose a
        # card name other than a basic land card name." (Null Chamber.) Two
        # names and two choosers, so it is two armings of the one prompt rather
        # than a new kind: what differs from Runed Halo's single choice is who
        # answers and which slot the answer lands in, and both are data.
        #
        # Read *before* Runed Halo's phrase, which is a substring of this one —
        # tried first it would claim this line, record one name and leave the
        # opponent's choice unmade, which is the enchantment doing half of what
        # it prints.
        #
        # Both defaults are stamped first so an AI or headless seat never
        # blocks, exactly as every other arming here does. Each seat's default
        # names something that seat can see and would want gone: the priciest
        # nonland card in an opponent's graveyard, else one of their
        # permanents. Naming nothing would make the enchantment inert, which is
        # legal and is not a choice any player would make (idiom 8).
        if chooses_two_card_names_on_enter(text):
            opponents = [
                i for i, p in enumerate(self.players)
                if i != caster_index and not p.lost
            ]
            # CR 201.2 lets the controller pick which opponent answers; with
            # nobody to ask, the controller's own name is the whole choice.
            opponent_index = opponents[0] if opponents else None
            # The enchantment itself is excluded from both defaults. Naming
            # it is legal (CR 201.2 bounds nothing) and stops nothing that is
            # already on the battlefield, so it is not a choice a player would
            # make — and it is the *first* thing an opponent's scan of the
            # controller's permanents reaches.
            source_name = permanent.card.name
            names = [
                self._default_named_card(caster_index, exclude=source_name),
                (
                    self._default_named_card(opponent_index, exclude=source_name)
                    if opponent_index is not None else ""
                ),
            ]
            permanent.metadata[CHOSEN_CARD_NAMES] = names
            for slot, seat in enumerate([caster_index, opponent_index]):
                if seat is None:
                    continue
                self.arm_pending_choice(
                    "enter_choice", seat,
                    card_name=permanent.card.name, permanent=permanent,
                    needs_color=False, opponents=[], default_seat=None,
                    default_color=None, needs_card_name=True,
                    card_name_slot=slot,
                    choices=self._nameable_cards(seat, exclude=source_name),
                    default_card_name=names[slot],
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
        #
        # "As this creature enters, choose a **nonland** card name." (Meddling
        # Mage.) The same choice under CR 201.4a's bound, and the bound is
        # data: what the reader returns is carried to the prompt, obeyed by the
        # default and enforced on the answer
        # (``_named_card_breaks_printed_bound``). A card's *names* are asked
        # rather than its name (CR 201.4b): a split card is named by one of its
        # halves and bounded by that half's characteristics, so the offer lists
        # "Wax" and "Wane" and never the whole card's joined spelling, which is
        # a name no spell has.
        name_bound = chooses_card_name_on_enter(text)
        if name_bound is not None:
            from ..faces import castable_faces
            from ..search_filters import card_has_type

            excluded_type = name_bound.get("excluded_card_type")
            opponents = [
                i for i, p in enumerate(self.players)
                if i != caster_index and not p.lost
            ]
            visible = [
                card
                for seat in opponents
                for card in reversed(self.players[seat].graveyard)
            ] + [
                perm.card
                for seat in opponents
                for perm in self.controlled_by(seat)
            ]
            seen = [
                named.name
                for card in visible
                for named in castable_faces(card)
                if not (excluded_type and card_has_type(named, excluded_type))
            ]
            permanent.metadata["chosen_card_name"] = seen[0] if seen else ""
            if caster_index not in self.interactive_seats:
                # A chosen name is public (CR 201.4: the player *chooses a
                # card name*, out loud), and for a seat nobody asks the default
                # stamped above is the whole choice — the prompt below is
                # discarded the moment it is armed and says nothing. Without
                # this line a player facing an AI's Meddling Mage learned what
                # it had named by having a cast refused. An interactive seat's
                # answer is logged by the resolver, in these words.
                self.log.append(
                    f"{self.players[caster_index].name} named "
                    f"{permanent.metadata['chosen_card_name'] or 'nothing'} "
                    f"for {permanent.card.name}"
                )
            self.arm_pending_choice(
                "enter_choice", caster_index,
                card_name=permanent.card.name, permanent=permanent,
                needs_card_name=True, choices=sorted(set(seen)),
                default_card_name=permanent.metadata["chosen_card_name"],
                # Absent for Runed Halo, so the prompt that card raises is
                # byte-identical to what it was.
                **(
                    {"excluded_card_type": excluded_type}
                    if excluded_type else {}
                ),
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
            permanent.metadata[LIFE_PAID_AS_ENTERED] = 0
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

        # "As this enchantment enters, sacrifice **all** lands you control."
        # (Overlaid Terrain.) The row above with nothing to choose: CR 614.1c
        # puts it at the same moment, and "all" is the whole set, so it is
        # performed here rather than offered. Drawn from the entering seat's own
        # board through the control seam (CR 701.21a — a player sacrifices only
        # what they control), and never the entering permanent itself, which is
        # not yet on the battlefield as the replacement applies. Each one goes
        # through the one sacrifice transition, so every die / leaves trigger a
        # sacrificed land has is announced.
        for raw_line in entry_lines:
            swept = sacrifice_all_on_enter(raw_line, permanent.effective_card.name)
            if swept is None:
                continue
            doomed = [
                perm for perm in self.controlled_by(caster_index)
                if perm is not permanent
                and subject_matches(self, perm, swept, observer=caster_index)
            ]
            for perm in doomed:
                if self.sacrifice_permanent(perm) is not None:
                    self.log.append(
                        f"{self.players[caster_index].name} sacrificed "
                        f"{perm.card.name} as {permanent.card.name} entered"
                    )
            break

        # "As this enchantment enters, **discard your hand**." (Heightened
        # Awareness.) The row above one zone over: the whole hand, nobody
        # chooses, performed at the entry (CR 614.1c). Each card goes through
        # ``_discard_card`` — the seam the "discard your hand" effect uses — so a
        # discard replacement still applies and every discard watcher sees it.
        for raw_line in entry_lines:
            if not discards_hand_on_enter(raw_line, permanent.effective_card.name):
                continue
            player = self.players[caster_index]
            gone = list(player.hand)
            player.hand = []
            for card in gone:
                self._discard_card(player, card)
            self.log.append(
                f"{player.name} discarded their hand ({len(gone)} card(s)) as "
                f"{permanent.card.name} entered"
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

        # "**If this creature was kicked, it enters with** two +1/+1 counters
        # on it **and with flying**." (Faerie Squadron.) The loop above under
        # CR 702.33d's condition, read off the stamp the resolving spell left
        # on the permanent before it entered (``resolution._resolve_card``) --
        # so a creature put onto the battlefield without being cast, which
        # carries no stamp, enters as the card's printed body. That is the
        # rule: it was not cast, so it was not kicked.
        #
        # What follows "and with" is something the permanent **has** from here
        # on, with no duration (CR 611.2a), so it goes through the two layer-6
        # grant channels with ``duration=None`` -- the value that has always
        # meant "no sweep takes this away". A granted keyword is therefore an
        # ability on the grant channel and not a rewrite of the card: a later
        # effect that takes that word away takes it and leaves the counters.
        #
        # (This said "Humility takes Kavu Titan's trample" until it was driven:
        # it does not. The *blanket* removal is struck before every grant
        # whatever their timestamps -- ``Permanent.effective_card`` says why
        # that is right for a grant made after it -- so a Humility that
        # arrives *later* leaves a kicked creature its keyword and its quoted
        # triggered ability, where CR 613.7 would take both. The activation
        # gate does refuse the quoted activated one. Measured at Apocalypse
        # and left: it is every grant channel against four cards, not this
        # loop.)
        #
        # "If this creature was kicked **with its {1}{U} kicker**, …" (the five
        # Volvers, CR 702.33f). The same loop asked of one kicker cost rather
        # than of any: the entry applies only when the key the sentence names
        # is among those the cast recorded paying (``KICKED_WITH``, stamped
        # beside the flag). A card prints one such line per kicker, so a Volver
        # kicked with both passes this loop twice and enters with three
        # counters and both abilities -- two entry replacements, not one with
        # a choice in it.
        if permanent.metadata.get(KICKED):
            paid_kickers = tuple(permanent.metadata.get(KICKED_WITH) or ())
            for raw_line in entry_lines:
                entry = kicked_entry(raw_line, permanent.effective_card.name)
                if entry is None:
                    continue
                if entry["kicker"] is not None and entry["kicker"] not in paid_kickers:
                    continue
                count, kind = entry["counters"]
                # "…with X +1/+1 counters on it, where X is the discarded
                # card's mana value" (Dralnu's Pet): the count is not printed,
                # it is the number the resolving spell stamped beside the
                # kicked stamp. Absent — nothing discarded, or not exactly one
                # card — it is 0, which places nothing and leaves the keyword.
                counted_from = entry.get("counters_from")
                if counted_from is not None:
                    count = max(0, int(permanent.metadata.get(counted_from, 0) or 0))
                if count <= 0:
                    pass
                elif kind == "+1/+1":
                    self.place_plus1_counters(permanent, count)
                elif kind == "+1/+0":
                    permanent.power_bonus += count
                    permanent.metadata["plus_1_0_counters"] = count
                else:
                    permanent.toughness_bonus += count
                    permanent.metadata["plus_0_1_counters"] = count
                for keyword in entry["keywords"]:
                    grant_keyword(permanent, keyword)
                for granted_line in entry["ability_lines"]:
                    grant_ability_line(permanent, granted_line)

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

        # "…enters with a <kind> counter on it **for each <noun phrase>**"
        # (Zombie Mob). The third place the number can come from, beside the
        # printed one and the announced X: the board, counted as the permanent
        # enters (CR 608.2). ``evaluate_count`` is the same evaluator the
        # printed sentence "gets +1/+1 for each creature card in your
        # graveyard" already reaches, so the two count the same set.
        #
        # Counted against the *controller's* zones, which is what "your" names
        # for a permanent entering under a seat, and taken before the counters
        # go on — the permanent itself is not in a graveyard, so nothing here
        # can count itself.
        for raw_line in entry_lines:
            counted = enters_with_counted_pt_counters(
                raw_line, permanent.effective_card.name
            )
            if counted is None:
                continue
            kind, spec = counted
            from ..handlers._amounts import evaluate_count

            seat = self.controller_index_of(permanent)
            owner = self.players[seat if seat is not None else 0]
            amount = max(0, evaluate_count(self, owner, spec, source=permanent))
            if amount <= 0:
                continue
            if kind == "+1/+1":
                # Through the seam, for the printed-count loop's reason: an
                # entry counter is a counter placement and CR 614.1c lets a
                # replacement modify it.
                self.place_plus1_counters(permanent, amount)
            elif kind == "+1/+0":
                permanent.power_bonus += amount
                permanent.metadata["plus_1_0_counters"] = amount
            else:
                permanent.toughness_bonus += amount
                permanent.metadata["plus_0_1_counters"] = amount

        # The copy-as-enter choice (Clone, Copy Artifact) used to be made here,
        # *after* every other entry replacement above had read the printed
        # card. It is `_enter_as_a_copy` now, called first — see there.

        # "You have no maximum hand size." used to be stamped here too, onto
        # `PlayerState.has_no_max_hand_size`, and nothing ever cleared it — so a
        # destroyed Library of Leng left its controller with no maximum hand
        # size for the rest of the game (CR 611.3a ends a static ability with
        # its source). It is derived from the board on every read now, by
        # `engine/hand_size.maximum_hand_size`, which is the same reader Cursed
        # Rack's limit and Anvil of Bogardan's all-players spelling go through.
        # The field survives for an effect that really does set the permission
        # on a player with no permanent behind it.

        # The two mana-spending permissions used to be stamped here and never
        # cleared, so a destroyed Sunglasses of Urza or Chromatic Orrery left
        # its controller spending mana its way for the rest of the game
        # (CR 611.3a ends a static ability with its source). They are derived
        # from the board on every continuous refresh now --
        # `_refresh_mana_spending`, reading `engine/mana_spending.py` -- which
        # is also what let Celestial Dawn's narrowed form be expressed at all.

        if LOSE_LIFE_EQUAL_TO_TOTAL_ON_ENTER in text:
            controller = self.players[caster_index]
            life_loss = controller.life
            controller.life -= life_loss
            self.log.append(f"{permanent.card.name}: {controller.name} lost {life_loss} life on entry")

    def _enter_as_a_copy(self, permanent: Permanent) -> None:
        """"You may have this <type> enter as a copy of any <type> on the
        battlefield" (Clone, Vesuvan Doppelganger, Copy Artifact) — CR 707.5's
        "as a copy", a CR 614.1c replacement, performed as the first part of
        :meth:`_perform_entry_state` (CR 614.12).

        Read off ``effective_card``, so a token copy of a Clone that copies
        nothing offers the same choice the Clone would (CR 707.5: the token *is*
        that Clone as it enters).

        The chosen permanent is asked through the layer accessors
        (``has_type``) rather than its printed primary type, which answers
        "creature" for an artifact creature: Copy Artifact aimed at an
        Ornithopter refused the choice and then found no "artifact" to fall
        back to, and entered as a plain blue enchantment.
        """
        program = compile_card_oracle(permanent.effective_card)
        text = program.normalized_text
        # copy-as-enter creature
        if any(COPY_CREATURE_ON_ENTER == line for line in program.static_lines) or COPY_CREATURE_ON_ENTER in text:
            source = self._resolve_copy_target(permanent, "creature")
            if source is None:
                source = next(
                    (
                        perm
                        for perm in self.all_permanents()
                        if perm is not permanent and perm.has_type("creature")
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
                        if perm is not permanent and perm.has_type("artifact")
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

    def _apply_copy(
        self,
        permanent: Permanent,
        source: Permanent,
        *,
        grants_text: tuple[str, ...] = (),
    ) -> None:
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
        # *grants_text* is CR 707.9a's "except it has this ability" where the
        # clause is on the sentence being resolved rather than on the copier's
        # standing text (Unstable Shapeshifter). The exception table below reads
        # the copier's own printed clauses — Vesuvan Doppelganger's colour, Copy
        # Artifact's added type — and cannot see a clause the resolution is
        # carrying, which is why the caller hands it over.
        exceptions = copies.copy_exceptions(
            compile_card_oracle(permanent.card).normalized_text
        )
        copies.become_copy(
            permanent,
            source,
            grants_text=grants_text,
            **exceptions,
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
        # Recorded **before** entry, because CR 707.5 says so in as many words:
        # an object that enters "that's a copy" of another "becomes a copy as it
        # enters the battlefield. It doesn't enter the battlefield, and then
        # become a copy". The contribution keys on the token object, not on its
        # id, so it needs nothing the entry gives it. Recorded after, the token
        # was announced to every "whenever a creature enters" watcher as a
        # typeless "Token" — a Soul Warden saw no creature, and the entry seam
        # froze a power of 0 — and only then turned into what it copies.
        copies.become_copy(token, source)
        self._put_permanent_onto_battlefield(controller_index, token, None)
        self._recalculate_lord_buffs()
        return token

    def _resolve_copy_target(self, permanent: Permanent, primary_type: str) -> Permanent | None:
        """Return the player-chosen permanent for a "copy as it enters" effect.

        The chosen target is recorded as ``copy_target = (player_index,
        perm_index, permanent_id)`` when the spell is cast. Returns None if no
        legal choice was recorded so the caller can fall back to an arbitrary
        legal permanent.

        **By id when there is one.** The choice is made at cast and spent at
        resolution, and anything leaving the battlefield in between renumbers
        every later slot — so the index alone made a Clone aimed at a Craw Wurm
        copy whatever creature slid into the Wurm's slot after a Grizzly Bears
        died in response. The id is CR 400.7's identity; a chosen creature that
        has left resolves to nothing rather than to its neighbour. A two-entry
        record (no id announced) keeps the index it always had.
        """
        copy_target = permanent.metadata.pop("copy_target", None)
        if copy_target is None:
            return None
        player_index, perm_index = copy_target[0], copy_target[1]
        chosen_id = copy_target[2] if len(copy_target) > 2 else None
        if isinstance(chosen_id, int):
            candidate = self.permanent_by_id(chosen_id)
            if candidate is None:
                return None
        else:
            if not isinstance(player_index, int) or not isinstance(perm_index, int):
                return None
            if not (0 <= player_index < len(self.players)):
                return None
            candidate = self.permanent_at(player_index, perm_index)
            if candidate is None:
                return None
        if candidate is permanent or not candidate.has_type(primary_type):
            return None
        return candidate

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
        from ..handlers._filters import permanent_effective_colors

        return permanent_effective_colors(permanent)
