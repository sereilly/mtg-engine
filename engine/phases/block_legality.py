from __future__ import annotations

"""Block legality (CR 509.1a–c).

Whether a creature can block an attacker (``_can_block_attacker``: every
restriction on the pair, evasion and the landwalk reading beside it, and
whether a toll to block can be paid), how many attackers one creature may
block (``_max_blocks_for``), the fewest and most creatures an attacker may be
blocked by, what the board compels to block (CR 509.1c), and whether a
declared *set* of blockers is legal (``block_declaration_refusal``: the
CR 509.1b restrictions only a whole declaration can disobey).

Split out of ``DeclareBlockersStepMixin``, which declares the blocks and pays
for them, and composed onto ``Game`` directly after it; each side calls the
other through ``self``.
"""

from ..auras import (attached_block_ceiling, attached_combat_restrictions,
                     aura_restriction_active)
from ..combat_permissions import (ADDITIONAL_BLOCKS_UNTIL_EOT,
                                  CAN_BLOCK_ANY_NUMBER_UNTIL_EOT,
                                  CANT_BLOCK_ATTACKERS_UNTIL_EOT,
                                  CANT_BLOCK_UNTIL_EOT, printed_block_ceiling)
from ..combat_restrictions import (declaration_company_required,
                                  declaration_greater_power_required,
                                  declaration_tap_costs,
                                  participation_cap,
                                  restriction_condition_holds)
from ..evasion_negation import negated_evasion_abilities
from ..landwalk import LANDWALK, land_satisfies, landwalk_requirement
from ..mana_payment import plan_payment
from ..layer_bridge import computed_abilities
from ..subject_filters import subject_matches
from ..models import Permanent
from ..oracle import compile_card_oracle
from ..static_bonuses import conditional_static_holds


# Landwalk is not a fixed word list any more: what the defender must control is
# the ability's printed **quality**, and CR 702.14a lets that quality be a land
# subtype welded into the word ("islandwalk") or a supertype standing in front
# of the family word ("legendary landwalk", Livonya Silone). `engine/landwalk.py`
# reads both into one requirement, and the same reader admits the printed line
# in `engine.oracle` — so a quality nothing here can test keeps its card
# unsupported instead of shipping evasion that never applies.


