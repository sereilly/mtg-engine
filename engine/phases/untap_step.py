from __future__ import annotations

"""Untap step (CR 502).

The active player untaps their permanents as a turn-based action. No player
receives priority during this step in this engine (CR 502.4). Untap
constraints (skip entirely, per-type count limits, power-based blocks) are
derived from oracle text by engine/untap_restrictions.py — this module only
aggregates and enforces them, so new restriction cards never touch it.
"""

from ..auras import aura_restriction_active
from ..replacements import apply_replacements
from ..subject_filters import subject_matches
from ..handlers.board_misc import LAND_TYPE_UNTIL_UNTAP
from ..handlers.tapping import (SKIP_NEXT_UNTAP_SEAT,
                                UNTAP_BLOCKED_WHILE_COUNTERS_KEY,
                                UNTAP_LOCK_WHILE_PRESENT_KEY,
                                UNTAP_LOCK_WHILE_TAPPED_KEY)
from ..land_types import end_land_type_changes_from
from ..control import LINKED_CONTROL_CONDITIONS
from ..named_counters import counters_on
from ..turn_state import record_turn_start_states
from ..turn_state import attacked_during_seats_last_turn
from ..handlers._common import CHOSEN_CARD_TYPE, chosen_card_type_filter
from ..untap_restrictions import (
    LIMITED_SCOPES,
    SELF_DOESNT_UNTAP_PHRASE,
    SELF_MAY_KEEP_TAPPED_PHRASE,
    TYPE_CHOICE_SCOPE,
    permanent_in_limited_scope,
    self_untap_attacked_last_turn,
    self_untap_counter_condition,
    self_untap_opponent_board_condition,
    self_untap_line,
    untap_restriction_for,
)


#: The scopes a "can't untap more than N" restriction may name. The untap step
#: asks each one separately, so a card printed with any of them needs no code
#: here — only a row in engine/untap_restrictions.py. Imported from that module
#: rather than spelled again: the row that produces the scope and the step that
#: enforces it disagreeing is a cap read off a card and then applied to nothing.
_LIMITED_TYPES = LIMITED_SCOPES


def _holds_a_live_untap_lock(game, permanent) -> bool:
    """Whether *permanent* is holding another one down by staying tapped.

    Phyrexian Gremlins and Giant Oyster both print "You may choose not to untap
    this creature during your untap step" above an ability whose whole effect
    lasts only "for as long as this creature remains tapped". A seat that
    untaps releases what it is holding — legal, and never what the card was
    activated for — so the same default the linked *steal* already has applies
    here: while the lock is live, AI and headless play keep the permanent
    tapped. A human's explicit choice still wins, through ``keep_tapped_indices``
    at the call site.

    Derived from the record the lock itself writes rather than from a list of
    cards, and re-checked against the battlefield: an id whose permanent has
    gone is a lock that ended with it (CR 400.7), and holding a creature back
    for it would be paying a price for nothing.
    """
    held = permanent.metadata.get(UNTAP_LOCK_WHILE_TAPPED_KEY)
    return held is not None and game.permanent_by_id(held) is not None


def _skip_next_untap_names_this_step(permanent, seat: int) -> bool:
    """Whether a permanent's ``skip_next_untap`` marker is about *seat*'s step.

    Two printed durations share the one marker. "…during **its controller's**
    next untap step" (Frost Breath) records no seat, because the step only ever
    reaches permanents the active player controls and so the controller's step
    is the one that finds it. "…during **your** next untap step" (Deep Spawn,
    Homarid Warrior — CR 701.43a) records the seat the effect's controller had,
    and that marker must sit out every other player's untap step rather than be
    spent by it: a creature that changed hands would otherwise miss the step the
    card actually named and untap on schedule under its new controller.

    Asked at both ends of this step — the skip and the expiry — so an untap that
    the marker does not block cannot silently consume it.
    """
    named = permanent.metadata.get(SKIP_NEXT_UNTAP_SEAT)
    return named is None or named == seat


