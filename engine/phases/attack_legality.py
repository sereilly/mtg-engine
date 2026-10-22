from __future__ import annotations

"""Attack legality (CR 508.1a–d).

Whether a creature can attack (``can_attack``: every restriction a card, an
Aura, a static ability or a permission puts on it, and whether what it costs
to attack can be paid), the requirements on a declaration ("attacks each
combat if able", "also attacks if able" beside another attacker, CR 508.1d),
and whether a declared *set* of attackers is legal
(``attack_declaration_refusal``: the CR 508.1c restrictions only a whole
declaration can disobey — "can only attack alone", a cap per defending
player, "unless at least two other creatures attack").

Split out of ``DeclareAttackersStepMixin``, which declares the attack and pays
for it, and composed onto ``Game`` directly after it; each side calls the
other through ``self``.
"""

from ..aura_restrictions import aura_restriction_active
from ..combat_permissions import (ATTACK_AS_THOUGH_NO_DEFENDER,
                                  ATTACKS_AS_THOUGH_NO_DEFENDER,
                                  CANT_ATTACK_UNTIL_EOT)
from ..combat_restrictions import (declaration_company_required,
                                   declaration_companion_required,
                                   declaration_greater_power_required,
                                   declaration_tap_costs,
                                   defender_attack_cap,
                                   participation_cap,
                                   restriction_condition_holds)
from ..mana_payment import plan_payment
from ..subject_filters import subject_matches
from ..models import Permanent
from ..oracle import compile_card_oracle
from ..static_bonuses import conditional_static_holds
from ..turn_state import (attacked_during_seats_last_turn,
                          marked_for_this_turn, stamped_turn_is_now,
                          CANT_ATTACK_ON_SEAT_TURN_KEY,
                          MUST_ATTACK_ON_SEAT_TURN_KEY)


