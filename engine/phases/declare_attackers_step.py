from __future__ import annotations

"""Declare attackers step (CR 508).

The active player declares attackers (and any attacking bands) as a turn-based
action, taps non-vigilance attackers, puts any attack triggers on the stack
(CR 508.2), then receives priority (CR 508.4) so the triggers resolve as players
pass. Also holds the attack-legality query (``can_attack``),
"must attack if able" enforcement, and the banding-declaration validation.
"""

from ..auras import aura_restriction_active
from ..combat_permissions import ATTACK_AS_THOUGH_NO_DEFENDER
from ..subject_filters import subject_matches
from ..events import emit
from ..models import Permanent, PlayerState
from ..oracle import compile_card_oracle
from ..static_bonuses import conditional_static_holds
from ..trigger_utils import matching_triggers


class DeclareAttackersStepMixin:
    def declare_attackers(
        self,
        controller_index: int,
        attacker_indices: list[int],
        defending_player_index: int | None = None,
        bands: list[list[int]] | None = None,
        attacker_targets: dict[int, int] | None = None,
        attacker_planeswalker_ids: dict[int, int] | None = None,
    ) -> tuple[bool, str]:
        """Declare attackers (CR 508). Under CR 802 (attack multiple players), each
        attacker may name its own defending player via ``attacker_targets`` (attacker
        battlefield idx -> defending player idx). Any attacker not present in
        ``attacker_targets`` falls back to the shared ``defending_player_index`` —
        the original 2-player/back-compat shorthand of "everyone attacks this one
        opponent", still exactly how every existing (2-player) caller behaves.

        CR 508.1b: an attacker may instead attack a planeswalker an opponent
        controls — ``attacker_planeswalker_ids`` maps attacker battlefield idx to
        the attacked planeswalker's ``permanent_id``. Such an attacker's
        defending *player* (for blocks, restrictions and CR 508.5) is the
        planeswalker's controller, derived here rather than asked for twice."""
        if self.current_turn_phase != "combat" or self.current_step != "declare_attackers":
            return False, "attackers can only be declared during declare_attackers"
        if controller_index != self.active_player_index:
            return False, "only the active player may declare attackers"

        controller = self.players[controller_index]
        unique_indices = sorted(set(attacker_indices))
        living_opponents = self.opponents_of(controller_index)

        attacker_targets = dict(attacker_targets or {})
        attacker_planeswalker_ids = dict(attacker_planeswalker_ids or {})
        per_attacker_walker: dict[int, int] = {}
        for idx, walker_id in attacker_planeswalker_ids.items():
            if idx not in unique_indices:
                return False, f"planeswalker target given for non-attacker {idx}"
            walker = self.permanent_by_id(walker_id)
            if walker is None or not walker.has_type("planeswalker"):
                return False, "attacked planeswalker is not on the battlefield"
            walker_seat = self.controller_index_of(walker)
            if walker_seat is None or walker_seat == controller_index:
                return False, "a creature can only attack an opponent's planeswalker"
            # The walker names the defending player (CR 508.5); a contradictory
            # explicit seat for the same attacker is a malformed declaration.
            stated = attacker_targets.get(idx)
            if stated is not None and stated != walker_seat:
                return False, "attacker's defending player contradicts its attacked planeswalker"
            attacker_targets[idx] = walker_seat
            per_attacker_walker[idx] = walker_id

        per_attacker_defender: dict[int, int] = {}
        for idx in unique_indices:
            target = attacker_targets.get(idx, defending_player_index)
            if target is None:
                # No explicit target for this attacker: with exactly one living
                # opponent (2-player games, always) that's unambiguous — attack
                # them, exactly as every existing caller already assumes. Only a
                # genuine 3+ player choice requires an explicit target.
                if len(living_opponents) == 1:
                    target = living_opponents[0]
                else:
                    return False, f"no defending player chosen for attacker {idx}"
            per_attacker_defender[idx] = target

        living_opponents_set = set(living_opponents)
        for target in per_attacker_defender.values():
            if target < 0 or target >= len(self.players) or target == controller_index:
                return False, "invalid defending player"
            if target not in living_opponents_set:
                return False, "that player has already left the game"

        required_attackers: list[str] = []
        for idx, attacker in enumerate(controller.battlefield):
            if not self._is_creature(attacker) or attacker.tapped:
                continue
            if idx in unique_indices:
                continue
            if self._must_attack_if_able(attacker) and any(
                self.can_attack(attacker, opp) for opp in living_opponents
            ):
                required_attackers.append(attacker.card.name)
        if required_attackers:
            if len(required_attackers) == 1:
                return False, f"{required_attackers[0]} must attack if able"
            names = ", ".join(required_attackers)
            return False, f"{names} must attack if able"

        for idx in unique_indices:
            if idx < 0 or idx >= len(controller.battlefield):
                return False, "attacker index out of range"
            attacker = controller.battlefield[idx]
            if not self._is_creature(attacker):
                return False, "only creatures can attack"
            if attacker.tapped:
                return False, f"{attacker.card.name} is tapped"
            if not self.can_attack(
                attacker,
                per_attacker_defender[idx],
                # CR 508.5: this attacker attacks the planeswalker, and its
                # defending player is derived — so a restriction scoped to
                # attacking "a player" (Arboria) must know the difference.
                attacking_planeswalker=idx in per_attacker_walker,
            ):
                return False, f"{attacker.card.name} cannot attack"

        # CR 702.22c: validate any declared attacking bands before committing.
        validated_bands, band_error = self._validate_attacking_bands(
            bands, unique_indices, controller
        )
        if band_error is not None:
            return False, band_error

        self.combat_attackers = dict(per_attacker_defender)
        self.combat_attacked_planeswalkers = dict(per_attacker_walker)
        self.combat_defending_player_index = self._resolve_defending_player_index()
        self.combat_blockers = {}
        self.combat_blockers_declared_by = set()
        self.combat_bands = validated_bands
        self.combat_band_blocks = {}
        self.combat_banding_damage = {}
        self.combat_multiblock_damage = {}
        self.combat_damage_resolved = False
        self.combat_first_strike_done = False
        self.combat_attackers_locked = True
        self.combat_blockers_locked = False
        self._prune_combat_state()

        declared: list[Permanent] = []
        for idx in unique_indices:
            attacker = controller.battlefield[idx]
            declared.append(attacker)
            # CR 702.20b: attacking doesn't cause a creature with vigilance to tap.
            if not self._has_keyword(attacker, "vigilance"):
                self.become_tapped(attacker)
                self._turn_face_up(attacker)
            attacker.metadata["attacked_this_turn"] = True
            # The durable half of that record: which seat's turn it attacked
            # on, by that seat's own turn ordinal. `attacked_this_turn` is
            # swept at cleanup, and "it attacked during your last turn" (Giant
            # Turtle) is a question asked one turn later — so this key is
            # deliberately not in `_EOT_METADATA_KEYS`, and it dies with the
            # permanent instead (CR 400.7: a Turtle that leaves and returns is
            # a new object with no record). Overwritten on each attack; only
            # the latest one can be "your last turn".
            attacker.metadata["attacked_on_seat_turn"] = {
                "seat": controller_index,
                "seat_turn": self.seat_turn_counts.get(controller_index, 0),
            }

        self._prune_combat_state()
        self.log.append(f"{controller.name} declared {len(unique_indices)} attacker(s)")
        if validated_bands:
            self.log.append(f"{controller.name} declared {len(validated_bands)} band(s)")
        if unique_indices:
            self._fire_attack_triggers(controller_index)
            self._fire_creature_attacks_triggers(controller_index, unique_indices)
            self._fire_matching_creature_attacks_triggers(declared)
            self._announce_attack_declaration(controller_index, declared)
            self._fire_delayed_attack_triggers(controller_index, unique_indices)
        # CR 508.4: once attackers have been declared (the turn-based action of the
        # declare attackers step), the active player receives priority.
        self.start_priority_window(self.active_player_index)
        return True, "declared attackers"

    def _fire_delayed_attack_triggers(
        self, controller_index: int, attacker_indices: list[int]
    ) -> None:
        """Delayed "whenever … creature(s) attack this turn" triggers created
        by a resolved loyalty ability (CR 603.7 — Basri Ket's −2, Basri,
        Devoted Paladin's −1). A batch entry fires once per attack with the
        count of matching attackers; a per-creature entry fires once per
        matching attacker, with that attacker as the trigger's source so its
        "on it" resolves to the creature. Entries stay armed for every combat
        this turn — cleanup clears them."""
        if not self.delayed_triggers:
            return
        controller = self.players[controller_index]
        attackers = [
            perm
            for idx in attacker_indices
            if (perm := self.permanent_at(controller, idx)) is not None
        ]
        if not attackers:
            return
        defending = next(iter(sorted(self.combat_defending_players())), None)
        events: list[dict] = []
        for entry in list(self.delayed_triggers):
            if entry.get("event") != "creatures_attack":
                continue
            # "…whenever **a creature you control with power 2 or less**
            # attacks" (Subira's shape, on the attack event). The narrowing is a
            # filter payload like every other, asked through `subject_matches`
            # because "you control" is a seat comparison the object alone cannot
            # answer (CR 109.5). `nontoken` stays its own key: it predates this
            # and the two payloads are not the same shape.
            described = entry.get("attacker_filter") or {}
            matching = [
                perm for perm in attackers
                if not (entry.get("nontoken") and perm.metadata.get("is_token"))
                and subject_matches(
                    self, perm, described,
                    observer=int(entry.get("controller_index", controller_index)),
                )
            ]
            if not matching:
                continue
            seat = int(entry.get("controller_index", controller_index))
            instruction = entry.get("instruction")
            if instruction is None:
                continue
            if entry.get("batch"):
                events.append({
                    "controller_index": seat,
                    "source_permanent": None,
                    "card": entry.get("card"),
                    "instruction": instruction,
                    "effect_kind": "triggered_delayed",
                    "ability_text": entry.get("source_name", "delayed trigger"),
                    "trigger_context": {
                        "trigger_count": len(matching),
                        "trigger_defending_player_index": defending,
                    },
                })
            else:
                for perm in matching:
                    events.append({
                        "controller_index": seat,
                        "source_permanent": perm,
                        "card": entry.get("card"),
                        "instruction": instruction,
                        "effect_kind": "triggered_delayed",
                        "ability_text": entry.get("source_name", "delayed trigger"),
                        "trigger_context": {
                            "trigger_defending_player_index": defending,
                        },
                    })
        if events:
            self._enqueue_triggered_batch(events)

    def can_attack(
        self,
        attacker: Permanent,
        defending_player_index: int,
        *,
        attacking_planeswalker: bool = False,
    ) -> bool:
        # *attacking_planeswalker* is CR 508.5's distinction: an attacker aimed
        # at a planeswalker still has a defending player (that planeswalker's
        # controller — passed as *defending_player_index*), but it is not
        # attacking that **player**, so a restriction scoped to attacking a
        # player (Arboria) does not reach it. Defaulted False because every
        # other restriction in this function restricts *attacking*, whichever
        # object is attacked.
        #
        # "Can attack as though it had haste" (Instill Energy) lifts CR 302.6's
        # attack clause only — not its {T}-ability clause, which is why it is a
        # restriction here rather than a haste grant.
        if self._is_summoning_sick(attacker) and not aura_restriction_active(
            attacker, "attacks_as_though_hasty"
        ):
            return False

        program = compile_card_oracle(attacker.effective_card)
        instr_kinds = {i.kind for i in program.instructions}

        # The land type is *data* on the instruction rather than baked into its
        # name: a creature printed "unless defending player controls a Mountain"
        # is the same restriction with a different type. The chain that used to
        # produce this instruction matched an exact string naming Island, so any
        # other type fell through to a bare `static_line` and the creature
        # attacked freely while still reporting supported.
        without_land = next(
            (i for i in program.instructions if i.kind == "cant_attack_without_land_type"),
            None,
        )
        if without_land is not None:
            required = str(without_land.payload.get("land_type") or "island")
            # Honor text-changed land types (Magical Hack / Phantasmal Terrain):
            # a land turned into the named type counts, matching the upkeep
            # "no_islands" check. Scoped to lands so a creature subtype like
            # "Island Fish" never satisfies the restriction.
            #
            # CR 508.1c makes restrictions cumulative — "if any restrictions are
            # being disobeyed, the declaration is illegal" — so satisfying this
            # one answers only this one. This used to `return` the answer, which
            # let a Sea Serpent attack a player under Island Sanctuary the moment
            # they controlled an Island; Sea Serpent's own clause *requires* that
            # Island, so the two cards contradict each other on exactly the board
            # where both are played, and they have shipped together since Alpha.
            # It also skipped the defender check below, so a Wall printed with
            # this clause could attack at all.
            if not any(
                perm.card.primary_type == "land" and perm.has_type(required)
                for perm in self.controlled_by(defending_player_index)
            ):
                return False

        # "…unless you control four or more artifacts" (Gadrak). The attacker's
        # *own* controller is counted, which is the difference from the land
        # clause above — and CR 508.1c keeps it cumulative for the same reason
        # that one is: satisfying this restriction answers only this one.
        without_count = next(
            (
                i for i in program.instructions
                if i.kind == "cant_attack_without_controlled_count"
            ),
            None,
        )
        if without_count is not None:
            wanted = int(without_count.payload.get("count", 0))
            card_type = str(without_count.payload.get("controlled_type") or "")
            # `has_type`, so an animated artifact land counts as the artifact it
            # currently is (CR 613 layer 4) — the same rule the land clause
            # above follows for a text-changed type.
            held = sum(
                1 for perm in self.controlled_by(self.controller_index_of(attacker))
                if perm.has_type(card_type)
            )
            if held < wanted:
                return False

        # The creature's own printed clause, and the one an Aura imposes
        # (Faith's Fetters). Asked of the Auras attached right now, so the
        # restriction ends when the Aura does without anything clearing a flag —
        # the arrangement every other entry in that table already uses.
        if "cant_attack" in instr_kinds or aura_restriction_active(
            attacker, "cant_attack"
        ):
            return False

        # The board-reaching restrictions, asked of every permanent's compiled
        # program rather than of the attacker's own — a restriction printed on
        # one permanent that reaches creatures it does not name. Asked at
        # declaration, the read that matters, so each begins and ends with the
        # permanent carrying it. CR 508.1c keeps every branch cumulative:
        # passing one restriction answers only that one.
        #
        # - "Except for creatures named Akron Legionnaire and artifact
        #   creatures, creatures you control can't attack." — scoped to the
        #   carrier's controller, exempting an exception union.
        # - "Creatures without flying can't attack." (Moat) / "Non-Eye
        #   creatures you control can't attack." (Evil Eye of Orms-by-Gore) —
        #   a described set, carried as one `subject` filter payload.
        # - Arboria's "creatures can't attack a player unless that player cast
        #   a spell or put a nontoken permanent onto the battlefield during
        #   their last turn" — a fact about the *defending player*, read off
        #   the per-seat record the turn boundary folds.
        #
        # Every noun phrase is tested by `subject_matches`, the one reader of
        # a filter payload, so a member means here exactly what it means on a
        # blocker whitelist.
        attacker_seat = self.controller_index_of(attacker)
        for source_seat, source_perm in self.permanents_with_controller():
            for instr in compile_card_oracle(source_perm.effective_card).instructions:
                if instr.kind == "controlled_creatures_cant_attack":
                    if source_seat != attacker_seat:
                        continue
                    exceptions = instr.payload.get("exceptions") or ()
                    if not any(
                        subject_matches(
                            self, attacker, dict(member),
                            observer=source_seat, source=source_perm,
                        )
                        for member in exceptions
                    ):
                        return False
                elif instr.kind == "creatures_cant_attack":
                    described = dict(instr.payload.get("subject") or {})
                    # "You control" inside the subject is relative to the
                    # permanent *carrying* the restriction (CR 109.5), which is
                    # what scopes Evil Eye to its own controller's creatures
                    # while Moat, with no controller key, reaches every seat's.
                    if subject_matches(
                        self, attacker, described,
                        observer=source_seat, source=source_perm,
                    ):
                        return False
                elif instr.kind == "cant_attack_unless_defender_acted":
                    if attacking_planeswalker:
                        # "…can't attack **a player**": a planeswalker is not
                        # one (CR 508.5), so this restriction says nothing.
                        continue
                    if not self.last_own_turn_activity.get(
                        defending_player_index, False
                    ):
                        return False

        # "This creature can't attack if it attacked during your last turn."
        # (Giant Turtle.) The record is the stamp `declare_attackers` writes on
        # every attacker — which seat attacked with it, on that seat's own turn
        # ordinal — and "your last turn" is ordinal arithmetic against the
        # current controller: the stamp names *this* seat's previous turn
        # exactly when its ordinal is one less than the seat's current one. A
        # Turtle that attacked under a thief compares against the thief's
        # seat, not yours, and attacks freely once home (the stamp's seat is
        # part of the record, not just its turn).
        if "cant_attack_if_attacked_last_turn" in instr_kinds:
            stamp = attacker.metadata.get("attacked_on_seat_turn")
            if (
                isinstance(stamp, dict)
                and stamp.get("seat") == attacker_seat
                and stamp.get("seat_turn")
                == self.seat_turn_counts.get(attacker_seat, 0) - 1
            ):
                return False

        # "That creature can't attack during its controller's next turn."
        # (Wall of Dust's block trigger.) The stamp names a seat and that
        # seat's next turn ordinal, written when the trigger resolved; the
        # restriction holds exactly while that turn is the current one, and a
        # later turn walks past it with nothing to sweep. On the permanent
        # rather than the game because the sentence restricts one creature,
        # and a creature that leaves and returns is a new object with no
        # stamp (CR 400.7).
        stamp = attacker.metadata.get("cant_attack_on_seat_turn")
        if (
            isinstance(stamp, dict)
            and stamp.get("seat") == self.active_player_index
            and stamp.get("seat_turn")
            == self.seat_turn_counts.get(self.active_player_index, 0)
        ):
            return False

        # Defender is asked of layer 6, not of the printed keyword list: a Clone
        # copying a Wall has the ability through layer 1 and a Primal Clay that
        # entered on its 1/6 Wall body has it through a layer-6 grant, and
        # neither prints the word. Both could attack while this read the card.
        # Animate Wall grants the exemption while attached
        # (auras.aura_restrictions).
        if self._has_keyword(attacker, "defender") and not self._ignores_defender(
            attacker
        ):
            return False

        # Island Sanctuary: defending player is protected from non-flying,
        # non-islandwalk attackers. Both keywords are asked through layer 6, so
        # islandwalk granted by a lord counts — reading the metadata flag and
        # the printed keyword list separately missed every other route to the
        # ability, which is the bug class tests/engine/test_layer_reads.py
        # guards.
        defending = self.players[defending_player_index]
        if defending.island_sanctuary_protected:
            if not (
                self._has_keyword(attacker, "flying")
                or self._has_keyword(attacker, "islandwalk")
            ):
                return False

        return True

    def _ignores_defender(self, attacker: Permanent) -> bool:
        """Whether *attacker* may attack "as though it didn't have defender".

        CR 609.4: an "as though" effect applies **only** to the stated effect —
        the creature still has defender for every other purpose, so this is a
        permission read here rather than a keyword the layers remove. Removing it
        would also change what a defender-narrowed filter matches
        (``subject_filters``), what layer 6 reports to the web payload, and what
        "creatures with defender" counts, none of which the card says.

        Two sources, both asked live. An attached Aura (Animate Wall) is asked of
        the Auras attached right now, and the permanent's own conditional static
        (Drowsing Tyrannodon) is asked of the board right now — the condition can
        change between layer recomputes, and declaring attackers is the read that
        matters. It is the exact twin of the ``cant_be_blocked`` conditional
        static the declare blockers step asks at block time.
        """
        if aura_restriction_active(attacker, "ignores_defender"):
            return True
        # The third source: a resolving ability that granted the permission for
        # this turn (Wall of Wonder). A flag rather than a keyword removal for
        # the reason above, and swept by the cleanup step.
        if attacker.metadata.get(ATTACK_AS_THOUGH_NO_DEFENDER):
            return True
        seat = self.controller_index_of(attacker)
        if seat is None:
            return False
        return any(
            i.kind == "conditional_static"
            and i.payload.get("ignores_defender")
            and conditional_static_holds(
                self, seat, attacker, i.payload.get("condition") or {}
            )
            for i in compile_card_oracle(attacker.effective_card).instructions
        )

    def _must_attack_if_able(self, attacker: Permanent) -> bool:
        if attacker.metadata.get("must_attack_until_eot"):
            return True
        # An Aura can impose the requirement too (Furor of the Bitten). Asked of
        # the attached Auras rather than stamped on the creature, so the
        # requirement ends when the Aura leaves and nothing has to undo it —
        # the model every other Aura restriction already follows.
        if aura_restriction_active(attacker, "must_attack_each_combat"):
            return True
        program = compile_card_oracle(attacker.effective_card)
        return any(i.kind == "must_attack_each_combat" for i in program.instructions)

    def _fire_attack_triggers(self, controller_index: int) -> None:
        """Put "whenever one or more creatures you control attack" triggers on the stack.

        Covers Raging River and similar enchantments whose ability triggers once
        when the controller declares one or more attackers (CR 508.2/508.4, 603.3).
        Per CR 508.2 these abilities are placed on the stack as the declare attackers
        step's turn-based action completes — they don't resolve immediately; the
        active player then receives priority (the caller opens that window) and the
        triggers resolve as players pass priority with the stack non-empty.
        """
        from ..game_types import StackItem

        controller = self.players[controller_index]
        # CR 802.3a: a trigger not tied to a specific defending player applies once
        # across the whole attacking group; use the first attacker's defender as a
        # deterministic representative target (the only defender in the common
        # single-defender/2-player case).
        target_index = next(iter(self.combat_attackers.values()), controller_index)
        for permanent in list(controller.battlefield):
            for trig in matching_triggers(
                permanent.effective_card, condition_kinds={"one_or_more_attack"}
            ):
                self._stack_push(
                    StackItem(
                        card=permanent.card,
                        caster_index=controller_index,
                        target_player_index=target_index,
                        target_permanent_index=None,
                        x_value=None,
                        ability_instruction=trig.instruction,
                        ability_effect_kind=trig.effect_kind,
                        source_permanent=permanent,
                        ability_text=trig.source_line,
                    )
                )
                self.log.append(f"{permanent.card.name} triggered on attack (added to stack)")

    def _fire_creature_attacks_triggers(self, controller_index: int, attacker_indices: list[int]) -> None:
        """Put each attacker's own "whenever this creature attacks" triggers on
        the stack (e.g. Mijae Djinn's coin flip) — one per attacking creature
        that has the trigger, unlike _fire_attack_triggers' once-per-declaration
        team-wide version."""
        from ..game_types import StackItem

        controller = self.players[controller_index]
        for idx in attacker_indices:
            if not (0 <= idx < len(controller.battlefield)):
                continue
            permanent = controller.battlefield[idx]
            # "attacks or blocks" (Elder Gargaroth) is the same per-creature
            # firing on each half of its union — this is the attack half, the
            # blocker-side twin in declare_blockers_step is the other.
            for trig in matching_triggers(
                permanent.effective_card,
                condition_kinds={"creature_attacks", "creature_attacks_or_blocks"},
            ):
                # "Whenever this creature attacks AND ISN'T BLOCKED" (Merchant
                # Ship, Pirate Ship riders) can't be evaluated until blockers
                # exist — deferred to _fire_unblocked_attack_triggers at the
                # combat damage step.
                if "isn't blocked" in (trig.source_line or "").lower():
                    continue
                self._stack_push(
                    StackItem(
                        card=permanent.card,
                        caster_index=controller_index,
                        # The attacker's own controller/index, so the coin-flip
                        # handler can remove IT from combat without re-deriving
                        # who owns it.
                        target_player_index=controller_index,
                        target_permanent_index=idx,
                        x_value=None,
                        ability_instruction=trig.instruction,
                        ability_effect_kind=trig.effect_kind,
                        source_permanent=permanent,
                        ability_text=trig.source_line,
                    )
                )
                self.log.append(f"{permanent.card.name} triggered on attack (added to stack)")

    def _announce_attack_declaration(
        self, controller_index: int, declared: list[Permanent]
    ) -> None:
        """The declaration itself (CR 508.1), once, carrying *who* attacked.

        The fourth attack-trigger shape and the only one that is about the
        *group*: "whenever you attack with two or more creatures with flying"
        (Tide Skimmer) and "whenever this creature and at least two other
        creatures attack" (Makeshift Battalion) both ask how many attackers
        there were, which no per-creature announcement can answer — the other
        three fire once per declaration for one card's ability, once per
        attacker's own ability, and once per attacker to the whole board.

        The attackers ride the payload rather than being re-derived from
        ``combat_attackers`` at the filter: the trigger is about the declaration
        as it was announced, and a later removal renumbers that map.
        """
        emit(self, "attackers_declared", seat=controller_index, attackers=list(declared))
        # "Whenever an **opponent** attacks with creatures" (Mangara). The same
        # declaration asked from the other side, so it is announced here rather
        # than given a site of its own — and it carries, per seat, how many of
        # the batch are aimed at that seat, because CR 603.4's intervening-if
        # asks about the declaration and a recount at resolution would see a
        # combat that had moved on.
        aimed: dict[int, int] = {}
        for attacker in declared:
            defender = self._defender_seat_of(attacker)
            if defender is not None:
                aimed[defender] = aimed.get(defender, 0) + 1
        emit(
            self, "opponent_attackers_declared",
            seat=controller_index, attackers=list(declared), aimed_by_seat=aimed,
        )

    def _defender_seat_of(self, attacker: "Permanent") -> int | None:
        """Which seat *attacker* is attacking — the player, or the controller of
        the planeswalker it is aimed at.

        Both count as attacking that player for Mangara's purposes, which is
        what its "you and/or planeswalkers you control" says, so one lookup
        answers both halves.
        """
        index = next(
            (i for i, perm in enumerate(self.controlled_by(
                self.controller_index_of(attacker) or 0
            )) if perm is attacker),
            None,
        )
        if index is None:
            return None
        walker_id = self.combat_attacked_planeswalkers.get(index)
        if walker_id is not None:
            walker = self.permanent_by_id(walker_id)
            return self.controller_index_of(walker) if walker is not None else None
        return self.combat_attackers.get(index)

    def _fire_matching_creature_attacks_triggers(
        self, declared: list[Permanent]
    ) -> None:
        """"Whenever a creature you control with deathtouch attacks …" (Hooded
        Blightfang) — once for each declared attacker that answers the trigger's
        own subject filter.

        The third of the three attack-trigger shapes, and the only one whose
        source need not be attacking: ``_fire_attack_triggers`` fires once for
        the whole declaration, ``_fire_creature_attacks_triggers`` fires an
        attacker's own ability, and this one announces *each attacker* to the
        whole board. That is what the event bus is for — the announcement is
        game-wide and the narrowing is the trigger's own noun phrase, so no
        card is named here.
        """
        for attacker in declared:
            emit(self, "matching_creature_attacks", subject=attacker)

    # ------------------------------------------------------------------
    # Banding declaration (CR 702.22)
    # ------------------------------------------------------------------

    def _creature_has_banding(self, permanent: Permanent) -> bool:
        """Whether a creature currently has banding (printed or granted)."""
        if permanent.has_keyword("banding"):
            return True
        return self._has_keyword(permanent, "banding")

    def _validate_attacking_bands(
        self,
        bands: list[list[int]] | None,
        attacker_indices: list[int],
        controller: PlayerState,
    ) -> tuple[list[list[int]], str | None]:
        """Validate declared attacking bands (CR 702.22c). Returns (bands, error).

        A band is one or more attacking creatures with banding plus up to one
        attacking creature without banding; each creature may join only one band.
        """
        if not bands:
            return [], None
        attacker_set = set(attacker_indices)
        seen: set[int] = set()
        validated: list[list[int]] = []
        for group in bands:
            members = sorted(set(group))
            if len(members) < 2:
                return [], "a band must contain at least two creatures"
            banding_count = 0
            nonbanding_count = 0
            for idx in members:
                if idx not in attacker_set:
                    return [], "every band member must be a declared attacker"
                if idx in seen:
                    return [], "a creature may belong to only one band"
                seen.add(idx)
                if self._creature_has_banding(controller.battlefield[idx]):
                    banding_count += 1
                else:
                    nonbanding_count += 1
            if banding_count < 1:
                return [], "a band needs at least one creature with banding"
            if nonbanding_count > 1:
                return [], "a band may include at most one creature without banding"
            validated.append(members)
        return validated, None