def _self_untap_blocked(game, permanent, seat: int) -> bool:
    """Whether *permanent*'s own text keeps it tapped **this** untap step.

    The loose substring probe this replaced was right about every unconditional
    printing of the phrase and wrong about a conditional one: "doesn't untap
    during your untap step **if it has a glyph counter on it**" (granted by
    Glyph of Delusion) contains the phrase, so the probe kept the creature
    tapped for the rest of the game while the card removes one counter per
    upkeep and is supposed to release it.

    So the lines are read one at a time. A line stating a counter condition
    applies only while the counter is there; any other line carrying the phrase
    keeps its old, unconditional reading - the probe's looseness is deliberate
    (see ``engine/untap_restrictions.py``), and narrowing it here would be a
    second, stricter reader of text this module does not own.

    ``effective_card`` throughout, so a CR 613 layer-3 text change and a granted
    line are both read; the condition is asked of the permanent, which is where
    a CR 122.1 counter lives.

    *seat* is whose untap step this is — the seat "**your** untap step" and
    "your last turn" name — so the attack condition is ordinal arithmetic
    against that seat's own turn counter rather than against the game's.
    """
    blocked = False
    for line in (permanent.effective_card.oracle_text or "").splitlines():
        if SELF_DOESNT_UNTAP_PHRASE not in line.lower():
            continue
        name = permanent.effective_card.name
        counter = self_untap_counter_condition(line, name)
        if counter is not None:
            if counters_on(permanent, counter) > 0:
                blocked = True
            continue
        # "…if it attacked during your last turn" (Goblin Rock Sled). The
        # condition is re-asked every untap step off the permanent's own attack
        # record, so a Sled that sat out untaps normally — where the loose
        # substring reading below would have frozen it for the rest of the game.
        if self_untap_attacked_last_turn(line, name):
            if attacked_during_seats_last_turn(game, permanent, seat):
                blocked = True
            continue
        # "…if an opponent controls two or more creatures" (Walking Dream).
        # A fact about somebody else's board, re-asked every untap step for the
        # reason the two conditions above are: the loose reading below would
        # freeze the creature the moment the line was printed and never let go.
        #
        # "An opponent" is *any one* of them (CR 102.1), so each seat's own
        # board is counted separately — summing them would freeze the Dream on
        # a table where two opponents hold one creature each, which is a board
        # no opponent controls.
        board = self_untap_opponent_board_condition(line, name)
        if board is not None:
            threshold, described = board
            controller = game.controller_index_of(permanent)
            for other in range(len(game.players)):
                if other == controller:
                    continue
                matching = sum(
                    1
                    for perm in game.controlled_by(other)
                    if subject_matches(
                        game, perm, described, observer=other, source=permanent
                    )
                )
                if matching >= threshold:
                    blocked = True
                    break
            continue
        return True
    return blocked


#: Which untap step a source last asked its type choice for, as ``(turn,
#: seat)``, recorded on the source permanent.
#:
#: The answer itself goes in ``CHOSEN_CARD_TYPE`` — the record every other
#: "of the chosen type" reader already asks — but that key alone cannot say
#: *when* it was chosen, and this choice is re-made every untap step by whoever
#: is untapping. Without the stamp the arming would either re-ask (overwriting a
#: human's answer with the default the moment the step resumed) or never re-ask
#: (freezing turn one's answer into the rest of the game).
UNTAP_TYPE_CHOICE_STAMP = "untap_type_choice_stamp"


def _most_untappable_type(game, seat: int, options) -> str:
    """The option that would untap the most of *seat*'s tapped permanents.

    A real answer rather than the first item, which is what a chooser facing
    this every untap step would actually name. Ties go to the printed order, so
    the default is deterministic and a seed still reproduces a run — and an
    empty board takes the first option, because every count is zero and the
    sentence still demands a word.

    Counted through the filter the prompt offers and the step then spends
    (idiom 9), so the number the default is picked on is the number the step
    will really untap.
    """
    best, best_count = str(options[0]), -1
    for option in options:
        described = chosen_card_type_filter(option)
        if described is None:
            continue
        count = sum(
            1
            for perm in game.controlled_by(seat)
            if perm.tapped and subject_matches(game, perm, described, observer=seat)
        )
        if count > best_count:
            best, best_count = str(option), count
    return best


