from __future__ import annotations

import re
from functools import lru_cache

from ..control import (
    LINKED_CONTROL_CONDITIONS,
    control_changes,
    end_control_change,
)
from ..equipment import is_equipment, unattach_illegal_equipment
from ..models import Permanent, PlayerState
from ..oracle import compile_card_oracle
from ..trigger_utils import matching_triggers
from .stack import aura_enchant_noun, enchant_noun_seat, enchant_seat_satisfied
from ..target_immunity import cannot_be_enchanted
from ..tokens import is_token_card

_COUNTER_CAP_RE = re.compile(r"can't have more than (\d+) (\w+) counters")


@lru_cache(maxsize=None)
def _parse_counter_cap(oracle_text: str) -> tuple[int, str] | None:
    """The 704.5r counter cap ``(limit, counter_type)`` a card imposes on itself,
    or None. Cached on oracle text so the regex runs once per distinct card
    rather than for every permanent on every state-based-action pass."""
    match = _COUNTER_CAP_RE.search(oracle_text.lower())
    if match is None:
        return None
    return int(match.group(1)), match.group(2)


class GameEndingMixin:
    def concede(self, player_index: int) -> None:
        """Rule 104.3a: A player who concedes leaves the game immediately and loses."""
        player = self.players[player_index]
        if not player.lost:
            player.lost = True
            self.log.append(f"{player.name} conceded and lost the game (104.3a)")
            # A concession can decide the game without any state-based action
            # running, so the ante is settled here too (CR 407.2).
            self._maybe_award_ante()

    def get_winner(self) -> PlayerState | None:
        """Return the single player who has won the game, or None if the game is not yet won.

        Rule 104.2a: a player wins if all opponents have lost.
        Rule 104.3f: a player who would win and lose simultaneously instead loses.
        """
        if self.is_draw:
            return None
        active = [p for p in self.players if not p.lost]
        if len(active) == 1:
            return active[0]
        return None

    def is_game_over(self) -> bool:
        """Rule 104.1: True if a player has won, the game is a draw, or all players have lost."""
        if self.is_draw:
            return True
        if all(p.lost for p in self.players):
            return True
        if self.get_winner() is not None:
            return True
        return False

    def _eliminate_player(self, player_index: int) -> None:
        """CR 800.4a: when a player leaves the game, objects they own leave with
        them. Scope decision for this engine: their battlefield permanents are
        exiled (removed from play — they're no longer valid attackers, blockers,
        or targets) and any stack objects they control cease to exist; their
        hand/library/graveyard are left alone (inert history — nothing keys off
        a lost player's non-battlefield zones for gameplay purposes, since
        ``opponents_of``/combat helpers already exclude lost players).

        CR 800.4n is an explicit exception to 800.4a: objects the departing
        player owns in the ante zone do NOT leave the game — they stay there for
        whoever eventually wins (CR 407.2) — so ``player.ante`` is untouched."""
        player = self.players[player_index]
        for permanent in self.controlled_by(player_index):
            self.log.append(
                f"{permanent.card.name} leaves the game ({player.name} left the game, CR 800.4a)"
            )
        self.remove_all_from_battlefield(list(self.controlled_by(player_index)))
        # CR 800.4a: stack objects this player owns/controls cease to exist.
        self.stack = [item for item in self.stack if item.caster_index != player_index]
        self.log.append(f"{player.name} has left the game (CR 800.4a)")

    def check_state_based_actions(self) -> bool:
        """Check and apply all state-based actions per CR 704. Returns True if any action fired."""
        any_changed = False
        changed = True
        previously_lost = {i for i, p in enumerate(self.players) if p.lost}
        # City in a Bottle-style set bans: which set codes are banned, and which
        # permanents are the banners themselves (exempt from the sweep). Computed
        # once per call — the banner population can't change mid-fixpoint (nothing
        # enters the battlefield during SBA processing), so there's no need to
        # recompile every permanent's oracle on each `while changed` pass. The
        # common case (no banner in play) leaves this empty and skips the sweep.
        banned_set_codes: set[str] = set()
        banner_perm_ids: set[int] = set()
        for _perm in self.all_permanents():
            for _instr in compile_card_oracle(_perm.effective_card).instructions:
                    if _instr.kind == "ban_and_sacrifice_set_permanents":
                        code = _instr.payload.get("set_code")
                        if code is not None:
                            banned_set_codes.add(code)
                        banner_perm_ids.add(id(_perm))
        while changed:
            changed = False

            # Recompute continuous effects (611.3a) before evaluating SBAs so that
            # characteristic-defining and lord P/T reflect the current board — e.g.
            # when a Plague Rats dies the others shrink immediately, and any creature
            # that drops to lethal/0 toughness as a result dies in the same pass.
            self._recompute_continuous_effects()

            # 704.5a: player with 0 or less life loses the game
            for player in self.players:
                if not player.lost and player.life <= 0:
                    # e.g. Lich / Platinum Angel-style replacement
                    if self._player_controls_text(
                        player, "you don't lose the game for having 0 or less life"
                    ):
                        continue
                    player.lost = True
                    self.log.append(f"{player.name} lost the game (704.5a: 0 or less life)")
                    changed = True

            # 704.5b: player who attempted to draw from empty library loses
            for player in self.players:
                if player.drew_from_empty:
                    player.drew_from_empty = False
                    if not player.lost:
                        player.lost = True
                        self.log.append(f"{player.name} lost the game (704.5b: drew from empty library)")
                    changed = True

            # 704.5c / 104.3d: player with 10 or more poison counters loses
            for player in self.players:
                if not player.lost and player.poison_counters >= 10:
                    player.lost = True
                    self.log.append(f"{player.name} lost the game (704.5c / 104.3d: {player.poison_counters} poison counters)")
                    changed = True

            # 704.6c / 903.10a: a player dealt 21 or more combat damage by the
            # same commander over the course of the game loses. Only in a
            # Commander game, and not in a Brawl one (903.12h) — both answered
            # by engine/commander.py rather than by a flag read here.
            if self._commander_damage_state_based_actions():
                changed = True

            # 903.9a: a commander put into a graveyard or into exile since the
            # last check may be moved to the command zone by its owner. Its
            # place among the state-based actions is after the ones that put it
            # there (704.5f/g above) and before the game-ending check below, so
            # a commander that died this pass is offered in this pass.
            if self._commander_zone_state_based_actions():
                changed = True

            # 104.4a: if all players have now lost, the game is a draw
            if not self.is_draw and len(self.players) > 1 and all(p.lost for p in self.players):
                self.is_draw = True
                self.log.append("Game is a draw (104.4a: all players lost simultaneously)")
                changed = True

            # State trigger: "When you control no Islands, sacrifice this creature"
            # (Sea Serpent) / "When you control no lands, sacrifice this creature"
            # (Serendib Djinn, Island Fish Jasconius already covered by no_islands).
            # Modeled alongside SBAs so it fires immediately when the last
            # matching land leaves, not only at the next upkeep (CR 603.8).
            from ..subject_filters import subject_matches

            for seat, player in enumerate(self.players):
                for perm in list(self.controlled_by(player)):
                    # "When you control **no <noun>**, sacrifice this creature."
                    # The noun is payload, tested by ``subject_matches`` — the
                    # same reader the positive twin below uses — so Sea Serpent's
                    # Islands, Serendib Djinn's lands and Gorilla Pack's Forests
                    # are one rule. It used to be two condition kinds with the
                    # type welded into each name, which is why a card printing
                    # the identical sentence about any third type could not be
                    # read at all.
                    empty_of = [
                        trig.condition.payload.get("controlled_filter") or {}
                        for trig in matching_triggers(
                            perm.effective_card,
                            condition_kinds={"controls_no_matching"},
                            instruction_kinds={"sacrifice_self"},
                        )
                    ]
                    needs_none = any(
                        not any(
                            subject_matches(
                                self, other, described, observer=seat, source=perm
                            )
                            for other in self.controlled_by(seat)
                        )
                        for described in empty_of
                    )
                    # "When there are **no lands on the battlefield**,
                    # sacrifice this enchantment." (Mana Vortex.) The same
                    # state trigger asked about every battlefield rather than
                    # this seat's, so it is its own condition and its own
                    # count: a Mana Vortex whose controller has run out of
                    # lands stays while an opponent still has one.
                    needs_any_land_anywhere = next(matching_triggers(
                        perm.effective_card,
                        condition_kinds={"no_lands_anywhere"},
                        instruction_kinds={"sacrifice_self"},
                    ), None) is not None
                    lands_anywhere = any(
                        p.has_type("land") for p in self.all_permanents()
                    )
                    if needs_none or (
                        needs_any_land_anywhere and not lands_anywhere
                    ):
                        # Through the one sacrifice transition (CR 701.21a), not
                        # a graveyard append beside a battlefield rebuild: the
                        # card says *sacrifice*, and the open-coded pair here
                        # skipped the `was_sacrificed` stamp and the
                        # `you_sacrifice_permanent` announcement that every
                        # other sacrifice in the engine makes. Sea Serpent and
                        # Island Fish Jasconius have been leaving that way since
                        # the seam was built.
                        self.sacrifice_permanent(perm)
                        reason = (
                            "no lands on the battlefield"
                            if needs_any_land_anywhere and not lands_anywhere
                            else "controls none of what its state trigger names"
                        )
                        self.log.append(f"{perm.card.name} sacrificed ({reason})")
                        changed = True

            # The positive state trigger: "When you control a Dwarf, sacrifice
            # this creature." (Goblins of the Flarg.) CR 603.8 again, and here
            # rather than at the upkeep for the same reason as the two above —
            # the condition becomes true the moment the Dwarf arrives, and a
            # trigger that waited for the next upkeep would let the Goblin
            # attack alongside it. The noun phrase is payload, tested by
            # ``subject_matches``, so a card naming any other tribe needs
            # nothing here.
            for seat, player in enumerate(self.players):
                for perm in list(self.controlled_by(player)):
                    for trig in matching_triggers(
                        perm.effective_card,
                        condition_kinds={"controls_matching_permanent"},
                        instruction_kinds={"sacrifice_self"},
                    ):
                        described = trig.condition.payload.get("controlled_filter") or {}
                        if not any(
                            subject_matches(
                                self, other, described, observer=seat, source=perm
                            )
                            for other in self.controlled_by(seat)
                        ):
                            continue
                        # The same sacrifice seam the no-lands block above was
                        # taught to use (CR 701.21a). These three sweeps say
                        # "sacrificed" in their own log lines while appending to
                        # a graveyard beside a battlefield rebuild, which skips
                        # the `was_sacrificed` stamp and the
                        # `you_sacrifice_permanent` announcement — so a card
                        # watching for a sacrifice never saw one of these.
                        self.sacrifice_permanent(perm)
                        self.log.append(
                            f"{perm.card.name} sacrificed (its controller controls "
                            "what its state trigger names)"
                        )
                        changed = True
                        break

            # Jihad: "When the chosen player controls no nontoken permanents of
            # the chosen color, sacrifice this enchantment." A state trigger
            # (CR 603.8) checked alongside SBAs like the no-lands sacrifices
            # above, so it fires the moment the last matching permanent leaves.
            for player in self.players:
                for perm in list(self.controlled_by(player)):
                    if (
                        "when the chosen player controls no nontoken permanents of the chosen color"
                        in perm.effective_card.oracle_text.lower()
                        and isinstance(perm.metadata.get("chosen_player_index"), int)
                        and not self._chosen_color_permanent_condition(perm)
                    ):
                        self.sacrifice_permanent(perm)
                        self.log.append(
                            f"{perm.card.name} sacrificed (the chosen player controls no "
                            "nontoken permanents of the chosen color)"
                        )
                        changed = True

            # City in a Bottle: "other nontoken permanents with a name
            # originally printed in [set] are on the battlefield, their
            # controllers sacrifice them." Modeled as a continuous state
            # check (like the no-lands trigger above) rather than a one-shot
            # trigger, so it also catches a banned permanent entering after
            # City in a Bottle is already in play.
            if banned_set_codes:
                for player in self.players:
                    for perm in list(self.controlled_by(player)):
                        # The card's original printing, not whichever set loaded
                        # first — see _set_lockout_banning_card.
                        card_set = perm.card.original_printing.lower()
                        if (
                            id(perm) not in banner_perm_ids
                            and not perm.metadata.get("is_token")
                            and card_set in banned_set_codes
                        ):
                            self.sacrifice_permanent(perm)
                            self.log.append(f"{perm.card.name} sacrificed (City in a Bottle)")
                            changed = True

            # Old Man of the Sea: linked-duration steal ends the instant it
            # untaps OR the stolen creature's power exceeds its own (unlike
            # Aladdin's simpler "for as long as you control this creature"),
            # so it's checked continuously here rather than only on leave.
            for perm in self.all_permanents():
                if not perm.metadata.get("stolen_while_tapped_and_weaker"):
                    continue
                stolen = next(iter(self.permanents_controlled_via(perm)), None)
                if stolen is None:
                    continue
                if not perm.tapped or stolen.effective_power > perm.effective_power:
                    self.end_control_changes_from(perm)
                    perm.metadata.pop("stolen_while_tapped_and_weaker", None)
                    changed = True

            # Monitored linked-duration control changes (CR 611.2b): "for as
            # long as you control this creature [and this creature remains
            # tapped]" (Willow Satyr, Rubinia Soulsinger, The Wretched). The
            # conditions ride the *source's* record
            # (engine/control.LINKED_CONTROL_CONDITIONS) and are re-checked
            # here from the **stolen** side — each contribution names its
            # source, so a source that has left the battlefield is still
            # seen, which the source-side scan above cannot do. The moment a
            # condition is false the contribution is dropped and whatever
            # remains decides (engine/control.py).
            for held in list(self.all_permanents()):
                for entry in control_changes(held):
                    source = entry["source"]
                    if not isinstance(source, Permanent):
                        continue
                    conditions = source.metadata.get(LINKED_CONTROL_CONDITIONS)
                    if not conditions:
                        continue
                    broken = (
                        "you_control_source" in conditions
                        # The seat the change gave control to must still
                        # control the source; a source off the battlefield
                        # has no controller, so leaving breaks it too.
                        and self.controller_index_of(source)
                        != entry["controller_index"]
                    ) or (
                        "source_remains_tapped" in conditions
                        and (
                            not self.is_on_battlefield(source)
                            or not source.tapped
                        )
                    ) or (
                        # "…for as long as this creature remains on the
                        # battlefield" (Scarwood Bandits). Weaker than the
                        # control condition above and not the same test: an
                        # opponent stealing the Bandits breaks that one and not
                        # this one, and the artifact stays where it is.
                        "source_on_battlefield" in conditions
                        and not self.is_on_battlefield(source)
                    )
                    if not broken:
                        continue
                    end_control_change(held, source=source)
                    self._sync_control()
                    now = self.controller_index_of(held)
                    if now is not None:
                        self.log.append(
                            f"{held.card.name} returns to "
                            f"{self.players[now].name}'s control "
                            f"({source.card.name}'s linked control "
                            "effect ended)"
                        )
                    changed = True

            # 704.5d: a token in any zone but the battlefield ceases to exist.
            # The zone seams (put_card_into_hand / put_card_into_library) and
            # _permanent_to_graveyard refuse a token up front, so this is the
            # backstop for a path that moved a card without going through one —
            # the sweep that catches what one forgotten call site would leak.
            for player in self.players:
                for zone_name in ("graveyard", "hand", "exile"):
                    zone = getattr(player, zone_name, None)
                    if not zone or not any(is_token_card(c) for c in zone):
                        continue
                    setattr(player, zone_name, [c for c in zone if not is_token_card(c)])
                    changed = True

            # 704.5f: creature with toughness 0 or less → graveyard (regeneration cannot replace)
            def _zero_toughness(perm: Permanent) -> bool:
                # ``effective_card``, not ``card``: a copy's printed toughness is
                # the copied object's (CR 613 layer 1). Reading the copier's own
                # would call a Clone of a variable-P/T creature "fixed at 0" and
                # sweep it in the window before the characteristic-defining
                # ability has been counted — the same printed-vs-effective bug
                # the animated-Mox sweep had.
                raw_t = str(perm.effective_card.raw.get("toughness", "0"))
                has_fixed_toughness = raw_t.lstrip("-").isdigit()
                has_dynamic_toughness = not has_fixed_toughness and "absolute_toughness" not in perm.metadata
                # is_creature (CR 613 layer 4), not the printed type line: an
                # artifact animated by Animate Artifact, or a land animated by
                # Kormus Bell, is a creature and CR 704.5f applies to it. Reading
                # the printed type meant an animated Mox sat at 0/0 forever.
                # A permanent that has not finished entering has no settled
                # characteristics to test (CR 614.1c): Wood Elemental's P/T is
                # the number of Forests sacrificed *as it entered*, and the
                # answer to that is still queued. Sweeping it here binned the
                # creature between raising the prompt and the player seeing it.
                if self.permanent_is_entering(perm):
                    return False
                return perm.is_creature and not has_dynamic_toughness and perm.effective_toughness <= 0

            for player in self.players:
                def _on_destroy_5f(perm: Permanent, player=player) -> None:
                    self.log.append(f"{perm.card.name} died (704.5f: toughness {perm.effective_toughness})")
                    self._trigger_aura_death_effects(perm, player)

                if self._destroy_swept_permanents(
                    player, _zero_toughness,
                    allow_regeneration=False, respect_indestructible=False,
                    on_destroy=_on_destroy_5f,
                ):
                    changed = True

            # 704.5g/h: creature with lethal damage marked (or any damage from a
            # deathtouch source) is destroyed. Regeneration replaces that
            # destruction (CR 701.19).
            #
            # This lives in the SBA loop rather than only in
            # _destroy_marked_creatures(), which every damage-dealing effect had
            # to remember to call by hand — nine call sites, and a tenth that
            # forgot would leave a lethally damaged creature alive. Composed
            # damage sequences make that failure mode much easier to hit, since
            # a damage step no longer necessarily sits inside a handler that
            # knows to run the sweep.
            def _lethally_damaged(perm: Permanent) -> bool:
                if not perm.is_creature:
                    return False
                if perm.effective_toughness <= 0:
                    return False  # 704.5f above owns this case
                if perm.damage_marked >= perm.effective_toughness:
                    return True
                return bool(
                    perm.metadata.get("received_deathtouch") and perm.damage_marked > 0
                )

            def _regenerated(perm: Permanent) -> None:
                # Clear the marked damage the shield replaced; leaving it marked
                # would re-destroy the creature on the next pass of this loop.
                perm.damage_marked = 0
                perm.metadata.pop("received_deathtouch", None)

            for player in self.players:
                def _on_destroy_5g(perm: Permanent, player=player) -> None:
                    self.log.append(f"{perm.card.name} died (704.5g: lethal damage)")
                    self._trigger_aura_death_effects(perm, player)

                if self._destroy_swept_permanents(
                    player, _lethally_damaged,
                    on_regenerate=_regenerated,
                    on_destroy=_on_destroy_5g,
                ):
                    changed = True

            # 704.5h is scoped to damage dealt "since the last time state-based
            # actions were checked", so the marker is one-shot: anything still
            # alive after the sweep (its damage was prevented down to nothing)
            # must not carry the flag into a later, unrelated damage event.
            for perm in self.all_permanents():
                perm.metadata.pop("received_deathtouch", None)

            # 704.5i: planeswalker with 0 loyalty → graveyard. Loyalty lives in
            # metadata["loyalty_counters"] (CR 306.5c: loyalty on the
            # battlefield IS its loyalty counters), written on entry by
            # _initialize_permanent_state and adjusted by damage and loyalty
            # costs. has_type, not the printed line, so a layer-4 type change
            # is honored.
            def _zero_loyalty(perm: Permanent) -> bool:
                if not perm.has_type("planeswalker"):
                    return False
                loyalty = perm.metadata.get("loyalty_counters")
                return loyalty is not None and loyalty <= 0

            for player in self.players:
                if self._destroy_swept_permanents(
                    player, _zero_loyalty,
                    allow_regeneration=False, respect_indestructible=False,
                    on_destroy=lambda perm: self.log.append(
                        f"{perm.card.name} went to graveyard (704.5i: 0 loyalty)"
                    ),
                ):
                    changed = True

            # 704.5j: legend rule — same player controlling two legendaries with same name
            for player in self.players:
                legendary_by_name: dict[str, list[Permanent]] = {}
                for perm in self.controlled_by(player):
                    # Both reads are of the **effective** card, because CR 707.2
                    # copies the name and the type line together: a Clone of
                    # Hazezon Tamar is a second Hazezon Tamar, and asking the
                    # printed card asks the copier's own line — where a Clone is
                    # a Shapeshifter named Clone that matches nothing, so the
                    # rule never fired for the one board state it exists for.
                    # Layer 3 rides along for free (a text change rewrites the
                    # type line before anything reads it).
                    #
                    # `has_supertype` and not the printed line: layer 4
                    # computes supertypes now (CR 205.4a), so a "legendary" an
                    # effect added or took away is counted where the printed
                    # read would have missed both.
                    effective = perm.effective_card
                    if perm.has_supertype("legendary"):
                        legendary_by_name.setdefault(effective.name, []).append(perm)
                for name, perms in legendary_by_name.items():
                    if len(perms) > 1:
                        # Keep first; put the rest in graveyard. Collected as
                        # permanents rather than indices, so the reverse-order
                        # walk that kept the indices valid is gone with them.
                        for removed in reversed(perms[1:]):
                            self.remove_from_battlefield(removed)
                            self._permanent_to_graveyard(player, removed)
                            self.log.append(f"{name} put into graveyard (704.5j: legend rule)")
                        changed = True

            # 704.5k: world rule — keep only the most recently timestamped world permanent
            world_perms: list[tuple[PlayerState, Permanent]] = [
                (self.players[seat], perm)
                for seat, perm in self.permanents_with_controller()
                # The world supertype is a copiable value too (CR 707.2), and
                # the same printed read hid a copy of a world permanent here.
                # Layer 4 folds the copy in and any change to the word on top.
                if perm.has_supertype("world")
            ]
            if len(world_perms) > 1:
                # Keep last (most recent timestamp = highest position), remove rest
                for player, perm in world_perms[:-1]:
                    if self.controls(player, perm):
                        self.remove_from_battlefield(perm)
                        self._permanent_to_graveyard(player, perm)
                        self.log.append(f"{perm.card.name} put into graveyard (704.5k: world rule)")
                changed = True

            # 704.5m: Aura/Role not attached to a legal object → graveyard
            def _illegally_attached(perm: Permanent) -> bool:
                # Asked of CR 613 layer 4, not of the printed line: an effect
                # can return an Aura "as a **non-Aura** enchantment"
                # (Takklemaggot), and a sweep reading `card.type_line` would
                # bin the very permanent that sentence created. The printed
                # line is still the answer for everything nothing has changed.
                if not perm.has_type("aura") and not perm.has_type("role"):
                    return False
                if "attached_to" not in perm.metadata:
                    # Manually placed without tracking — skip 704.5m
                    return False
                attached_to = perm.metadata.get("attached_to")
                if attached_to is None:
                    return True
                return not self.is_on_battlefield(attached_to)

            def _on_destroy_5m(perm: Permanent) -> None:
                reason = (
                    "unattached aura"
                    if perm.metadata.get("attached_to") is None
                    else "enchanted object left battlefield"
                )
                self.log.append(f"{perm.card.name} put into graveyard (704.5m: {reason})")

            for player in self.players:
                if self._destroy_swept_permanents(
                    player, _illegally_attached,
                    allow_regeneration=False, respect_indestructible=False,
                    on_destroy=_on_destroy_5m,
                ):
                    changed = True

            # CR 303.4c's "and **other applicable effects**": an Aura on a
            # permanent that can't be enchanted by other Auras (Anti-Magic
            # Aura) is enchanting an illegal object, and 704.5m bins it. The
            # source's own Aura is exempt by the printed word "other", which is
            # why the predicate takes the Aura asking — without that Anti-Magic
            # Aura would make itself illegal and be swept the turn it landed.
            for player in self.players:
                departing_immune = []
                for perm in list(self.controlled_by(player)):
                    if not perm.has_type("aura"):
                        continue
                    host = perm.metadata.get("attached_to")
                    if host is None or not self.is_on_battlefield(host):
                        continue
                    if not cannot_be_enchanted(host, by_aura=perm):
                        continue
                    self._permanent_to_graveyard(player, perm)
                    self.log.append(
                        f"{perm.card.name} put into graveyard (704.5m: "
                        f"{host.card.name} can't be enchanted by other Auras)"
                    )
                    changed = True
                    departing_immune.append(perm)
                self.remove_all_from_battlefield(departing_immune)

            # CR 704.5m's other half: an Aura is also illegally attached when
            # its host stops satisfying the enchant clause. Enforced for the
            # clause's *seat* half ("Enchant creature **you control**", Cocoon;
            # "Enchant artifact **an opponent controls**", Relic Bind)
            # — an opponent gaining control of the creature makes the
            # attachment illegal, and the Aura is put into its owner's
            # graveyard. Read through the same `enchant_seat_satisfied` the
            # cast gate and the picker read, so the three cannot drift.
            for player in self.players:
                departing_own = []
                for perm in list(self.controlled_by(player)):
                    if "Aura" not in perm.card.type_line:
                        continue
                    attached_to = perm.metadata.get("attached_to")
                    if attached_to is None or not self.is_on_battlefield(attached_to):
                        continue
                    noun = aura_enchant_noun(perm.effective_card)
                    if noun is None or enchant_noun_seat(noun) is None:
                        continue
                    aura_seat = self.controller_index_of(perm)
                    if enchant_seat_satisfied(
                        self, aura_seat, self.controller_index_of(attached_to), noun
                    ):
                        continue
                    self._permanent_to_graveyard(player, perm)
                    self.log.append(
                        f"{perm.card.name} put into graveyard (704.5m: enchanted "
                        f"permanent no longer satisfies the enchant {noun} clause)"
                    )
                    changed = True
                    departing_own.append(perm)
                self.remove_all_from_battlefield(departing_own)

            # An Aura attached to a permanent that "can't be enchanted by other
            # Auras" (Consecrate Land) is illegally attached and is put into its
            # owner's graveyard. The Aura granting the restriction is exempt. This
            # covers Consecrate Land entering onto a land that already had Auras.
            for player in self.players:
                departing = []
                for perm in list(self.controlled_by(player)):
                    attached_to = perm.metadata.get("attached_to")
                    if (
                        "Aura" in perm.card.type_line
                        and attached_to is not None
                        and self._cant_be_enchanted(attached_to)
                        and "can't be enchanted by other auras" not in perm.effective_card.oracle_text.lower()
                    ):
                        self._permanent_to_graveyard(player, perm)
                        self.log.append(f"{perm.card.name} put into graveyard (enchanted land can't be enchanted by other Auras)")
                        changed = True
                        departing.append(perm)
                self.remove_all_from_battlefield(departing)

            # CR 702.16c / 702.16n: an Aura with a quality the enchanted permanent
            # has protection from is put into its owner's graveyard, unless the
            # Aura's own text says the effect doesn't remove it (702.16n, e.g.
            # White Ward).
            for player in self.players:
                departing = []
                for perm in list(self.controlled_by(player)):
                    attached_to = perm.metadata.get("attached_to")
                    if "Aura" in perm.card.type_line and attached_to is not None:
                        protection = self._protection_colors(attached_to)
                        if protection and (protection & self._effective_colors(perm)):
                            text = perm.effective_card.oracle_text.lower()
                            exempt = "remove this aura" in text or "remove all auras" in text
                            if not exempt:
                                self._permanent_to_graveyard(player, perm)
                                self.log.append(
                                    f"{perm.card.name} put into graveyard (702.16c: enchanted permanent has protection)"
                                )
                                changed = True
                                departing.append(perm)
                self.remove_all_from_battlefield(departing)

            # CR 704.5n (and 702.16d, 301.5c, 701.3d): an Equipment attached
            # to a permanent it can't legally equip becomes unattached and stays
            # on the battlefield. One sweep in engine/equipment.py, reading the
            # same legality the equip ability's resolution and target picker
            # read. The two loops it replaced cleared `attached_to` on the
            # Equipment alone and left it in the creature's `attached_auras`
            # list — so a Short Sword unattached by protection kept granting
            # its +1/+1 to the creature it no longer equipped.
            if unattach_illegal_equipment(self):
                changed = True

            # 704.5p: non-Aura, non-Equipment, non-Role permanent in attached state → unattach
            for perm in self.all_permanents():
                if "Aura" in perm.card.type_line or is_equipment(perm) or "Role" in perm.card.type_line:
                    continue
                if perm.metadata.get("attached_to") is not None:
                    perm.metadata["attached_to"] = None
                    self.log.append(f"{perm.card.name} became unattached (704.5p: illegal attached state)")
                    changed = True

            # 704.5q: +1/+1 and -1/-1 counter cancellation
            for perm in self.all_permanents():
                plus = perm.metadata.get("plus_counters", 0)
                minus = perm.metadata.get("minus_counters", 0)
                if plus > 0 and minus > 0:
                    cancel = min(plus, minus)
                    perm.metadata["plus_counters"] = plus - cancel
                    perm.metadata["minus_counters"] = minus - cancel
                    self.log.append(f"{perm.card.name}: cancelled {cancel} +1/+1 and -1/-1 counters (704.5q)")
                    changed = True

            # 704.5r: counter cap enforcement
            for perm in self.all_permanents():
                cap_info = _parse_counter_cap(perm.effective_card.oracle_text)
                if cap_info is None:
                    continue
                cap, counter_type = cap_info
                counter_key = f"{counter_type}_counters"
                current = perm.metadata.get(counter_key, 0)
                if current > cap:
                    perm.metadata[counter_key] = cap
                    self.log.append(f"{perm.card.name}: trimmed {counter_type} counters to {cap} (704.5r)")
                    changed = True

            # 704.5s: Saga at or past final chapter → sacrifice
            def _saga_done(perm: Permanent) -> bool:
                if "Saga" not in perm.card.type_line:
                    return False
                final = perm.metadata.get("final_chapter", 0)
                return final > 0 and perm.metadata.get("lore_counters", 0) >= final

            for player in self.players:
                if self._destroy_swept_permanents(
                    player, _saga_done,
                    allow_regeneration=False, respect_indestructible=False,
                    on_destroy=lambda perm: self.log.append(
                        f"{perm.card.name} sacrificed (704.5s: Saga reached final chapter)"
                    ),
                ):
                    changed = True

            # 704.5y: Role rule — per creature per controller, keep only the most recent Role
            for perm in self.all_permanents():
                if perm.card.primary_type != "creature":
                    continue
                # Find all Roles attached to this creature, grouped by controller.
                # The seam yields each seat's permanents in battlefield order, so
                # "most recent" is still the last one collected.
                roles_by_ctrl: dict[int, list[Permanent]] = {}
                for ctrl_idx, role_perm in self.permanents_with_controller():
                    if "Role" not in role_perm.card.type_line:
                        continue
                    if role_perm.metadata.get("attached_to") is not perm:
                        continue
                    roles_by_ctrl.setdefault(ctrl_idx, []).append(role_perm)
                for ctrl_idx, roles in roles_by_ctrl.items():
                    if len(roles) <= 1:
                        continue
                    ctrl_player = self.players[ctrl_idx]
                    # Keep the last (most recent), remove the rest
                    for role_perm in roles[:-1]:
                        if self.controls(ctrl_player, role_perm):
                            self.remove_from_battlefield(role_perm)
                            self._permanent_to_graveyard(ctrl_player, role_perm)
                            self.log.append(f"{role_perm.card.name} put into graveyard (704.5y: role rule)")
                    changed = True

            if changed:
                any_changed = True

        # 611.3b: permanents may have left the battlefield above (lethal damage,
        # sacrifice, legend/world rule, mass destruction resolving just before this
        # SBA check). Recompute static buffs / dynamic P/T so the board is current.
        if any_changed:
            self._recompute_continuous_effects()

        # CR 800.4a: in a multiplayer game (3+ players) the game continues after a
        # player leaves, so their zones must actually be cleaned up now. A 2-player
        # game just ends instead (CR 800.4 is explicitly a multiplayer concept —
        # "unlike two-player games, multiplayer games can continue..."), so nothing
        # here changes 2-player behavior.
        if len(self.players) >= 3:
            newly_lost = [i for i, p in enumerate(self.players) if p.lost and i not in previously_lost]
            for idx in newly_lost:
                self._eliminate_player(idx)

        # CR 407.2: at the end of the game the winner becomes the owner of every
        # card in the ante zone. A player can become the sole survivor here
        # (life, empty library, poison), so settle it once the game is decided.
        self._maybe_award_ante()

        # "Whenever you draw your second card each turn" (Mystic Skyfish).
        # Announced here rather than at each draw site because there is no one
        # draw seam — a dozen paths append to ``cards_drawn_this_turn`` — and a
        # site every action already passes through cannot be forgotten by the
        # next one. The once-per-turn flag is what makes the sweep idempotent,
        # and the trigger still enqueues before any player next gets priority,
        # which is when a triggered ability is noticed anyway (CR 603.3b).
        from ..events import emit
        from ..named_counters import EMPTIED_KINDS_MARK, counters_on

        for seat, player in enumerate(self.players):
            if seat in self.second_draw_fired_this_turn or player.lost:
                continue
            if len(player.cards_drawn_this_turn) < 2:
                continue
            self.second_draw_fired_this_turn.add(seat)
            emit(self, "draws_second_card", seat=seat)

        # "Whenever you draw a card" (Lorescale Coatl, Burlfist Oak) — the same
        # sweep off the same record, counting instead of flagging, because
        # CR 121.2 makes drawing N cards N individual draws and this one fires
        # per card.
        #
        # It belongs here for a reason the second-card trigger only half shows:
        # the condition parsed on **both** sides of the pipeline and had no
        # dispatcher at all, so two cards compiled supported, entered play and
        # did nothing. A per-draw-site announcement would have had the same fate
        # as the replacements do — three handlers reach ``player.draw``
        # directly, and a list of fire sites is only ever as complete as the
        # last card that touched it.
        for seat, player in enumerate(self.players):
            if player.lost:
                continue
            announced = int(self.draws_announced_this_turn.get(seat, 0))
            drawn = len(player.cards_drawn_this_turn)
            if drawn <= announced:
                continue
            self.draws_announced_this_turn[seat] = drawn
            for _ in range(drawn - announced):
                # The drawing seat travels twice, under two names and for two
                # readers: `seat` is what the event filter narrows on ("you" or
                # "an opponent"), and `event_subject_player` is what a "that
                # player" in the effect resolves to (CR 603.10 — the trigger
                # freezes it, because by resolution the turn may have moved on).
                emit(self, "draws_card", seat=seat, event_subject_player=seat)

        # "When you remove the last intervention counter from this enchantment,
        # the game is a draw." (Divine Intervention.) An *event* trigger, not a
        # state one — but the event has four call sites (the removal handler, an
        # activation cost, an upkeep registry entry and a damage shield), so the
        # announcement reads the record `named_counters.remove_counters` writes
        # rather than being repeated at each of them. Exactly the argument the
        # draw triggers above are written with, and the card that pays for
        # getting it wrong is this one: its whole text is the draw.
        #
        # The record is drained as it is read, which is what makes this an event
        # and not a state: a permanent sitting at zero counters announces once,
        # and only for a removal that actually happened.
        for permanent in list(self.all_permanents()):
            emptied = permanent.metadata.get(EMPTIED_KINDS_MARK)
            if not emptied:
                continue
            for trig in compile_card_oracle(
                permanent.effective_card
            ).triggered_abilities:
                if trig.condition.kind != "last_counter_removed":
                    continue
                kind = str(trig.condition.payload.get("counter_kind", ""))
                if kind not in emptied:
                    continue
                seat = self.controller_index_of(permanent)
                if seat is None or trig.instruction is None:
                    continue
                self._enqueue_triggered_batch([{
                    "controller_index": seat,
                    "source_permanent": permanent,
                    "card": permanent.card,
                    "instruction": trig.instruction,
                    "effect_kind": trig.effect_kind,
                    "ability_text": trig.source_line,
                    "trigger_context": {},
                }])
                any_changed = True
            # Drained whether or not a trigger wanted it: the record is about
            # what happened, and a permanent nobody is asking about must not
            # accumulate one that fires the day it gains the ability.
            permanent.metadata.pop(EMPTIED_KINDS_MARK, None)

        # "When there are four or more page counters on this artifact, …"
        # (Mazemind Tome.) CR 603.8's *state* trigger: it fires whenever the
        # game state matches rather than on an event, so this sweep is where it
        # belongs — there is no call site to hang it on, and CR 603.8 says it
        # fires only once until the state stops matching, which is why the
        # permanent remembers that it announced.
        for permanent in list(self.all_permanents()):
            for trig in compile_card_oracle(
                permanent.effective_card
            ).triggered_abilities:
                if trig.condition.kind != "counters_reach_threshold":
                    continue
                kind = str(trig.condition.payload.get("counter_kind", ""))
                wanted = int(trig.condition.payload.get("counter_count", 0))
                held = counters_on(permanent, kind)
                announced = permanent.metadata.get("_state_trigger_announced") or set()
                key = (kind, wanted)
                if held < wanted:
                    # CR 603.8: the ability may fire again once the state stops
                    # matching. Nothing in the pool undoes a page counter, but
                    # forgetting is the rule and remembering forever is not.
                    if key in announced:
                        permanent.metadata["_state_trigger_announced"] = announced - {key}
                    continue
                if key in announced:
                    continue
                permanent.metadata["_state_trigger_announced"] = announced | {key}
                seat = self.controller_index_of(permanent)
                if seat is None or trig.instruction is None:
                    continue
                self._enqueue_triggered_batch([{
                    "controller_index": seat,
                    "source_permanent": permanent,
                    "card": permanent.card,
                    "instruction": trig.instruction,
                    "effect_kind": trig.effect_kind,
                    "ability_text": trig.source_line,
                    "trigger_context": {},
                }])
                any_changed = True

        return any_changed