class BlockLegalityMixin:
    def _max_blocks_for(self, blocker: Permanent) -> int:
        """How many attackers this creature may block at once (CR 509.1b). Normally
        1; each "can block an additional creature" grant (Two-Headed Giant of
        Foriys) adds one. Blaze of Glory grants "can block any number of creatures",
        modeled as effectively unlimited.

        The printed grant is counted over the compiled program's **static**
        lines, not over the whole oracle text. The same sentence is printed as
        an *activated* ability ("{W}: This creature can block an additional
        creature this turn.", Mounted Archers), and a text scan cannot tell the
        two apart -- it would hand that creature the extra block every combat,
        for free and whether or not the ability was ever activated, which is
        the "works more often than the card allows" failure rather than a
        missing one. The activated printing arrives instead through
        ``ADDITIONAL_BLOCKS_UNTIL_EOT`` below, written by its handler and swept
        with the turn.
        """
        if blocker.metadata.get(CAN_BLOCK_ANY_NUMBER_UNTIL_EOT):
            return 1_000_000
        printed = printed_block_ceiling(
            compile_card_oracle(blocker.effective_card).static_lines
        )
        # "That creature can block up to two additional creatures this turn."
        # (Yare.) A granted ceiling, added to the printed one for CR 509.1b's
        # reason: restrictions and the permissions that lift them are
        # cumulative, so a creature whose own line already blocks an additional
        # one keeps that and gains these.
        granted = int(blocker.metadata.get(ADDITIONAL_BLOCKS_UNTIL_EOT, 0) or 0)
        # "Enchanted creature can block any number of creatures." (Entangler.)
        # The printed permission one sentence-subject over, asked of the Auras
        # attached right now, so it ends when the Aura leaves.
        attached = attached_block_ceiling(blocker)
        return 1 + printed + granted + attached

    def block_declaration_refusal(
        self,
        declared_blockers: list[Permanent],
    ) -> "tuple[Permanent, str] | None":
        """Which declared blocker's restriction this **set** disobeys, and why.

        CR 509.1b asks its restrictions of the declaration as a whole — "if any
        restrictions are being disobeyed, the declaration of blockers is
        illegal" — so none of these can live in ``_can_block_attacker``, a
        per-pair predicate with no way to say "and no more of you" (Caverns of
        Despair), "and at least two more of you" (Orcish Conscripts, and Mogg
        Flunkies' printed "can't block alone") or "and one of you bigger than
        me" (Okk).

        **Public, and returning the offending permanent, because the AI asks it
        too.** This is the blocking twin of
        :meth:`attack_declaration_refusal`, and it is written from the same
        defect: until this existed the three checks were inline in
        ``declare_blockers`` and nowhere else, so ``choose_combat_blockers``
        pruned against nothing. It proposed an over-cap map, the declaration
        refused it *whole*, ``ai_combat.declare_ai_blockers`` fell through to
        ``{}`` and ``web/game_flow`` to a safety valve that wipes every seat's
        blocks — the defender blocked with nobody, this combat and every later
        one, with no rule broken, nothing spent and nothing logged. The
        permanent is what lets the AI drop the creature this names instead.

        **One defending player's declaration, and only theirs (CR 802.4b).**
        These three checks used to add every *other* seat's ``combat_blockers``
        to their totals, on the reading that "each combat" spans the whole
        combat and a creature blocking under an earlier declaration does not
        stop being a blocker. CR 802.4b says the opposite in as many words:
        "When determining whether a defending player's blocks are legal, ignore
        any creatures attacking other players and **any blocking creatures
        controlled by other players**." So under a Caverns of Despair each
        defender may block with two, and the engine was refusing the second
        defender's legal declaration outright — a restriction firing more often
        than the rules allow, which is the same silent wrongness as one firing
        less often, pointed the other way. It is also why this takes a list and
        not a seat: once the other seats' blockers are ignored there is nothing
        left for a seat index to select.

        Asked of the collected ``Permanent`` objects rather than of indices: an
        index is unstable, and both callers have the permanents already.

        The Camouflage exemption is the **caller's**, not this predicate's: the
        piles were matched at random (CR 509.1a is replaced wholesale), so
        there is no declaration to declare illegal, and the declaration gate
        already skips this beside the four requirement checks it skips for the
        same reason.
        """
        # The board-wide cap first, for the reason the attack side takes it
        # first: it is the widest restriction here — it does not care who is
        # blocking or what they block — so it is the cheapest true answer, and
        # naming any other offender under it would be arbitrary in a different
        # way. The **last** blocker in the list is named, which makes the order
        # the caller hands them over in the caller's policy:
        # ``_legal_block_declaration`` sorts its worst block last, so a cap
        # drops that one.
        #
        # The permanents scanned are the whole board (``all_permanents``), not
        # one seat's: CR 802.4b scopes which *blockers* are counted, not where
        # the permanent printing the cap is allowed to sit.
        cap = participation_cap(self.all_permanents(), "block")
        if cap is not None and len(declared_blockers) > cap:
            return declared_blockers[-1], (
                f"no more than {cap} creature(s) can block each combat"
            )
        for blocker in declared_blockers:
            needed = declaration_company_required(blocker, "block")
            if needed is not None and len(declared_blockers) - 1 < needed:
                return blocker, (
                    f"{blocker.card.name} needs at least {needed} other "
                    "blocking creature(s)"
                )
        # "…unless a creature with **greater power** also blocks." (Okk.) The
        # comparison twin of the count above, and the same CR 509.1b
        # declaration-wide question.
        #
        # Power is read live off both creatures rather than off their printed
        # numbers: CR 613 computes it, so a pumped Okk needs a bigger companion
        # than one that has not been. ``is`` rather than an index comparison,
        # because the rule is about the *other* blockers and two 3/3s are not
        # one another.
        for blocker in declared_blockers:
            if not declaration_greater_power_required(blocker, "block"):
                continue
            if not any(
                other is not blocker
                and other.effective_power > blocker.effective_power
                for other in declared_blockers
            ):
                return blocker, (
                    f"{blocker.card.name} needs a blocking creature with "
                    "greater power beside it"
                )
        # "…unless you tap an untapped creature you control not declared as a
        # blocking creature this combat." (Hollow Warrior.) The attack side's
        # plan, asked of this defender's set (CR 802.4b scopes it to their own
        # blockers, which is all the list holds).
        owing = [b for b in declared_blockers if declaration_tap_costs(b, "block")]
        if owing:
            seat = self.controller_index_of(owing[0])
            if seat is None or self.declaration_tap_plan(
                seat, declared_blockers, "block"
            ) is None:
                return owing[-1], (
                    f"{owing[-1].card.name} has no untapped creature left to tap "
                    "for its block"
                )
        return None

    def _minimum_blockers(self, attacker: Permanent) -> int:
        """How many creatures must block *attacker* at once, or 1 if any may.

        CR 509.1b: every restriction applies, so the answer is the **largest**
        minimum any of them imposes — a creature with menace and Gorilla
        Berserkers' line needs three blockers, not two, and taking the first
        match would have made the second restriction free.

        Menace is read as a keyword (CR 702.111a defines it as exactly this
        sentence with N=2) and the printed template as a restriction, because
        that is how each is written on a card; both answer the same question,
        and one caller asking it once is what stops the two disagreeing.
        """
        minimum = 2 if self._has_keyword(attacker, "menace") else 1
        for restriction in (
            *compile_card_oracle(attacker.effective_card).instructions,
            *attached_combat_restrictions(attacker),
        ):
            if restriction.kind != "cant_be_blocked_by_fewer_than":
                continue
            minimum = max(minimum, int(restriction.payload.get("count", 1)))
        return minimum

    def _maximum_blockers(self, attacker: Permanent) -> int | None:
        """How many creatures may block *attacker* at once, or None if any may.

        "This creature can't be blocked by more than one creature." (Stalking
        Tiger.) The ceiling to :meth:`_minimum_blockers`' floor, and the
        **smallest** ceiling wins for the same CR 509.1b reason the largest
        minimum does: every restriction applies, so obeying only the loosest
        would let a declaration break the tighter one.
        """
        caps = [
            int(restriction.payload.get("count", 1))
            for restriction in (
                *compile_card_oracle(attacker.effective_card).instructions,
                *attached_combat_restrictions(attacker),
            )
            if restriction.kind == "cant_be_blocked_by_more_than"
        ]
        # "Each creature you control can't be blocked by more than one
        # creature." (Familiar Ground.) The same ceiling printed on a
        # *permanent* about a described set, so it is found by scanning the
        # board rather than read off the attacker's own program — and it is
        # collected into the same list, because CR 509.1b makes every
        # restriction apply and the smallest ceiling is still the answer.
        #
        # "You control" inside the noun phrase is relative to the permanent
        # printing it (CR 109.5), which is what scopes Familiar Ground to its
        # own controller's creatures; `observer` is that seat and `source` is
        # that permanent, exactly as the attack-side scan one file over asks.
        for source_seat, source_perm in self.permanents_with_controller():
            for instr in compile_card_oracle(
                source_perm.effective_card
            ).instructions:
                if instr.kind != "matching_cant_be_blocked_by_more_than":
                    continue
                if subject_matches(
                    self, attacker, dict(instr.payload.get("subject") or {}),
                    observer=source_seat, source=source_perm,
                ):
                    caps.append(int(instr.payload.get("count", 1)))
        return min(caps) if caps else None

    def _board_compels_block(self, blocker: Permanent) -> bool:
        """The board-reaching half of Watchdog's requirement.

        "All creatures block each combat if able." (Invasion Plans.) Printed on
        an enchantment nobody is blocking with, so it is found by scanning the
        board rather than read off the blocker's own program — the requirement
        twin of ``creatures_cant_block`` in ``_can_block_attacker`` and the
        block-side mirror of ``_must_attack_if_able``'s ``creatures_must_attack``
        scan, over the same ``subject`` payload and the same ``subject_matches``.

        The observer is the seat whose ability this is (CR 109.5), so a
        "creatures **you** control" printing would compel that seat's creatures
        rather than the blocker's controller's.
        """
        for source_perm in self.all_permanents():
            source_seat = self.controller_index_of(source_perm)
            for instr in compile_card_oracle(
                source_perm.effective_card
            ).instructions:
                if instr.kind != "creatures_must_block":
                    continue
                if subject_matches(
                    self, blocker, dict(instr.payload.get("subject") or {}),
                    observer=source_seat, source=source_perm,
                ):
                    return True
        return False

    def _can_block_attacker(self, blocker: Permanent, attacker: Permanent) -> bool:
        if attacker.metadata.get("cant_be_blocked_until_eot"):
            return False

        # One-shot blanket restrictions ("Creatures without flying can't block
        # this turn", Destructive Tampering). Keywords are asked of layer 6, so
        # a creature granted flying after the spell resolved may block.
        for entry in self.blocking_restrictions_until_eot:
            # A toll is not a ban. "Creatures can't block **unless their
            # controller pays {X}**" (War Cadence) is CR 509.1b's second half —
            # a restriction with a condition that can be met — so its entry sits
            # here beside the blanket ones and is answered as a *cost*, by
            # ``_block_toll_of`` and the gate below. Read as a prohibition it
            # would stop every creature the noun phrase names from blocking at
            # all, which on War Cadence is the whole defending board.
            if entry.get("toll"):
                continue
            # "**Only** creatures in the chosen piles can block this turn."
            # (Stand or Fall.) The blocking twin of the attack gate's two
            # readings, in the same order and for the same reasons: the
            # creatures a resolution *named* are excepted by id (CR 400.7 — one
            # that left and returned is a new object the sentence never named),
            # and an entry scoped to one player's creatures is inert for every
            # other seat's.
            if blocker.permanent_id in (entry.get("except_permanent_ids") or ()):
                continue
            scoped_seat = entry.get("controller_seat")
            if scoped_seat is not None and self.controller_index_of(blocker) != scoped_seat:
                continue
            # The noun phrase through ``subject_matches``, the one reader of a
            # filter payload — the attack gate's twin read. It spelled out
            # three fields (a type and two keyword lists) and so could not
            # test a colour: "Green creatures and white creatures can't block
            # this turn" (Flash of Defiance) refused rather than reaching both.
            # No observer: the entry is a record on the game, and the
            # lowering admits only what the object alone answers.
            if subject_matches(self, blocker, dict(entry.get("filter") or {})):
                return False

        # **The blocker's own restriction, which nothing asked.**
        # "This creature can't block." compiled to a `cant_block` instruction,
        # reported the card supported, and was read by no one — the comment in
        # `engine/combat_restrictions.py` named this file as the enforcement
        # site, and this file had never mentioned the kind. Every question below
        # is about the *attacker*, which is how a restriction on the blocker
        # came to have no home at all.
        #
        # Off the effective card, like every other read here: a Clone of a
        # creature that can't block can't block either (CR 707.2).
        blocker_program = compile_card_oracle(blocker.effective_card)
        # Read as an *instruction* rather than out of a kind set, exactly as the
        # attack gate reads its twin and for the same reason: the clause can be
        # qualified — "…**if an enchantment is on the battlefield**" (Wirecat) —
        # and a kind-set membership test drops the condition and stops the
        # creature blocking for good. Every printed clause separately, because
        # CR 509.1b makes restrictions cumulative: one whose condition is false
        # answers only itself.
        for restriction in blocker_program.instructions:
            if restriction.kind != "cant_block":
                continue
            if restriction_condition_holds(
                self,
                restriction.payload.get("condition"),
                # CR 109.5: "you" inside the noun phrase is the seat whose
                # ability this is, which is the blocker's controller. The
                # defending player *is* that seat in this engine's combats, and
                # is passed as such rather than assumed equal.
                observer=self.controller_index_of(blocker),
                defender=self.controller_index_of(blocker),
                # "Another" is measured against the permanent whose line this
                # is — the blocker itself.
                source=blocker,
            ):
                return False
        # And the Aura-imposed half (Faith's Fetters).
        if aura_restriction_active(blocker, "cant_block"):
            return False
        # And the granted half (Panic): a restriction a spell put on this one
        # creature for the turn, swept by the cleanup step. Read beside the two
        # above because all three answer the same question about the blocker,
        # and a reader that knew only two of them would let the third through.
        if blocker.metadata.get(CANT_BLOCK_UNTIL_EOT):
            return False
        # And the *named-attacker* half (Duct Crawler): "can't block **this
        # creature** this turn" denies one pairing rather than every block, so
        # it is asked here — where the pair is in hand — rather than beside the
        # three blanket reads above. By ``permanent_id``, so an attacker that
        # left and came back is a new object the old denial does not name
        # (CR 400.7).
        denied_attackers = blocker.metadata.get(CANT_BLOCK_ATTACKERS_UNTIL_EOT)
        if denied_attackers and attacker.permanent_id in denied_attackers:
            return False

        # And the board-wide half: "Creatures with flying can't attack **or
        # block**…" (Katabatic Winds). A restriction printed on a permanent
        # that reaches every creature on every battlefield, so it is found by
        # scanning the board rather than read off the blocker's own program —
        # the block twin of `creatures_cant_attack` in
        # `attack_legality.can_attack`, over the same `subject` payload
        # and asked through the same one filter reader. "You control" inside
        # that phrase is relative to the permanent carrying the restriction
        # (CR 109.5), which is what the observer seat says.
        for source_seat, source_perm in self.permanents_with_controller():
            for instr in compile_card_oracle(source_perm.effective_card).instructions:
                if instr.kind != "creatures_cant_block":
                    continue
                if subject_matches(
                    self, blocker, dict(instr.payload.get("subject") or {}),
                    observer=source_seat, source=source_perm,
                ):
                    return False

        # "This creature can't block unless you control **more lands than
        # attacking player**." (Monstrous Hound.) The blocker's own comparison
        # between two boards, read off its program beside the three blanket
        # denials above rather than beside the attacker questions below —
        # nothing about the attacker enters it except which seat declared it.
        #
        # The seat compared against is the attacker's controller rather than the
        # active player: CR 508.1a makes them the same in every combat this
        # engine can build, and reading it off the attacker is the answer that
        # stays right if a creature changes hands mid-combat. Counted through
        # `subject_matches` with the blocker's controller as observer, for the
        # attack twin's reason — the phrase is the blocker's card's, so "you" is
        # its controller (CR 109.5).
        outnumber = next(
            (
                i for i in blocker_program.instructions
                if i.kind == "cant_block_unless_you_control_more"
            ),
            None,
        )
        if outnumber is not None:
            described = dict(outnumber.payload.get("subject") or {})
            mine_seat = self.controller_index_of(blocker)
            theirs_seat = self.controller_index_of(attacker)

            def _counted(seat: int | None) -> int:
                return sum(
                    1 for perm in self.controlled_by(seat)
                    if subject_matches(
                        self, perm, described, observer=mine_seat, source=blocker
                    )
                )

            if theirs_seat is None or _counted(mine_seat) <= _counted(theirs_seat):
                return False

        attacker_program = compile_card_oracle(attacker.effective_card)
        attacker_kinds = {i.kind for i in attacker_program.instructions}

        # "This creature can't be blocked." (Phantom Warrior.) Read as an
        # *instruction* rather than out of the kind set, exactly as the
        # ``cant_block`` gate above reads its twin and for the same reason: the
        # clause can be qualified — "…**as long as defending player controls an
        # artifact**" (Bouncing Beebles) — and a kind-set membership test drops
        # the condition and makes the creature unblockable for good. Every
        # printed clause separately, because CR 509.1b makes restrictions
        # cumulative: one whose condition is false answers only itself.
        for restriction in attacker_program.instructions:
            if restriction.kind != "cant_be_blocked":
                continue
            if restriction_condition_holds(
                self,
                restriction.payload.get("condition"),
                # CR 109.5: "you" inside the noun phrase is the attacker's
                # controller, whose card this is. "Defending player" is the seat
                # being attacked, which for a legal block is the blocker's
                # controller (CR 509.1a) — read off the blocker rather than the
                # combat map because that is the seat this call is deciding for.
                observer=self.controller_index_of(attacker),
                defender=self.controller_index_of(blocker),
                source=attacker,
            ):
                return False
        if any(
            # "Enchanted creature can't be blocked." (Cloak of Mists.) The
            # attached channel of the same restriction, asked beside the
            # attacker's own program for the reason `cant_block` above is asked
            # both ways: the sentence is one rule, and a reader that knew only
            # the printed half would enforce it for Phantom Warrior and not for
            # the creature an Aura made unblockable.
            restriction.kind == "cant_be_blocked"
            for restriction in attached_combat_restrictions(attacker)
        ):
            return False

        # "This creature can't be blocked **as long as it's attacking alone**."
        # (Dream Prowler.) CR 506.5's condition, asked at the declaration
        # rather than materialized on a recompute — for the reason the
        # conditional static below is: the answer changes the moment another
        # attacker joins or leaves, and blocking is the read that matters.
        # ``creature_attacking_alone`` is the one reader of the rule, shared
        # with Errantry's attack-side restriction.
        if (
            "cant_be_blocked_while_attacking_alone" in attacker_kinds
            and self.creature_attacking_alone(attacker)
        ):
            return False

        # "This creature can't be blocked as long as …" (Tome Anima). Asked
        # now rather than materialized on a recompute, because the condition
        # can change between recomputes and blocking is the read that matters.
        attacker_seat = self.controller_index_of(attacker)
        if attacker_seat is not None and any(
            cs.kind == "conditional_static"
            and cs.payload.get("cant_be_blocked")
            and conditional_static_holds(
                self, attacker_seat, attacker, cs.payload.get("condition") or {}
            )
            for cs in attacker_program.instructions
        ):
            return False

        attacker_has_flying = self._has_keyword(attacker, "flying")
        blocker_has_flying = self._has_keyword(blocker, "flying")
        blocker_has_reach = self._has_keyword(blocker, "reach")
        if attacker_has_flying and not (blocker_has_flying or blocker_has_reach):
            return False

        # Fear: attacker can't be blocked except by artifact creatures and/or black creatures
        attacker_has_fear = self._has_keyword(attacker, "fear")
        if attacker_has_fear:
            # Both halves through the layers: an animated artifact is an
            # artifact creature (613 layer 4) and a laced creature is black
            # (layer 5). No card in this pool has fear, so nothing here is
            # observable yet — which is exactly why it was written against the
            # printed card and never noticed.
            is_artifact_creature = blocker.is_creature and blocker.has_type("artifact")
            is_black_creature = "B" in blocker.effective_colors
            if not (is_artifact_creature or is_black_creature):
                return False

        # Shadow (CR 702.28b), and it is the only evasion ability in this
        # function that restricts **both** creatures. "A creature with shadow
        # can't be blocked by creatures without shadow, and a creature without
        # shadow can't be blocked by creatures with shadow." Two prohibitions in
        # one sentence, which is why the test is an inequality rather than the
        # `attacker_has_x and not blocker_has_x` shape flying and fear use six
        # lines up: a shadow creature is *unable to block the ground*, and a
        # reading that kept only the first half would turn a printed drawback
        # into pure evasion — silently, and in the player's favour.
        #
        # Both reads through layer 6, like every other keyword here, so a
        # granted shadow (Dauthi Embrace, Shadow Rift) and a removed one
        # (Reality Anchor) are answered by the same two lines.
        attacker_has_shadow = self._has_keyword(attacker, "shadow")
        blocker_has_shadow = self._has_keyword(blocker, "shadow")
        if blocker_has_shadow and not attacker_has_shadow:
            return False
        if attacker_has_shadow and not blocker_has_shadow:
            # "This creature can block creatures with shadow as though it had
            # shadow." (Heartwood Dryad, Wall of Diffusion.) A permission over
            # the *first* half only, so it is asked here and not folded into
            # `blocker_has_shadow` above: the Dryad does not have shadow, and a
            # reading that pretended it did would forbid it from blocking the
            # ground creatures it is printed to stop. CR 702.28b is two
            # prohibitions and this text lifts exactly one of them.
            if not any(
                restriction.kind == "can_block_as_though_it_had"
                and restriction.payload.get("keyword") == "shadow"
                for restriction in (
                    *blocker_program.instructions,
                    *attached_combat_restrictions(blocker),
                )
            ):
                return False

        # Protection (CR 702.16f): an attacking creature with protection from a
        # quality can't be blocked by creatures that have that quality.
        if self._is_protected_from(attacker, blocker):
            return False

        # "…can't be blocked by Walls" / "…by artifact creatures" — one
        # restriction whose noun phrase is payload (engine/combat_restrictions).
        # It used to be a Wall-only kind tested with a literal `has_type("wall")`;
        # the phrase is a filter now, so Argothian Pixies and Artifact Ward cost
        # a table row rather than a second branch here.
        #
        # Asked of `subject_matches`, which reads the layer system: an animated
        # artifact land *is* an artifact creature (613 layer 4) and Primal Clay's
        # third body *is* a Wall, and the printed line says otherwise for both.
        # An Aura prints the same restriction about the creature it is attached
        # to (Artifact Ward), so the two channels are unioned here rather than
        # asked in two places: the restriction is the same sentence and the
        # difference is only whose text it is printed on.
        #
        # ``subject_matches`` is the module-level import at the top of this
        # file. It was re-imported here, which made the name *local to this
        # whole function* — so the board scan added above, several screens
        # earlier in the same body, raised ``UnboundLocalError`` on the first
        # blocker it was asked about. A function-level re-import of a name the
        # module already has is not a no-op.

        # "Target creature can't be blocked by Walls **this turn**" (Tower of
        # Coireall): the same restriction granted for a turn rather than printed
        # on the attacker. A third channel beside the two below rather than a
        # branch of its own, because the class of blocker is the same filter
        # payload in all three — the difference is only where the record lives.
        from ..combat_restrictions import (
            granted_blocker_filters,
            granted_blocker_whitelists,
        )

        for described in granted_blocker_filters(attacker):
            if subject_matches(self, blocker, described):
                return False

        # "Target creature can't be blocked this turn **except by Walls**."
        # (Joven's Tools.) The granted *whitelist*, and its own loop for the
        # reason the static whitelist below has its own branch: a blocker
        # matching no member of the union is illegal, where the blacklist above
        # only rejects the ones that do match.
        #
        # Every grant separately, because each is its own restriction
        # (CR 509.1b): two of them must both be satisfied, and a blocker legal
        # under either one alone is not legal under both.
        for allowed in granted_blocker_whitelists(attacker):
            if not any(
                subject_matches(self, blocker, described) for described in allowed
            ):
                return False

        for restriction in (
            *attacker_program.instructions,
            *attached_combat_restrictions(attacker),
        ):
            # "…can't be blocked **except by** X" (Elven Riders, Evil Eye of
            # Orms-by-Gore, Seeker). The inverse of the restriction below, and
            # its own branch because it is a *whitelist*: a blocker matching no
            # member of the union is illegal, where the restriction below only
            # rejects blockers that do match. An empty union never reaches here
            # — `combat_restriction_for` refuses a phrase it cannot parse
            # rather than admitting one that would allow everything.
            if restriction.kind == "cant_be_blocked_except_by":
                allowed = restriction.payload.get("allowed_blockers") or ()
                if not any(
                    subject_matches(
                        self, blocker, described,
                        observer=self.controller_index_of(attacker),
                        source=attacker,
                    )
                    for described in allowed
                ):
                    return False
                continue
            if restriction.kind != "cant_be_blocked_by":
                continue
            # "…**as long as defending player controls a snow land**."
            # (Arctic Foxes.) A qualifier on the restriction, stripped once in
            # `combat_restrictions` rather than written into every row — and
            # asked here, because a condition read at the gate and ignored at
            # the enforcement would be an evasion ability that applies on every
            # board. The seat "defending player" names is the blocker's
            # controller; "you" is the attacker's, CR 109.5's observer for the
            # ability this text is.
            if not restriction_condition_holds(
                self,
                restriction.payload.get("condition"),
                observer=self.controller_index_of(attacker),
                defender=self.controller_index_of(blocker),
            ):
                continue
            # The printed noun phrase, already read into subject filters by
            # `combat_restrictions._blocker_union` — the same vocabulary the
            # whitelist form above uses. This used to be four payload keys
            # translated back into filter keys by four branches here: two
            # vocabularies for one thing, so a noun both parsers could read
            # needed a capture *and* a branch, and without the branch the
            # restriction was parsed and never applied.
            #
            # Every field still goes through `subject_matches`, so the layers
            # answer: a Grizzly Bears laced red is a red creature, an animated
            # artifact is an artifact creature, and a pumped 2/2 has power 4.
            # The restriction belongs to the *attacker* (its own printed line,
            # or an Aura's about the creature it enchants), so CR 109.5's
            # observer is the attacker's controller and the ability's source is
            # the attacker itself. Passed here rather than left out because
            # `_blocker_union` admits the whole testable key set: a phrase
            # narrowed by "you control" or by "another" would otherwise be
            # carried into a call that cannot answer it and silently dropped,
            # which on a blocking restriction is a block the card forbids.
            for described in restriction.payload.get("blocker_filters") or ():
                if subject_matches(
                    self, blocker, described,
                    observer=self.controller_index_of(attacker), source=attacker,
                ):
                    return False

        # Invisibility's "can't be blocked except by Walls" used to be its own
        # aura restriction and its own check here. It is not any more: the loop
        # above reads the whitelist form through the same subject rewrite as
        # every other attached restriction, so Invisibility, Seeker and Elven
        # Riders are one rule printed on three different kinds of card.

        # "Can't block creatures with power N or greater" (Ironclaw Orcs),
        # "…white creatures with power 2 or greater" (Orcish Veteran). The
        # printed noun phrase rides on the payload rather than the instruction
        # kind, read through the same `subject_matches` the blocked-by
        # restriction above uses — so the layers answer here too: a pumped 2/2
        # has power 4 and a creature laced white is a white creature.
        # An Aura prints the same restriction about the creature it is attached
        # to (Ironclaw Curse), so the two channels are unioned here exactly as
        # they are for the blocked-by restriction above: one sentence, and the
        # only difference is whose text it is on.
        blocker_program = compile_card_oracle(blocker.effective_card)
        for restriction in (
            *blocker_program.instructions,
            *attached_combat_restrictions(blocker),
        ):
            if restriction.kind != "cant_block_subject":
                continue
            for described in restriction.payload.get("blockee_filters") or ():
                if subject_matches(
                    self, attacker, described,
                    observer=self.controller_index_of(blocker), source=blocker,
                ):
                    return False

        # "...can't block creatures with power 3 or greater **unless you pay
        # {1}**." (Hipparion.) CR 509.1b's restriction with CR 509.1d's cost
        # hung off it. This is the *gate* half - a cost the defender cannot
        # cover makes the block illegal - and `_block_mana_costs_of` is the one
        # reader, shared with the charge in `declare_blockers`, so a block can
        # never be accepted and then left unpaid.
        #
        # Per-creature, which is all a per-pair predicate can honestly say: the
        # declaration-wide check adds several blockers' costs together, the way
        # `_declaration_mana_plan` does on the attack side.
        blocker_seat = self.controller_index_of(blocker)
        # "Nonblue creatures can't block creatures you control **unless their
        # controller pays 1 life for each blocking creature they control**."
        # (Heat Wave.) CR 509.1d's cost paid in life rather than mana, and the
        # per-creature half of it — this predicate can honestly say "you could
        # afford this one", and the declaration below adds up the creatures.
        if blocker_seat is not None:
            owed = self._block_life_cost_of(blocker, attacker)
            # CR 119.4: a player may pay N life only with a life total of at
            # least N. Asked here so an unpayable toll makes the block illegal
            # rather than being discovered at the charge, where CR 509 has
            # already locked the declaration in.
            if owed and self.players[blocker_seat].life < owed:
                return False
        if blocker_seat is not None:
            # The turn-scoped toll (War Cadence), owed once for this creature
            # rather than once per attacker it blocks — see ``_block_toll_of``.
            # Gated here as well as charged below for the reason every other
            # cost in this file is: a per-pair predicate is what "blocks if
            # able" reads, and a defender who cannot cover the toll is not able.
            toll = self._block_toll_of(blocker)
            if toll and plan_payment(
                self.players[blocker_seat].mana_pool,
                self.payment_lands(blocker_seat),
                toll, payer=self.players[blocker_seat],
            ) is None:
                return False
            for cost in self._block_mana_costs_of(blocker, attacker):
                if plan_payment(
                    self.players[blocker_seat].mana_pool,
                    self.payment_lands(blocker_seat),
                    cost, payer=self.players[blocker_seat],
                ) is None:
                    return False
            # "…unless you tap an untapped creature you control not declared as
            # a blocking creature this combat." (Hollow Warrior.) The tap cost,
            # gated for this creature alone like the mana above; several at
            # once are `block_declaration_refusal`'s question.
            if declaration_tap_costs(blocker, "block") and self.declaration_tap_plan(
                blocker_seat, [blocker], "block"
            ) is None:
                return False

        # "This creature can block only creatures with flying." (Shacklegeist.)
        # The mirror of the restriction above: that one names what may not be
        # blocked, this names the only thing that may — so an attacker *without*
        # the word is what fails. Asked of layer 6, so a creature granted flying
        # can be blocked by it and one that lost flying cannot.
        #
        # "**Enchanted creature** can block only creatures with flying." (Air
        # Bladder.) The same sentence printed on an Aura about its host, so the
        # attached channel is unioned in exactly as it is for
        # ``cant_block_subject`` above — one rule, and the only difference is
        # whose text it is printed on. Every one of them is asked: CR 509.1b
        # makes restrictions cumulative, and two of them naming two keywords
        # both have to be met.
        for only_with in (
            *blocker_program.instructions,
            *attached_combat_restrictions(blocker),
        ):
            if only_with.kind != "can_block_only_with_keyword":
                continue
            if not self._has_keyword(
                attacker, str(only_with.payload.get("required_keyword") or "")
            ):
                return False

        # "Creatures with flying can block only creatures with flying."
        # (Chaosphere.) The restriction above printed about the board, so it is
        # found by scanning every permanent rather than read off the blocker —
        # the source is a World Enchantment nobody is attacking or blocking, and
        # the sentence says "creatures", so it reaches both seats' creatures
        # including its own controller's.
        #
        # Both halves through ``subject_matches``, with **no** observer: neither
        # noun phrase names a seat, and passing one would let a future "creatures
        # you control" printing silently mean the wrong board. CR 509.1b keeps
        # every such restriction cumulative, so each one is asked separately.
        for permanent in self.all_permanents():
            for restriction in compile_card_oracle(
                permanent.effective_card
            ).instructions:
                if restriction.kind != "subject_can_block_only":
                    continue
                if not subject_matches(
                    self, blocker, restriction.payload.get("subject") or {}
                ):
                    continue
                if not subject_matches(
                    self, attacker, restriction.payload.get("allowed") or {}
                ):
                    return False

        # "**Blue creatures** can't block creatures you control." (Heat Wave.)
        # CR 509.1b's restriction printed about a described *set* of blockers
        # rather than about the permanent carrying it, so it is found by the
        # same board scan the block-only restriction above needs and for the
        # same reason: the source is an enchantment nobody is attacking or
        # blocking.
        #
        # The observer is the seat controlling the **restricting permanent**,
        # not the blocker's: "creatures **you** control" on the blockee half is
        # that seat's "you" (CR 109.5), and this is precisely the card that
        # proves it — read with the blocker's seat it would protect the wrong
        # player's creatures, which in a duel is the opposite of the printed
        # card.
        for source_seat, source_perm in self.permanents_with_controller():
            for restriction in compile_card_oracle(
                source_perm.effective_card
            ).instructions:
                if restriction.kind != "subject_cant_block_subject":
                    continue
                if not subject_matches(
                    self, blocker, restriction.payload.get("subject") or {},
                    observer=source_seat, source=source_perm,
                ):
                    continue
                for described in restriction.payload.get("blockee_filters") or ():
                    if subject_matches(
                        self, attacker, described,
                        observer=source_seat, source=source_perm,
                    ):
                        return False

        # Landwalk (CR 702.14): the attacker can't be blocked if the defending
        # player controls a land of the matching basic type. The blocker is one of
        # the defending player's creatures, so its controller is the defender.
        if self._attacker_has_active_landwalk(attacker, blocker):
            return False

        return True

    def _negated_evasion_abilities(self) -> frozenset[str]:
        """Evasion abilities that currently restrict no block at all, because
        some permanent on the battlefield says they don't (CR 509.1b).

        "Creatures with islandwalk can be blocked as though they didn't have
        islandwalk" (Undertow and its seven Legends siblings). The source is a
        permanent nobody is attacking or blocking, so this is asked of the
        **board** rather than of the attacker — and of every permanent, not
        only the defender's: the sentence says "creatures", so an Undertow its
        own controller is attacking through switches off their islandwalk too.
        """
        negated: set[str] = set()
        for perm in self.all_permanents():
            negated.update(negated_evasion_abilities(perm.effective_card.oracle_text or ""))
        return frozenset(negated)

    def _attacker_has_active_landwalk(self, attacker: Permanent, blocker: Permanent) -> bool:
        defender_index = self.controller_index_of(blocker)
        if defender_index is None:
            return False
        negated = self._negated_evasion_abilities()
        # Every ability the attacker currently has, asked one at a time whether
        # it is a landwalk — rather than a fixed table of walk words, which
        # could not hold a quality-first one. Computed through CR 613 layer 6,
        # so a landwalk granted by an Aura (Burrowing, Fishliver Oil) counts
        # alongside a printed one and ends when the Aura does, without this
        # reader knowing an Aura exists; the `has_<walk>` metadata flags an
        # older channel stamped are collected into layer 6 too.
        for ability in sorted(computed_abilities(attacker)):
            requirement = landwalk_requirement(ability)
            if requirement is None:
                continue
            # Switched off for blocking, but **not removed** — CR 702.14b makes
            # landwalk an evasion ability and this text lifts the restriction it
            # creates, nothing more. `_has_keyword` still answers True
            # everywhere else, which is why the skip lives here rather than as a
            # layer-6 removal.
            # A named ability ("islandwalk") or the whole family, which is what
            # "creatures with **landwalk abilities**" negates (Staff of the
            # Ages). The family marker covers a *qualified* landwalk too — "snow
            # forestwalk" is a landwalk, and `requirement` is not None precisely
            # because it is one.
            if ability in negated or LANDWALK in negated:
                continue
            for perm in self.controlled_by(defender_index):
                if land_satisfies(perm, requirement):
                    return True
        return False