class UntapStepMixin:
    def _untap_constraints(self) -> dict[str, object]:
        """Aggregate every active untap restriction on any battlefield into
        effective limits for the current untap step."""
        skip_all_source: str | None = None
        # "Players can't untap more than one <type> during their untap steps."
        # One entry per printed type rather than a counter per type in the
        # source: Winter Orb says land, Smoke says creature, Damping Field says
        # artifact, and the only thing that differs between them is the word.
        # It was two named counters, which is why adding the third meant a
        # third of everything down to the browser.
        limits: dict[str, int] = {}
        # Every "<noun phrase> don't untap during their controllers' untap
        # steps" in force, as ``(filter payload, the source's controller)``.
        # One list where there were three aggregates -- a power cap, a colour
        # set and a supertype set, one per card that had been printed. The seat
        # travels with the filter because CR 109.5 makes "you control" inside a
        # noun phrase relative to the *source's* controller, not to whoever is
        # untapping.
        # …and the *source permanent* beside the seat, because a narrowing can
        # name something recorded on the source rather than printed in the
        # sentence: "Creatures **of the chosen type**" (An-Zerrin Ruins) is
        # CR 614.1c's entry choice, and ``subject_matches`` resolves it out of
        # the source's own record. Dropped, the key survives into the pure
        # matcher, which refuses every permanent — a restriction that quietly
        # blocks nothing.
        blocked: list[tuple[dict, int | None, object]] = []
        # "…each player chooses artifact, creature, or land during their untap
        # step. That player can untap only permanents of the chosen type this
        # step." (Storage Matrix.) The third family, as ``(source, options)``.
        # The *answer* is not here: it is recorded on the source permanent and
        # re-made every untap step, so what this aggregate can say is only which
        # sources are asking and what each offers.
        type_choices: list[tuple[object, tuple[str, ...]]] = []
        for perm in self.all_permanents():
            # effective_card, so a CR 613 layer-3 text change (Sleight of Mind
            # rewriting the colour word) is applied before the restriction is
            # read — the table itself never learns text can change.
            restriction = untap_restriction_for(perm.effective_card.oracle_text)
            if restriction is None:
                continue
            if restriction.only_while_source_untapped and perm.tapped:
                continue
            if restriction.scope == "all":
                if restriction.limit == 0:
                    skip_all_source = perm.card.name
            elif restriction.scope in _LIMITED_TYPES:
                if restriction.limit is not None:
                    limits[restriction.scope] = min(
                        limits.get(restriction.scope, restriction.limit),
                        restriction.limit,
                    )
            elif restriction.scope == TYPE_CHOICE_SCOPE:
                if restriction.chosen_type_options:
                    type_choices.append((perm, restriction.chosen_type_options))
            elif restriction.blocked is not None:
                blocked.append(
                    (restriction.blocked, self.controller_index_of(perm), perm)
                )
        return {
            "skip_all_source": skip_all_source,
            "limits": limits,
            "blocked": blocked,
            "type_choices": type_choices,
        }

    # -- The type the untapping player names (CR 502.3) ---------------------

    def arm_untap_type_choices(self, player_index: int) -> bool:
        """Ask *player_index* for each type choice their untap step owes.

        CR 502.3 makes untapping a turn-based action, and this is a decision
        *inside* it: the active player names a type before determining which
        permanents untap, so the answer has to exist before the step does
        anything. Returns whether an interactive seat now owes one — the web
        layer stops the beginning phase on a True and picks it up when the
        answer arrives (``web/turn_steps.py``).

        Three things make this safe to call from either end. The **default is
        stamped first**, so a headless or AI seat is never blocked and the step
        always has a word to spend — ``card_type_choice``'s own arrangement, and
        for its reason. The **stamp** makes it idempotent for one step, so
        ``resolve_untap_step`` may call it again on the way through without
        overwriting a human's answer. And a source that is *tapped* asks
        nothing, because Storage Matrix's whole sentence is "as long as this
        artifact is untapped" — a turn where it is tapped owes no choice at all.

        This is the first prompt in the engine armed by a **turn-based action**
        rather than by a resolution, and the registry carries it unchanged:
        ``arm_pending_choice`` stamps ``_stack_item`` only while something is
        resolving, so this one holds priority and holds no stack object — the
        shape ``land_type_choice`` already documents for a prompt armed by a
        permanent that is already on the battlefield.
        """
        asked = False
        for source, options in self._untap_constraints()["type_choices"]:
            stamp = (self.turn, player_index)
            if source.metadata.get(UNTAP_TYPE_CHOICE_STAMP) == stamp:
                continue
            default = _most_untappable_type(self, player_index, options)
            source.metadata[CHOSEN_CARD_TYPE] = default
            source.metadata[UNTAP_TYPE_CHOICE_STAMP] = stamp
            choice = self.arm_pending_choice(
                "card_type_choice", player_index,
                card_name=source.card.name, permanent=source,
                options=list(options), default_card_type=default,
                # What the answer does, for the prompt. Not a card's sentence
                # but the *family's*, so any card printing this pair gets it —
                # which is what lets it travel from a text-keyed table at all.
                detail="you can untap only permanents of the chosen type this step.",
                # Which prompt this is, for the untap step's *other* channel —
                # see `get_untap_land_selection_options`. Private, so it never
                # reaches a client.
                _untap_step=True,
            )
            self.log.append(
                f"{source.card.name}: {self.players[player_index].name} chooses a type "
                f"({', '.join(options)})"
            )
            asked = asked or choice is not None
        return asked

    def untap_type_choice_owed(self, player_index: int) -> bool:
        """Whether *player_index* still owes their untap step's type choice."""
        return any(
            choice.kind == "card_type_choice"
            and choice.player_index == player_index
            and choice.data.get("_untap_step")
            for choice in self.pending_choices
        )

    def _chosen_untap_type_filters(self, constraints: dict) -> list[dict]:
        """The filter payload each live type choice has been answered with.

        A source with **no** recorded answer contributes nothing, and that
        direction is the opposite of the block family's on purpose: this
        sentence says a player can untap *only* permanents of the chosen type,
        so a dropped narrowing untaps the whole board where a dropped block
        would untap nothing. Neither is reachable while
        :meth:`arm_untap_type_choices` stamps a default before it asks; the
        fall-through is stated rather than left to whichever way the payload
        happened to fail.
        """
        filters: list[dict] = []
        for source, _options in constraints["type_choices"]:
            word = source.metadata.get(CHOSEN_CARD_TYPE)
            described = chosen_card_type_filter(word) if word else None
            if described is not None:
                filters.append(described)
        return filters

    def get_untap_land_selection_options(self, player_index: int) -> dict[str, object] | None:
        """Untap-step selection constraints the controller must resolve: Winter Orb
        limits untapping to one *land*, Smoke to one *creature*. Returns combined
        candidate battlefield indices and the total number that may be untapped
        among the constrained types, or None if nothing is constrained."""
        # Nothing to offer while the type choice is still owed: under Storage
        # Matrix *and* Winter Orb, which permanents are even eligible depends on
        # the word that has not been said yet, so the count prompt is computed
        # after it. Here rather than in the web layer because the same answer is
        # read by the action gate, the state payload and the deferral — and a
        # gate that said "select untap lands before other actions" while the
        # seat owed a type choice would refuse the only action that could
        # answer it.
        if self.untap_type_choice_owed(player_index):
            return None

        player = self.players[player_index]
        constraints = self._untap_constraints()

        if constraints["skip_all_source"] is not None:
            return None

        limits = constraints["limits"]

        # A type is only *constrained* when the player has more tapped
        # permanents of it than the limit allows — otherwise there is nothing
        # to choose between and no prompt to raise.
        binding: dict[str, int] = {}
        candidate_indices: list[int] = []
        for card_type, limit in sorted(limits.items()):
            candidates = self._tapped_indices_of_type(player, card_type)
            if len(candidates) <= limit:
                continue
            binding[card_type] = limit
            candidate_indices += candidates
        if not binding:
            return None

        return {
            "max_count": sum(binding.values()),
            "candidate_indices": sorted(candidate_indices),
            "limits": binding,
        }

    @staticmethod
    def _tapped_indices_of_type(player, card_type: str) -> list[int]:
        """Battlefield positions of *player*'s tapped permanents of *card_type*.

        ``has_type``, not the printed line's first word: an Ornithopter is an
        artifact *and* a creature, so Damping Field constrains it and so does
        Smoke — and with both on the battlefield it really is constrained
        twice, which is what CR 613 layer 4 makes true of it. Reading
        ``primary_type`` would have made Damping Field ignore every artifact
        creature in Antiquities, which is most of them.
        """
        return [
            idx for idx, perm in enumerate(player.battlefield)
            if perm.tapped and permanent_in_limited_scope(perm, card_type)
        ]

    def get_optional_untap_permanents(self, player_index: int) -> list[dict]:
        """Tapped permanents whose controller may choose not to untap them
        (Old Man of the Sea: "You may choose not to untap this creature during
        your untap step"). The web layer prompts a human with these; the
        keep-tapped choice is passed back via resolve_untap_step's
        ``keep_tapped_indices``."""
        player = self.players[player_index]
        return [
            {"index": idx, "name": permanent.card.name}
            for idx, permanent in enumerate(player.battlefield)
            if permanent.tapped
            # Anchored per line through `self_untap_line`, not a substring over
            # the whole text: the probe below still reads the loose form for the
            # keep-tapped decision itself, but what the *prompt offers* has to be
            # the same set the support gate admits.
            and any(
                self_untap_line(line, permanent.effective_card.name)
                == "may_keep_tapped"
                for line in (permanent.effective_card.oracle_text or "").splitlines()
            )
        ]

    def resolve_untap_step(
        self,
        player_index: int,
        selected_land_indices: list[int] | None = None,
        selected_creature_indices: list[int] | None = None,
        keep_tapped_indices: list[int] | None = None,
        selected_indices_by_type: dict[str, list[int]] | None = None,
    ) -> int:
        """*selected_indices_by_type* is the general form: one list of chosen
        battlefield positions per constrained card type. The two named
        parameters beside it are the shape it grew out of and are folded into
        it here — kept because a caller naming lands or creatures reads better
        than one building a dict, and because they are what the existing tests
        say."""
        phase = "beginning"
        step = "untap"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        player = self.players[player_index]
        # CR 502.3's "the active player determines which permanents they control
        # will untap" — where a card makes that determination a *named type*,
        # the naming happens here, before anything is untapped. Idempotent for
        # one step, so the web layer's own call (which is what lets a human be
        # asked at all) is not undone by this one; for every other caller this
        # is where the default is stamped, which is why a headless run and the
        # AI simulator need no untap-step code of their own.
        self.arm_untap_type_choices(player_index)
        constraints = self._untap_constraints()
        # CR 702.26a's phasing event: before the active player untaps anything,
        # this player's phased-in permanents *with phasing* phase out and their
        # phased-out ones phase in, simultaneously.
        #
        # Guarded by the skip because CR 702.26m says so — "if an effect causes
        # a player to skip their untap step, the phasing event simply doesn't
        # occur that turn" — which is why the constraints are read one line
        # above rather than below the phase-in this replaced. Reading them first
        # also decides the one ordering question the rule leaves open: a Stasis
        # that phases in during this event does not retroactively skip the step
        # it arrived in.
        if constraints["skip_all_source"] is None:
            self.resolve_phasing_for(player_index)
        self._advance_summoning_sickness(player_index)
        # Record untapped lands at the beginning of the turn — i.e. *before* the
        # untap step untaps anything (Power Surge: X = "the number of untapped lands
        # they controlled at the beginning of this turn"). Lands tapped going into
        # the turn don't count, so tapping out before your turn avoids the damage.
        # What every permanent's state was as the turn began, before this step
        # changes any of it — "if this creature started the turn untapped"
        # (Rasputin Dreamweaver) reads it at the upkeep, by which time the board
        # no longer knows. Over every battlefield, not the active player's: the
        # turn began for every permanent there is.
        record_turn_start_states(self.all_permanents(), self.turn)
        self.untapped_lands_at_turn_start[player_index] = sum(
            1 for perm in self.controlled_by(player)
            if perm.card.primary_type == "land" and not perm.tapped
        )
        # Island Sanctuary protection lasts until the player's next turn begins
        player.island_sanctuary_protected = False

        if constraints["skip_all_source"] is not None:
            self.log.append(f"{player.name} skipped untap due to {constraints['skip_all_source']}")
            return 0

        limits: dict[str, int] = dict(constraints["limits"])
        blocked = list(constraints["blocked"])
        chosen_types = self._chosen_untap_type_filters(constraints)

        # The controller chooses which of the constrained permanents to untap
        # (CR 502 with a "can't untap more than N" restriction): Winter Orb
        # picks a land, Smoke a creature, Damping Field an artifact. Absent a
        # choice — AI or headless play — the loop below takes the first
        # eligible ones up to the cap.
        chosen: dict[str, list[int]] = dict(selected_indices_by_type or {})
        if selected_land_indices is not None:
            chosen.setdefault("land", list(selected_land_indices))
        if selected_creature_indices is not None:
            chosen.setdefault("creature", list(selected_creature_indices))

        selected: dict[str, set[int]] = {}
        for card_type, indices in chosen.items():
            picked: set[int] = set()
            for idx in indices:
                if idx < 0 or idx >= len(player.battlefield):
                    raise ValueError(f"selected {card_type} index out of range")
                permanent = player.battlefield[idx]
                # Through the scope predicate, which is also what
                # `_tapped_indices_of_type` offered the caller — and which
                # answers CR 110.1's "permanent" (Static Orb), a word no type
                # line carries. `primary_type` was the third reader of this
                # question and the narrowest of the three.
                if not permanent_in_limited_scope(permanent, card_type):
                    raise ValueError(f"selected permanent is not a {card_type}")
                if not permanent.tapped:
                    continue
                picked.add(idx)
            limit = limits.get(card_type)
            if limit is not None and len(picked) > limit:
                raise ValueError(f"cannot untap more than {limit} {card_type}(s)")
            selected[card_type] = picked

        untapped = 0
        untapped_by_type: dict[str, int] = {}
        # A **snapshot**, because one of the replacements below takes the
        # permanent off the battlefield: Undiscovered Paradise goes to its
        # owner's hand instead of untapping, and a live list would renumber
        # every later slot under the loop — so the permanent that slid into the
        # gap would be skipped and `idx` would stop naming the permanent the
        # caller's `keep_tapped_indices` and per-type selections were built
        # against. The indices stay the ones the caller was offered, and the
        # liveness check below is what keeps a departed permanent out.
        for idx, permanent in enumerate(list(player.battlefield)):
            if not permanent.tapped or not self.is_on_battlefield(permanent):
                continue

            # Permanents that read "doesn't untap during your untap step" (e.g.
            # Time Vault, Basalt Monolith) stay tapped (Rule 502.4, 702 self-text).
            if _self_untap_blocked(self, permanent, player_index):
                continue

            # "…don't untap during their controller's next untap step" (Frost
            # Breath): a marker left by a resolved spell rather than a restriction
            # read off this permanent's own text, which is why it is here and not
            # in engine/untap_restrictions.py. CR 502.3 — "effects can keep one or
            # more of a player's permanents from untapping". Cleared below, for
            # this step whether or not it kept anything tapped.
            if permanent.metadata.get("skip_next_untap") and (
                _skip_next_untap_names_this_step(permanent, player_index)
            ):
                continue

            # "…doesn't untap during its controller's untap step **for as
            # long as it has a paralyzation counter on it**." (Dread Wight.)
            # The condition is a fact about this permanent, so the record
            # travels with it — and it is the counter's *name* rather than a
            # flag, because the restriction has no end date (CR 611.2a) and
            # lapses of itself the moment the last such counter comes off.
            # Nothing clears it; this read is the whole enforcement.
            if any(
                counters_on(permanent, str(counter)) > 0
                for counter in (
                    permanent.metadata.get(UNTAP_BLOCKED_WHILE_COUNTERS_KEY) or ()
                )
            ):
                continue

            # "…doesn't untap during its controller's untap step for as long as
            # this creature remains tapped." (Phyrexian Gremlins.) Read off the
            # *source's* record rather than a flag on this permanent, so the
            # restriction ends the moment the source untaps or leaves — there
            # is nothing here to clear, which is what makes a condition-ended
            # duration expressible at all.
            # "…for as long as this creature remains **on the battlefield**."
            # (Somnophore.) The same record on the same holder under its own
            # key, and the *only* difference is the question asked of the
            # holder: this one is not about whether it is tapped, so a
            # Somnophore that taps to attack keeps its creature down. Read in
            # one pass with its sibling because both are answered by walking
            # the same board.
            if any(
                (
                    holder.tapped
                    and holder.metadata.get(UNTAP_LOCK_WHILE_TAPPED_KEY)
                    == permanent.permanent_id
                )
                or holder.metadata.get(UNTAP_LOCK_WHILE_PRESENT_KEY)
                == permanent.permanent_id
                for holder in self.all_permanents()
            ):
                continue

            # Old Man of the Sea: "You may choose not to untap this creature
            # during your untap step." A human's explicit keep-tapped choice is
            # honored; AI/headless play keeps it tapped while an effect that
            # ends when it untaps is still live.
            if SELF_MAY_KEEP_TAPPED_PHRASE in permanent.effective_card.oracle_text.lower():
                if keep_tapped_indices is not None:
                    if idx in keep_tapped_indices:
                        continue
                elif (
                    permanent.metadata.get("stolen_while_tapped_and_weaker")
                    # Willow Satyr / Rubinia Soulsinger: a monitored linked
                    # steal whose conditions include staying tapped
                    # (engine/control.LINKED_CONTROL_CONDITIONS) — untapping
                    # would end the control effect, so AI/headless play keeps
                    # the permanent tapped while a steal is live.
                    or "source_remains_tapped"
                    in (permanent.metadata.get(LINKED_CONTROL_CONDITIONS) or ())
                ) and self.permanents_controlled_via(permanent):
                    continue
                elif _holds_a_live_untap_lock(self, permanent):
                    continue

            # "<noun phrase> don't untap during their controllers' untap
            # steps." Meekstone's power cap, Magnetic Mountain's colour, Arena
            # of the Ancients' supertype, Blizzard's flying and Curse of Marit
            # Lage's Islands are one sentence with the noun changed, so they are
            # one test — asked through `subject_matches`, which is what makes
            # every narrowing computed (CR 613: an animated land is a creature,
            # a text-changed colour word is the new colour).
            #
            # Outside the creature branch below, because the noun need not be a
            # creature at all: keying the whole family to `primary_type ==
            # "creature"` is what the three fields it replaced assumed, and
            # Curse of Marit Lage names Islands.
            if any(
                subject_matches(
                    self, permanent, described, observer=seat, source=source
                )
                for described, seat, source in blocked
            ):
                continue

            # "That player can untap only permanents of the chosen type this
            # step." (Storage Matrix.) The inverse of the block above — a
            # permanent that does **not** answer to the named type stays tapped
            # — and every live source narrows independently, so two Matrices
            # answered differently leave the intersection, which is what "only"
            # says twice. No ``source``: the word has already been resolved into
            # an ordinary type filter by `_chosen_untap_type_filters`, so this
            # is the same pure question the block family asks.
            if any(
                not subject_matches(
                    self, permanent, described, observer=player_index
                )
                for described in chosen_types
            ):
                continue

            if permanent.card.primary_type == "creature":
                if aura_restriction_active(
                    permanent, "doesnt_untap", game=self, seat=player_index
                ):
                    continue

            # The per-type cap and the controller's choice within it, asked the
            # same way for every constrained type. This was two copies keyed on
            # "creature" and "land", which is why Damping Field's artifact
            # needed a third of everything.
            # Every constrained type this permanent answers to, asked through
            # the layers for the reason `_tapped_indices_of_type` gives — an
            # artifact creature is under both Damping Field's limit and
            # Smoke's, and each has to see it.
            applicable = [
                t for t in limits if permanent_in_limited_scope(permanent, t)
            ]
            if any(
                (selected.get(t) is not None and idx not in selected[t])
                or untapped_by_type.get(t, 0) >= limits[t]
                for t in applicable
            ):
                continue
            for card_type in applicable:
                untapped_by_type[card_type] = untapped_by_type.get(card_type, 0) + 1

            # CR 614: "If a permanent with a wind counter on it **would
            # untap** during its controller's untap step, remove all wind
            # counters from it instead." (Freyalise's Winds.) The last gate,
            # and a replacement rather than one more skip condition above:
            # every test before this one says the permanent does not untap and
            # leaves it at that, while this one *does something else instead*.
            #
            # No `restart` thunk: the untap step gives nobody priority
            # (CR 502.4), so there is no moment at which a CR 616.1e choice
            # could be answered. With one effect in contention that costs
            # nothing, and a second would take the documented default.
            consumed, _ = apply_replacements(
                self, "would_untap",
                {"permanent": permanent, "player": player},
            )
            if consumed:
                continue

            self.become_untapped(permanent)
            untapped += 1

        # The marker's whole lifetime ends here (CR 611.2a: the effect lasts as
        # long as the spell said, and it said "next untap step"). Swept rather
        # than cleared inside the loop above, for two reasons the loop cannot
        # serve: it skips permanents that are already untapped, and a marked
        # permanent untapped by something else in between would keep its marker
        # forever. CR 701.43b says the same of exert, the keyworded form of this
        # effect — "each effect causing it not to untap expires during the same
        # untap step".
        #
        # After the skip-the-whole-step return above, deliberately: a skipped
        # untap step (Stasis) is a step that does not happen (CR 500.11), so it is
        # not yet the "next untap step" the spell named and the marker waits for
        # one that does.
        for permanent in self.controlled_by(player_index):
            # A count, not a flag: "its controller's next **two** untap steps"
            # (Telekinesis) spends one of them here and waits for the other, and
            # the marker is forgotten only when the last is spent. `True` from
            # any older record counts as one.
            #
            # A marker naming somebody else's untap step is left alone — this is
            # not the step it named, and CR 611.2a's stated duration is that
            # step and no other. Only the marker is held back; the land-type
            # window below is a different record with a different owner and is
            # swept for this seat regardless.
            if _skip_next_untap_names_this_step(permanent, player_index):
                held = int(permanent.metadata.get("skip_next_untap") or 0) - 1
                if held > 0:
                    permanent.metadata["skip_next_untap"] = held
                else:
                    permanent.metadata.pop("skip_next_untap", None)
                    permanent.metadata.pop(SKIP_NEXT_UNTAP_SEAT, None)
            # "Target land becomes a Swamp **until its controller's next untap
            # step**." (Orcish Farmer.) The window names the land's controller,
            # which is this seat, and the record outlives the permanent that
            # made it — so it is keyed by a label rather than by that permanent
            # and dropped here by the label's prefix. Dropping one contribution
            # is CR 611.3b: what the land is afterwards is whatever the others
            # still say, not what was printed on it.
            end_land_type_changes_from(permanent, prefix=LAND_TYPE_UNTIL_UNTAP)

        self.log.append(f"{player.name} untapped {untapped} permanent(s)")
        self._on_step_or_phase_end(phase, step)
        # No player receives priority during the untap step (CR 502.3), so the
        # first SBA check after it happens as the upkeep step opens — run it here
        # so untapping is never observable without its consequences. Old Man of
        # the Sea's steal lasts "for as long as this creature remains tapped":
        # untapping it must hand the creature back before anyone sees the board.
        self.check_state_based_actions()
        return untapped
