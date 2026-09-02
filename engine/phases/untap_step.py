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
                                UNTAP_LOCK_WHILE_TAPPED_KEY)
from ..land_types import end_land_type_changes_from
from ..control import LINKED_CONTROL_CONDITIONS
from ..named_counters import counters_on
from ..turn_state import record_turn_start_states
from ..turn_state import attacked_during_seats_last_turn
from ..untap_restrictions import (
    SELF_DOESNT_UNTAP_PHRASE,
    SELF_MAY_KEEP_TAPPED_PHRASE,
    self_untap_attacked_last_turn,
    self_untap_counter_condition,
    self_untap_line,
    untap_restriction_for,
)


#: The card types a "can't untap more than N" restriction may name. The untap
#: step asks each one separately, so a card printed with any of them needs no
#: code here — only a row in engine/untap_restrictions.py.
_LIMITED_TYPES = ("land", "creature", "artifact")


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
        return True
    return blocked


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
            elif restriction.blocked is not None:
                blocked.append(
                    (restriction.blocked, self.controller_index_of(perm), perm)
                )
        return {
            "skip_all_source": skip_all_source,
            "limits": limits,
            "blocked": blocked,
        }

    def get_untap_land_selection_options(self, player_index: int) -> dict[str, object] | None:
        """Untap-step selection constraints the controller must resolve: Winter Orb
        limits untapping to one *land*, Smoke to one *creature*. Returns combined
        candidate battlefield indices and the total number that may be untapped
        among the constrained types, or None if nothing is constrained."""
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
            if perm.tapped and perm.has_type(card_type)
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
        # CR 702.26e: phased-out permanents this player controls phase in as
        # the untap step begins, before anything untaps.
        self.phase_in_for(player_index)
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
        constraints = self._untap_constraints()

        if constraints["skip_all_source"] is not None:
            self.log.append(f"{player.name} skipped untap due to {constraints['skip_all_source']}")
            return 0

        limits: dict[str, int] = dict(constraints["limits"])
        blocked = list(constraints["blocked"])

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
                if permanent.card.primary_type != card_type:
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
        for idx, permanent in enumerate(player.battlefield):
            if not permanent.tapped:
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
            # flag, because the restriction has no end date (CR 611.2b) and
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
            if any(
                holder.tapped
                and holder.metadata.get(UNTAP_LOCK_WHILE_TAPPED_KEY) == permanent.permanent_id
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
            applicable = [t for t in limits if permanent.has_type(t)]
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