class AttackLegalityMixin:
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
        program = compile_card_oracle(attacker.effective_card)
        instr_kinds = {i.kind for i in program.instructions}

        if self._is_summoning_sick(attacker) and not aura_restriction_active(
            attacker, "attacks_as_though_hasty"
        ):
            # "This creature can attack as though it had haste **unless it
            # entered this turn**." (Chaos Lord.) The creature's own printed
            # permission, beside the Aura-granted one (Instill Energy) — and
            # the exception is read off the *entry* stamp, never off summoning
            # sickness: this card changes controller every upkeep and
            # `_sync_control` rewrites that stamp, so asking it would answer
            # "it entered this turn" because of the control change the ability
            # exists to cause, and the permission would never once apply.
            if not (
                "attacks_as_though_hasty_unless_it_entered" in instr_kinds
                and not self.entered_this_turn(attacker)
            ):
                return False

        # What the defending player controls, and which answer forbids the
        # attack. Both are *data*: "unless … an Island" (Sea Serpent) and "if …
        # an untapped creature with power 3 or greater" (Goblin Mutant) are one
        # question under two polarities, and the noun is a whole printed phrase
        # rather than the five basic land words this used to hold. That
        # narrowing was the enforcement's, not the card's — the scan matched a
        # land by name — so a creature naming anything else had nowhere to go.
        #
        # `subject_matches` is the one reader of a filter payload, so a text
        # changed land type (Magical Hack, Phantasmal Terrain) counts here for
        # the same reason it counts everywhere else, and no re-scoping to lands
        # is needed: CR 205.3i puts a land subtype only on a land.
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
        defender_board = next(
            (
                i for i in program.instructions
                if i.kind == "cant_attack_unless_defender_controls"
            ),
            None,
        )
        if defender_board is not None:
            described = dict(defender_board.payload.get("subject") or {})
            held = any(
                subject_matches(
                    self, perm, described,
                    # CR 109.5: "you" inside the noun phrase would be the
                    # ability's controller, which is the attacker's seat — not
                    # the defender whose board is being scanned. The scan picks
                    # the board; the observer answers the phrase.
                    observer=self.controller_index_of(attacker),
                    source=attacker,
                )
                for perm in self.controlled_by(defending_player_index)
            )
            if held is not bool(defender_board.payload.get("required", True)):
                return False

        # "…can't attack or block unless you tap an untapped creature you
        # control not declared as an attacking … creature this combat." (Hollow
        # Warrior.) CR 508.1h's cost, asked here of this creature alone: with
        # no other untapped creature to tap, it cannot attack at all. Whether
        # several such creatures can be paid for *together* is the declaration's
        # question (`attack_declaration_refusal`), as the sacrifice plan's is.
        if declaration_tap_costs(attacker, "attack") and self.declaration_tap_plan(
            self.controller_index_of(attacker), [attacker], "attack"
        ) is None:
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

        # "…unless you control **more lands than defending player**."
        # (Monstrous Hound.) The two clauses above each scan *one* board — the
        # defender's, or the attacker's controller's — and this one compares
        # them, which is why it is its own kind rather than a payload on either.
        # CR 508.1c keeps it cumulative like both of them: satisfying this
        # restriction answers only this one.
        #
        # Counted through `subject_matches`, so "lands" here means what it means
        # on every other printed noun phrase — an animated land is still a land
        # (CR 305.7), and a card printing "more creatures than" would be counted
        # through layer 4 without this site knowing the noun changed. The
        # observer is the attacker's controller on *both* scans, because the
        # phrase is the card's and CR 109.5 makes "you" its controller; only the
        # board being scanned differs.
        outnumber = next(
            (
                i for i in program.instructions
                if i.kind == "cant_attack_unless_you_control_more"
            ),
            None,
        )
        if outnumber is not None:
            described = dict(outnumber.payload.get("subject") or {})
            mine_seat = self.controller_index_of(attacker)

            def _counted(seat: int | None) -> int:
                return sum(
                    1 for perm in self.controlled_by(seat)
                    if subject_matches(
                        self, perm, described, observer=mine_seat, source=attacker
                    )
                )

            if _counted(mine_seat) <= _counted(defending_player_index):
                return False

        # "…unless you've cast a creature spell this turn." (Mogg Conscripts.)
        # CR 506.1 asked of a *window* rather than of a board, so it reads the
        # per-turn cast record instead of scanning permanents — and it reads the
        # **attacker's controller's** record, which is what "you" means on a
        # creature's own text (CR 109.5). A creature stolen this turn is held to
        # its new controller's casts, not to the caster's.
        #
        # CR 508.1c keeps it cumulative for the reason the two clauses above
        # are: satisfying this restriction answers only this one.
        after_cast = next(
            (
                i for i in program.instructions
                if i.kind == "cant_attack_unless_you_cast"
            ),
            None,
        )
        if after_cast is not None:
            from ..cast_restrictions import spells_cast_matching

            seat = self.controller_index_of(attacker)
            described = dict(after_cast.payload.get("spell_filter") or {})
            if seat is None or not spells_cast_matching(self, seat, described):
                return False

        # The creature's own printed clause, and the one an Aura imposes
        # (Faith's Fetters). Asked of the Auras attached right now, so the
        # restriction ends when the Aura does without anything clearing a flag —
        # the arrangement every other entry in that table already uses.
        #
        # Read as an *instruction* rather than out of `instr_kinds`, because the
        # clause can be qualified: "…**if there's another creature on the
        # battlefield**" (Shauku, Endbringer) is the same restriction with a
        # condition, and a kind-set read drops the condition and grounds the
        # creature for good. Every printed clause separately, because CR 508.1c
        # makes restrictions cumulative — one whose condition is false answers
        # only itself. The Aura form carries no condition, so it is asked
        # unqualified exactly as before.
        for restriction in program.instructions:
            if restriction.kind != "cant_attack":
                continue
            if restriction_condition_holds(
                self,
                restriction.payload.get("condition"),
                # CR 109.5: "you" inside the noun phrase is the seat whose
                # ability this is, which is the attacker's controller.
                observer=self.controller_index_of(attacker),
                defender=defending_player_index,
                # "Another" is measured against the permanent whose line this
                # is — the attacker itself.
                source=attacker,
            ):
                return False
        if aura_restriction_active(attacker, "cant_attack"):
            return False
        # And the granted half (Change of Heart): a restriction a spell put on
        # this one creature for the turn, swept by the cleanup step. Read
        # beside the two above because all three answer the same question about
        # the attacker, and a reader that knew only two of them would let the
        # third through — which is the mirror of the note the blocker gate
        # keeps about Panic.
        if attacker.metadata.get(CANT_ATTACK_UNTIL_EOT):
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
                elif instr.kind == "creatures_cant_attack_you":
                    # "Black creatures can't attack you." (Elephant Grass.) The
                    # sibling of `creatures_cant_attack` above with one thing
                    # more: a **defender**. "You" is the seat controlling the
                    # permanent that prints it (CR 109.5), so the restriction
                    # only speaks about an attack aimed at that seat — which is
                    # the whole of what separates this enchantment from a Moat.
                    # Read here rather than as a payload flag on that kind,
                    # because the two ask different questions of the board and a
                    # flag one branch ignored would ground every attack.
                    if source_seat != defending_player_index:
                        continue
                    if subject_matches(
                        self, attacker,
                        dict(instr.payload.get("subject") or {}),
                        observer=source_seat, source=source_perm,
                    ):
                        return False
                elif instr.kind == "creatures_that_attacked_last_turn_cant_attack":
                    # "Creatures that attacked during their controller's last
                    # turn can't attack." (Halls of Mist.) Giant Turtle's
                    # question asked of the board rather than of one creature,
                    # so it is read here in the scan rather than off the
                    # attacker's own program — and asked of the **attacker's**
                    # seat, not the Halls' controller's, because "their
                    # controller" is whose creature it is. One reader with the
                    # self form (`turn_state.attacked_during_seats_last_turn`),
                    # so a creature that attacked under a thief is answered the
                    # same way both cards ask it.
                    if attacker_seat is not None and attacked_during_seats_last_turn(
                        self, attacker, attacker_seat
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
            if attacked_during_seats_last_turn(self, attacker, attacker_seat):
                return False

        # "This creature can't attack unless you sacrifice two Islands."
        # (Leviathan.) CR 508.1h: an additional cost to attack. This is the
        # *gate* half — a cost its controller cannot pay makes the attack
        # illegal — and `_attack_costs_of` is the one reader, shared with the
        # charge in `declare_attackers`, so the declaration can never be
        # accepted and then left unpaid (or paid and then rejected).
        for cost in self._attack_costs_of(attacker):
            if len(self._sacrifice_candidate_indices(
                self.players[attacker_seat], dict(cost.get("filter") or {}), attacker
            )) < int(cost.get("count", 1)):
                return False

        # "Enchanted creature can't attack unless its controller pays {3}."
        # (Brainwash.) The mana twin, and asked here as well as over the whole
        # declaration because this predicate is what "attacks each combat **if
        # able**" reads: a creature whose cost its controller cannot cover is
        # not able, and enforcing a requirement against it would make a legal
        # declaration impossible. The declaration-wide check in
        # `declare_attackers` is what adds several attackers' costs together;
        # this one answers only for this creature, which is all a per-creature
        # predicate can honestly say.
        for cost in self._attack_mana_costs_of(
            attacker,
            None if attacking_planeswalker else defending_player_index,
        ):
            if plan_payment(
                self.players[attacker_seat].mana_pool,
                [
                    land
                    for land in self.payment_lands(attacker_seat)
                    if land is not attacker
                ],
                cost, payer=self.players[attacker_seat],
            ) is None:
                return False

        # One-shot blanket restrictions ("Creatures can't attack this turn",
        # Festival), the attack twin of `blocking_restrictions_until_eot`.
        # Asked here rather than stamped on each creature so a creature that
        # entered after the spell resolved is caught too, and tested through
        # `subject_matches` — the one reader of a filter payload — so the noun
        # phrase means here exactly what it means anywhere else. CR 508.1c
        # keeps it cumulative: passing every other restriction answers only
        # those.
        for entry in self.attack_restrictions_until_eot:
            # "**During that player's next turn**, … other creatures can't
            # attack." (Oracle en-Vec.) The same blanket restriction over a turn
            # that had not started when the ability resolved, so the entry
            # carries a `turn_state` window stamp and is inert on every other
            # turn. Asked before the noun phrase, which is what makes an entry
            # waiting for a later turn cost nothing on this one.
            # A toll is not a ban. "Creatures can't attack **unless their
            # controller pays {X}**" (War Tax) is CR 508.1c's second half — a
            # restriction with a condition that can be met — so its entry is
            # filed here beside the blanket ones and answered as a *cost*, by
            # ``_attack_mana_costs_of`` and the gate above that already asked
            # whether this seat can cover it. Read as a prohibition it would
            # ground every creature the noun phrase names, which on War Tax is
            # the board.
            if entry.get("toll"):
                continue
            window = entry.get("on_seat_turn")
            if window is not None and not stamped_turn_is_now(self, window):
                continue
            # "**Other** creatures can't attack" — other than the set the
            # sentence in front of it chose. That set is fixed because the
            # choice was made as the ability resolved (CR 608.2), which is a
            # different question from the restriction's own reach: CR 611.2c
            # gives a rules-modifying continuous effect every object there is,
            # including one that arrived afterwards, which is exactly why the
            # entry is state on the game and only the *exclusion* is a list.
            # By ``permanent_id`` rather than by object, because the exclusion
            # outlives the turn the ids were recorded in and a creature that
            # left and returned is a new object the sentence never named
            # (CR 400.7).
            if attacker.permanent_id in (entry.get("except_permanent_ids") or ()):
                continue
            # "**Only** creatures in the pile of their choice can attack this
            # turn." (Fight or Flight.) A restriction on one player's
            # creatures — the player whose creatures were separated — so the
            # entry names that seat and is inert for everybody else's. A seat
            # rather than a ``controller`` key in the filter, for the reason
            # the toll reader below gives: the entry is a record on the game,
            # so there is no observer whose "you" the phrase could mean.
            scoped_seat = entry.get("controller_seat")
            if scoped_seat is not None and self.controller_index_of(attacker) != scoped_seat:
                continue
            if subject_matches(self, attacker, dict(entry.get("filter") or {})):
                return False

        # "That creature can't attack during its controller's next turn."
        # (Wall of Dust's block trigger.) The stamp names a seat and that
        # seat's next turn ordinal, written when the trigger resolved; the
        # restriction holds exactly while that turn is the current one, and a
        # later turn walks past it with nothing to sweep. On the permanent
        # rather than the game because the sentence restricts one creature,
        # and a creature that leaves and returns is a new object with no
        # stamp (CR 400.7).
        if marked_for_this_turn(self, attacker, CANT_ATTACK_ON_SEAT_TURN_KEY):
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
        # …and the creature's own **unconditional** static: "This creature can
        # attack as though it didn't have defender." (the ability a kicked
        # Prison Barricade enters with). Read off ``effective_card`` so a line
        # the permanent was *granted* counts exactly as a printed one would,
        # and asked before the seat check below because it depends on nobody's
        # board.
        if any(
            i.kind == ATTACKS_AS_THOUGH_NO_DEFENDER
            for i in compile_card_oracle(attacker.effective_card).instructions
        ):
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
        ) or self._board_grants_defender_permission(attacker)

    def _board_grants_defender_permission(self, attacker: Permanent) -> bool:
        """The fourth source: a permanent naming a *class* of creatures.

        "Wall creatures can attack as though they didn't have defender."
        (Rolling Stones.) Printed on an enchantment nobody is attacking with,
        so it is found by scanning the board rather than read off the
        attacker's own program — the permission twin of ``creatures_cant_attack``
        one method up, over the same ``subject`` payload and through the same
        ``subject_matches``.

        The observer is the seat whose ability this is (CR 109.5), so a
        "creatures **you** control" printing would reach that seat's Walls
        rather than the attacker's.
        """
        for source_perm in self.all_permanents():
            source_seat = self.controller_index_of(source_perm)
            for instr in compile_card_oracle(
                source_perm.effective_card
            ).instructions:
                if instr.kind != "subject_ignores_defender":
                    continue
                if subject_matches(
                    self, attacker, dict(instr.payload.get("subject") or {}),
                    observer=source_seat, source=source_perm,
                ):
                    return True
        return False

    def _must_attack_if_able(self, attacker: Permanent) -> bool:
        if attacker.metadata.get("must_attack_until_eot"):
            return True
        # "**During that player's next turn**, the chosen creatures attack if
        # able" (Oracle en-Vec). The same CR 508.1d requirement the mark above
        # carries, over a turn that had not started when the ability resolved —
        # so it is the seat-turn stamp rather than the cleanup-swept flag, which
        # would have been gone a whole turn before the requirement applied.
        if marked_for_this_turn(self, attacker, MUST_ATTACK_ON_SEAT_TURN_KEY):
            return True
        # An Aura can impose the requirement too (Furor of the Bitten). Asked of
        # the attached Auras rather than stamped on the creature, so the
        # requirement ends when the Aura leaves and nothing has to undo it —
        # the model every other Aura restriction already follows.
        if aura_restriction_active(attacker, "must_attack_each_combat"):
            return True
        program = compile_card_oracle(attacker.effective_card)
        if any(i.kind == "must_attack_each_combat" for i in program.instructions):
            return True
        # "**Creatures you control** attack each combat if able." (the Pirate
        # token Pursued Whale gives each opponent.) CR 508.1d's requirement
        # printed on one permanent about a *set* of others, so it is found by a
        # board scan rather than on the attacker itself — the exact arrangement
        # `can_attack` already has for `creatures_cant_attack`, the restriction
        # that says the opposite, and read the same way: every noun phrase goes
        # through `subject_matches` with the *carrier's* seat as CR 109.5's
        # "you", which is what scopes the token's line to its own controller's
        # creatures while a card printing no controller word would reach every
        # seat's.
        #
        # Until this scan existed the token's second line compiled to a bare
        # `static_line` and obliged nobody: it could not block, which is
        # enforced, and was under no obligation to attack, which was not.
        for source_seat, source_perm in self.permanents_with_controller():
            for instr in compile_card_oracle(
                source_perm.effective_card
            ).instructions:
                if instr.kind != "creatures_must_attack":
                    continue
                if subject_matches(
                    self, attacker, dict(instr.payload.get("subject") or {}),
                    observer=source_seat, source=source_perm,
                ):
                    return True
        return False

    def _must_attack_beside(
        self, attacker: Permanent, declared: "list[Permanent]"
    ) -> bool:
        """""If a creature you control attacks, this creature **also** attacks
        if able." (Ekundu Cyclops.)

        CR 508.1d's requirement with a condition about the declaration rather
        than about the board, which is the whole reason it is not one more row
        in :meth:`_must_attack_if_able`: that predicate sees one creature and
        cannot be told who else was named.

        The condition is tested against the *other* declared attackers. "Also"
        is what says so — a lone Cyclops would otherwise be the creature its
        own condition names, and the requirement would demand it attack because
        it is attacking. Identity, not value: two Cyclopes are two permanents
        and each answers for the other, and ``is`` is the only comparison that
        can tell them apart (idiom #11).

        Through ``subject_matches`` with the requirement's own seat as CR 109.5's
        observer, so "you control" means the seat whose printed line this is —
        the same reader every other noun phrase in the combat steps goes
        through.
        """
        seat = self.controller_index_of(attacker)
        if seat is None:
            return False
        program = compile_card_oracle(attacker.effective_card)
        for restriction in program.instructions:
            if restriction.kind != "must_attack_if_partner_attacks":
                continue
            described = restriction.payload.get("subject") or {}
            if any(
                other is not attacker
                and subject_matches(
                    self, other, described, observer=seat, source=attacker
                )
                for other in declared
            ):
                return True
        # "**If a creature with a magnet counter on it attacks**, all creatures
        # with magnet counters on them attack if able." (Magnetic Web.) The
        # same conditional requirement printed on one permanent about a *set*
        # of others, so it is found by a board scan rather than on the attacker
        # itself — the arrangement `_must_attack_if_able` above already has for
        # the unconditional form and `can_attack` has for the restriction.
        #
        # Both noun phrases go through `subject_matches` with the **carrier's**
        # seat as CR 109.5's "you", so a card printing "creatures you control"
        # in either half would mean the seat whose permanent this is.
        # `other is not attacker` is what keeps the requirement from being
        # self-satisfying: a lone magnetized attacker is the creature its own
        # condition names, and without the identity check it would be compelled
        # to attack because it is attacking (idiom #11 — two magnetized
        # creatures are two permanents and each answers for the other).
        for source_seat, source_perm in self.permanents_with_controller():
            for instr in compile_card_oracle(
                source_perm.effective_card
            ).instructions:
                if instr.kind not in (
                    "creatures_must_attack_if_partner_attacks",
                    # "**If this creature attacks**, all creatures you control
                    # attack if able." (Viashino Bey.) The same scan and the
                    # same compelled set; only the condition differs, and it
                    # differs in kind rather than in payload — what has to be
                    # attacking is the permanent printing the line, which no
                    # noun phrase names. Answered by identity below.
                    "creatures_must_attack_if_source_attacks",
                ):
                    continue
                if not subject_matches(
                    self, attacker, dict(instr.payload.get("subject") or {}),
                    observer=source_seat, source=source_perm,
                ):
                    continue
                if instr.kind == "creatures_must_attack_if_source_attacks":
                    # ``is``, never ``in``: ``Permanent`` compares by value, so
                    # a second Bey — or an opponent's copy of the same
                    # catalog-shared card — would answer for this one and
                    # compel a board whose own Bey stayed home (idiom #11).
                    if any(other is source_perm for other in declared):
                        return True
                    continue
                condition = dict(instr.payload.get("condition_subject") or {})
                if any(
                    other is not attacker
                    and subject_matches(
                        self, other, condition,
                        observer=source_seat, source=source_perm,
                    )
                    for other in declared
                ):
                    return True
        return False

    def attack_declaration_refusal(
        self,
        declared_attackers: list[Permanent],
        *,
        defenders: "dict[int, int | None] | None" = None,
    ) -> "tuple[Permanent, str] | None":
        """Which declared attacker's restriction this **set** disobeys, and why.

        CR 508.1c asks its restrictions of the declaration as a whole — "if any
        restrictions are being disobeyed, the declaration is illegal" — so none
        of these can live in `can_attack`, a per-creature predicate with no way
        to say "and nobody else" (Errantry's "can only attack alone"), "and at
        least two more of you" (Orcish Conscripts), or "and no more of you"
        (Caverns of Despair, Crawlspace).

        **Public, and returning the offending permanent, because the AI asks it
        too.** `ai_policy.choose_attackers` builds its set out of
        `legal_attackers`, which is that per-creature predicate — so it happily
        proposed a set the declaration then refused *whole*, and a Conscripts
        beside one Bear grounded the Bear as well. A second reading of the rule
        inside the AI would drift from this one; the permanent is what lets the
        AI drop the creature it named instead.

        **The two caps used to be outside this predicate, and that is what W2G4
        fixed.** They were checked inline in `declare_attackers` and nowhere
        else, so the AI's prune could not see them: it proposed an over-cap set,
        the declaration refused it whole, and
        `web/combat_prompts._ai_declare_attackers` fell through its superset
        fallback (also over the cap) to `[]` — the seat attacked with nobody,
        for the rest of the game. The failure is *conservative*, no rule is
        broken and nothing is spent, which is exactly why it went unnoticed
        under both a shipped card (Caverns of Despair, since Legends) and a new
        one (Crawlspace).

        *defenders* maps a declared attacker's `permanent_id` to the seat it is
        attacking, or to `None` when it is attacking a planeswalker (CR 508.1b —
        not attacking the player, so outside a per-defender cap). It is a
        keyword because the two caps ask different questions: the global one
        needs no map at all, and the per-defender one cannot be answered without
        it. A caller that omits it in a game with exactly one living opponent
        gets that opponent, which is every two-player game and therefore every
        declaration the AI builds today; a caller that omits it with a genuine
        multi-seat choice gets the global cap only, and the declaration's own
        call always supplies the map, so the *gate* is never the one falling
        back.

        Asked of the collected `Permanent` objects rather than of indices: an
        index is unstable, and both callers have the objects already.
        """
        # The board-wide cap first: it is the widest restriction here — it does
        # not care who is attacking or whom — so it is the cheapest true answer
        # and naming any other offender under it would be arbitrary in a
        # different way.
        cap = participation_cap(self.all_permanents(), "attack")
        if cap is not None and len(declared_attackers) > cap:
            return declared_attackers[-1], (
                f"no more than {cap} creature(s) can attack each combat"
            )
        aimed = self._attacks_per_defender(declared_attackers, defenders)
        for seat, attackers in sorted(aimed.items()):
            seat_cap = defender_attack_cap(self.controlled_by(seat))
            if seat_cap is not None and len(attackers) > seat_cap:
                return attackers[-1], (
                    f"no more than {seat_cap} creature(s) can attack "
                    f"{self.players[seat].name} each combat"
                )
        if len(declared_attackers) > 1:
            for lone in declared_attackers:
                if self._can_only_attack_alone(lone):
                    return lone, f"{lone.card.name} can only attack alone"
        for attacker in declared_attackers:
            needed = declaration_company_required(attacker, "attack")
            if needed is not None and len(declared_attackers) - 1 < needed:
                return attacker, (
                    f"{attacker.card.name} needs at least {needed} other "
                    "attacking creature(s)"
                )
        # "…unless a creature with **greater power** also attacks." (Okk.) The
        # same CR 508.1c question asked as a comparison rather than a count, so
        # it is answered here beside its sibling and not in `can_attack`.
        #
        # Power is read live off both creatures rather than off their printed
        # numbers: CR 613 computes it, so an Okk that has been pumped needs a
        # bigger companion than one that has not, and a companion pumped in
        # response qualifies. `is` rather than an index comparison, because the
        # rule is about the *other* attackers and two 3/3s are not one another.
        for attacker in declared_attackers:
            if not declaration_greater_power_required(attacker, "attack"):
                continue
            if not any(
                other is not attacker
                and other.effective_power > attacker.effective_power
                for other in declared_attackers
            ):
                return attacker, (
                    f"{attacker.card.name} needs an attacking creature with "
                    "greater power beside it"
                )
        # "…unless **a black or green creature** also attacks." (Scarred Puma.)
        # The same CR 508.1c question with a described companion. "Also" is
        # "other than this one" — `is`, for the reason given above — and the
        # description is tested through `subject_matches`, so the companion's
        # colour is the layers' answer at the moment of the declaration.
        for attacker in declared_attackers:
            for described in declaration_companion_required(attacker):
                seat = self.controller_index_of(attacker)
                if not any(
                    other is not attacker
                    and subject_matches(
                        self, other, described, observer=seat, source=attacker
                    )
                    for other in declared_attackers
                ):
                    return attacker, (
                        f"{attacker.card.name} can't attack unless a creature "
                        "its text names also attacks"
                    )
        # "…unless you tap an untapped creature you control not declared as an
        # attacking creature this combat." (Hollow Warrior.) A cost every one of
        # them pays out of the same board, so the plan is asked of the whole
        # set; the creature it names is the last one owing, which is the one the
        # AI's prune drops.
        owing = [a for a in declared_attackers if declaration_tap_costs(a, "attack")]
        if owing:
            seat = self.controller_index_of(owing[0])
            if seat is None or self.declaration_tap_plan(
                seat, declared_attackers, "attack"
            ) is None:
                return owing[-1], (
                    f"{owing[-1].card.name} has no untapped creature left to tap "
                    "for its attack"
                )
        return None

    def _attacks_per_defender(
        self,
        declared_attackers: list[Permanent],
        defenders: "dict[int, int | None] | None",
    ) -> "dict[int, list[Permanent]]":
        """Which declared attackers are attacking each defending **player**.

        The per-defender cap's tally, and only its tally: an attacker aimed at a
        planeswalker is not attacking the player (CR 508.1b) and is left out, so
        a Crawlspace never refuses a declaration whose extra attackers are all
        pointed at a Garruk.

        With no map, every attacker is aimed at the one living opponent when
        there is exactly one — the same shorthand `declare_attackers` itself
        takes for a two-player game — and at nobody when the choice is genuine,
        because guessing a seat there would refuse a legal declaration.
        """
        if defenders is not None:
            aimed: dict[int, list[Permanent]] = {}
            for attacker in declared_attackers:
                seat = defenders.get(attacker.permanent_id)
                if seat is None:
                    continue
                aimed.setdefault(seat, []).append(attacker)
            return aimed
        if not declared_attackers:
            return {}
        controller = self.controller_index_of(declared_attackers[0])
        if controller is None:
            return {}
        living = self.opponents_of(controller)
        if len(living) != 1:
            return {}
        return {living[0]: list(declared_attackers)}

    def _can_only_attack_alone(self, attacker: Permanent) -> bool:
        """CR 506.5 — whether *attacker* may attack only as the sole attacker.

        Printed on the creature (a `combat_restrictions` row) or granted by an
        Aura (Errantry), and read through the same two seams every other combat
        restriction here goes through, so neither spelling is enforced without
        the other.
        """
        if aura_restriction_active(attacker, "can_only_attack_alone"):
            return True
        program = compile_card_oracle(attacker.effective_card)
        return any(i.kind == "can_only_attack_alone" for i in program.instructions)
