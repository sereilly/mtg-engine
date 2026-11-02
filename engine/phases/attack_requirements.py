from __future__ import annotations

"""Attack requirements (CR 508.1d), and the maximisation that judges by them.

"The active player checks each creature they control to see whether it's
affected by any requirements (effects that say a creature attacks if able, or
that it attacks if some condition is met). If the number of requirements that
are being obeyed is fewer than the maximum possible number of requirements that
could be obeyed without disobeying any restrictions, the declaration of
attackers is illegal. If a creature can't attack unless a player pays a cost,
that player is not required to pay that cost, even if attacking with that
creature would increase the number of requirements being obeyed."

The twin of ``block_requirements.py`` one step of combat earlier, in the same
three parts, one per clause of that sentence:

* **What is required** — :meth:`AttackRequirementsMixin.attack_requirements`,
  every requirement on the active player's creatures, one
  :class:`AttackRequirement` per source: the creature's own printed line
  (Juggernaut), an Aura's (Furor of the Bitten), a permanent's about a set
  (Grand Melee, the Pirate token Pursued Whale gives away), a resolved spell's
  or ability's mark for the turn (Boiling Blood, Siren's Call, Norritt) or for
  a later turn (Oracle en-Vec) — and the **conditional** ones, "attacks if
  some condition is met": Ekundu Cyclops ("if a creature you control
  attacks"), Magnetic Web ("if a creature with a magnet counter on it
  attacks") and Viashino Bey ("if this creature attacks").
* **The most that can be obeyed** — :meth:`~AttackRequirementsMixin.
  _most_obeyed_attack_declaration`, a search over the declarations that
  disobey no restriction and pay no cost.
* **The comparison** — :meth:`~AttackRequirementsMixin.
  attack_requirement_refusal`, the declaration gate, and
  :meth:`~AttackRequirementsMixin.obeying_attack_declaration`, the AI's.

**What this replaced.** One loop in ``declare_attackers`` asked each undeclared
creature whether it was compelled and could have attacked *a player* — and
cleared every requirement the moment a cap was reached. So under Dueling
Grounds a plain creature attacking alone beside an "attacks each combat if
able" one was accepted (CR 508.1d's own example says only the compelled one
may attack); two compelled creatures and a plain one under Caverns of Despair
could send the plain one; a creature that could attack only a planeswalker
(Arboria, Web of Inertia, Propaganda's controller's Garruk) was never
compelled; and its cost clause knew only Hollow Warrior's tap, so Juggernaut
under Propaganda was compelled to attack and pay.

**How a conditional requirement counts.** CR 508.1d defines a requirement as an
effect that says a creature "attacks if some condition is met"; a declaration
in which the condition is not met does not disobey it, so it counts as obeyed
there, and it is disobeyed only by a declaration that meets the condition and
leaves the creature home. Read the other way — counted only where the condition
holds — every Ekundu Cyclops would compel its controller to attack with
*something*, because the declaration that meets the condition and obeys it
would always outnumber the one that does neither.

**Which creatures carry one.** A requirement is counted only on a creature able
to obey it: untapped (CR 508.1a), and able to attack something — a player or a
planeswalker — without paying a cost (the sentence above; Juggernaut's ruling,
2022-12-08: "If there's a cost associated with having it attack, you're not
forced to pay that cost, so it doesn't have to attack in that case either").
A requirement on a creature that is not able imposes nothing in any
declaration — and for a conditional one, counting it would forbid meeting its
condition (a summoning-sick Ekundu Cyclops would ground every other creature).

**Why a search, and not a matching.** For ``block_requirements.py``'s reason:
the restrictions that couple attackers are not pairwise — a cap on how many
may attack (Caverns of Despair, Dueling Grounds) or attack one player
(Crawlspace), "can only attack alone" (Errantry), "can't attack unless at least
two other creatures attack" (Orcish Conscripts), "unless a creature with
greater power also attacks" (Okk), "unless a black or green creature also
attacks" (Scarred Puma). Each is asked of a whole declaration by the predicate
the declaration gate asks (``attack_declaration_refusal``). Which defender each
attacker is aimed at matters only to the per-creature predicate (``can_attack``
for that defender, and whether attacking it costs anything) and to the
per-defender cap, so the search branches over *which* creatures attack and
settles *whom* by a matching under those caps.
"""

from dataclasses import dataclass, field

from ..aura_restrictions import auras_imposing
from ..combat_restrictions import defender_attack_cap, participation_cap
from ..models import Permanent
from ..oracle import compile_card_oracle
from ..subject_filters import subject_matches
from ..turn_state import MUST_ATTACK_ON_SEAT_TURN_KEY, marked_for_this_turn


#: How many nodes one search may visit before it answers with the best it has
#: found — ``block_requirements._NODE_BUDGET``'s reason exactly: never reached
#: by a board the pool builds, and present so a pathological one costs a slow
#: declaration rather than a hung game. An inexact answer is sound in one
#: direction: a declaration it refuses is refused for a witness that really
#: does obey more.
_NODE_BUDGET = 200_000

#: The kinds a permanent prints about a set of creatures: "Creatures you
#: control attack each combat if able" (the Pirate token, Grand Melee), and the
#: two conditional ones (Magnetic Web, Viashino Bey).
_BOARD_COMPULSION_KINDS = frozenset({
    "creatures_must_attack",
    "creatures_must_attack_if_partner_attacks",
    "creatures_must_attack_if_source_attacks",
})


@dataclass(frozen=True)
class AttackRequirement:
    """One CR 508.1d requirement on one of the active player's creatures.

    ``attacker`` is the creature's battlefield slot. ``triggers`` is None for
    an unconditional requirement; for a conditional one it is the slots of
    the creatures whose attacking meets the condition — never the creature
    itself, because "also" is what Ekundu Cyclops prints and the other two
    sentences are about the *rest* of the declaration ("if this creature
    attacks, all creatures you control attack" says nothing to the creature
    that is attacking).
    """

    attacker: int
    name: str
    triggers: "frozenset[int] | None" = None

    @property
    def reason(self) -> str:
        return f"{self.name} must attack if able"

    @property
    def conditional(self) -> bool:
        return self.triggers is not None

    def obeyed(self, attacking: "set[int] | frozenset[int]") -> bool:
        """Whether a declaration attacking with the slots *attacking* obeys
        this requirement: its creature attacks, or its condition is unmet."""
        if self.attacker in attacking:
            return True
        return self.triggers is not None and not (self.triggers & attacking)


@dataclass
class AttackDeclaration:
    """A declaration as ``declare_attackers`` takes it: the attacking slots,
    the seat each attacks, and the planeswalker each attacking one attacks."""

    attackers: list[int] = field(default_factory=list)
    seats: dict[int, int] = field(default_factory=dict)
    walkers: dict[int, int] = field(default_factory=dict)


@dataclass
class AttackRequirementSearch:
    """The most requirements a legal, cost-free declaration obeys, and one
    that does. ``exact`` is False only when the node budget ran out first."""

    best: int
    witness: AttackDeclaration = field(default_factory=AttackDeclaration)
    exact: bool = True
    visited: int = 0


class AttackRequirementsMixin:
    # ------------------------------------------------------------------
    # What is required
    # ------------------------------------------------------------------

    def _board_attack_compulsions(self) -> "list[tuple[str, int, Permanent, dict]]":
        """Every requirement printed on a permanent about a *set* of creatures
        — ``(kind, carrier's seat, carrier, payload)`` — scanned once for a
        whole declaration rather than once per creature asked about."""
        return [
            (instruction.kind, source_seat, source_perm, instruction.payload)
            for source_seat, source_perm in self.permanents_with_controller()
            for instruction in compile_card_oracle(source_perm.effective_card).instructions
            if instruction.kind in _BOARD_COMPULSION_KINDS
        ]

    def _attack_requirement_count(
        self, attacker: Permanent, board: "list | None" = None,
    ) -> int:
        """How many **unconditional** CR 508.1d requirements are on *attacker*.

        *board* is :meth:`_board_attack_compulsions`' answer, for a caller
        asking about several creatures at once.

        Each source is one requirement, because CR 508.1d counts them: a
        Juggernaut under Grand Melee is affected by two, and under Dueling
        Grounds it is the creature that must attack beside a Bear affected by
        one.
        """
        count = 0
        # A resolved spell's or ability's mark for this turn (Boiling Blood,
        # Siren's Call, Norritt, Kookus's upkeep).
        if attacker.metadata.get("must_attack_until_eot"):
            count += 1
        # "**During that player's next turn**, the chosen creatures attack if
        # able" (Oracle en-Vec): the same requirement over a turn that had not
        # started when the ability resolved, so a seat-turn stamp rather than
        # the cleanup-swept mark.
        if marked_for_this_turn(self, attacker, MUST_ATTACK_ON_SEAT_TURN_KEY):
            count += 1
        # An Aura (Furor of the Bitten), asked of the Auras attached right now
        # so the requirement ends when the Aura does.
        count += len(auras_imposing(attacker, "must_attack_each_combat"))
        # The creature's own line, off its effective card so a copy, a grant
        # (Otarian Juggernaut's threshold) or a text change carries it.
        count += sum(
            1 for instruction in compile_card_oracle(attacker.effective_card).instructions
            if instruction.kind == "must_attack_each_combat"
        )
        # "**Creatures you control** attack each combat if able." (the Pirate
        # token Pursued Whale gives away; Grand Melee's "All creatures".) Printed
        # on one permanent about a set, so found by a board scan, with the
        # carrier's seat as CR 109.5's "you".
        if board is None:
            board = self._board_attack_compulsions()
        for kind, source_seat, source_perm, payload in board:
            if kind != "creatures_must_attack":
                continue
            if subject_matches(
                self, attacker, dict(payload.get("subject") or {}),
                observer=source_seat, source=source_perm,
            ):
                count += 1
        return count

    def _must_attack_if_able(self, attacker: Permanent) -> bool:
        """Whether an unconditional CR 508.1d requirement is on *attacker* —
        what the AI's chooser reads to put a compelled creature in its
        preference. The count is :meth:`_attack_requirement_count`'s."""
        return self._attack_requirement_count(attacker) > 0

    def _conditional_attack_requirements(
        self,
        attacker: Permanent,
        candidates: "list[Permanent]",
        board: "list | None" = None,
    ) -> "list[list[Permanent]]":
        """Each conditional CR 508.1d requirement on *attacker*, as the list of
        *candidates* whose attacking meets its condition.

        Three printed shapes, read off the attacker's own program and off the
        board, with every noun phrase through ``subject_matches`` and the
        seat whose line it is as CR 109.5's observer:

        * "If a creature you control attacks, this creature **also** attacks if
          able." (Ekundu Cyclops) — printed on the attacker, condition a noun
          phrase;
        * "If a creature with a magnet counter on it attacks, all creatures with
          magnet counters on them attack if able." (Magnetic Web) — printed on
          a permanent about a set, condition a noun phrase;
        * "If this creature attacks, all creatures you control attack if able."
          (Viashino Bey) — printed on a permanent about a set, condition the
          permanent itself, by identity.

        The attacker is never one of its own triggers (``is``, idiom #11: two
        magnetised creatures are two permanents and each answers for the
        other), and a requirement nothing on *candidates* could trigger is left
        out — its condition can never be met, so no declaration disobeys it.
        """
        seat = self.controller_index_of(attacker)
        if seat is None:
            return []
        found: list[list[Permanent]] = []
        for instruction in compile_card_oracle(attacker.effective_card).instructions:
            if instruction.kind != "must_attack_if_partner_attacks":
                continue
            described = dict(instruction.payload.get("subject") or {})
            found.append([
                other for other in candidates
                if other is not attacker
                and subject_matches(self, other, described, observer=seat, source=attacker)
            ])
        if board is None:
            board = self._board_attack_compulsions()
        for kind, source_seat, source_perm, payload in board:
            if kind == "creatures_must_attack":
                continue
            if not subject_matches(
                self, attacker, dict(payload.get("subject") or {}),
                observer=source_seat, source=source_perm,
            ):
                continue
            if kind == "creatures_must_attack_if_source_attacks":
                found.append([
                    other for other in candidates
                    if other is source_perm and other is not attacker
                ])
                continue
            condition = dict(payload.get("condition_subject") or {})
            found.append([
                other for other in candidates
                if other is not attacker
                and subject_matches(
                    self, other, condition, observer=source_seat, source=source_perm,
                )
            ])
        return [triggers for triggers in found if triggers]

    def _must_attack_beside(
        self, attacker: Permanent, declared: "list[Permanent]"
    ) -> bool:
        """Whether *declared* meets the condition of a conditional requirement
        on *attacker* (:meth:`_conditional_attack_requirements`)."""
        return bool(self._conditional_attack_requirements(attacker, declared))

    def _attack_targets(self, controller_index: int) -> "list[tuple[int, int | None]]":
        """Everything *controller_index*'s creatures could be aimed at: each
        living opponent, then each planeswalker an opponent controls
        (CR 508.1b)."""
        opponents = self.opponents_of(controller_index)
        return [(seat, None) for seat in opponents] + [
            (seat, walker.permanent_id)
            for seat in opponents
            for walker in self.controlled_by(seat)
            if walker.has_type("planeswalker")
        ]

    def _cost_free_attack_targets(
        self, controller_index: int
    ) -> "dict[int, list[tuple[int, int | None]]]":
        """Slot → what that creature may attack **without paying a cost**.

        A creature absent from the answer cannot obey any requirement: it is
        tapped, or no target passes ``can_attack``, or attacking each one that
        does costs something (``_owes_a_cost_to_attack``, CR 508.1d's last
        clause).
        """
        targets = self._attack_targets(controller_index)
        found: dict[int, list[tuple[int, int | None]]] = {}
        for slot, perm in enumerate(self.controlled_by(controller_index)):
            if not perm.is_creature or perm.tapped:
                continue
            allowed = [
                target for target in targets
                if self.can_attack(
                    perm, target[0], attacking_planeswalker=target[1] is not None
                )
                and not self._owes_a_cost_to_attack(perm, target)
            ]
            if allowed:
                found[slot] = allowed
        return found

    def attack_requirements(self, controller_index: int) -> list[AttackRequirement]:
        """Every CR 508.1d requirement on *controller_index*'s creatures able
        to obey one (see the module docstring), in battlefield order."""
        return self._attack_requirements_and_targets(controller_index)[0]

    def _attack_requirements_and_targets(
        self, controller_index: int,
    ) -> "tuple[list[AttackRequirement], dict[int, list]]":
        """:meth:`attack_requirements`, with :meth:`_cost_free_attack_targets`'
        answer beside it for the search.

        The requirements are read first and the targets only when there is
        one: asking ``can_attack`` of every creature against every defender is
        the expensive half, and nearly no board carries a requirement — the
        declaration step asks this on every declaration.
        """
        if not (0 <= controller_index < len(self.players)):
            return [], {}
        mine = list(self.controlled_by(controller_index))
        creatures = [perm for perm in mine if perm.is_creature]
        slot_of = {id(perm): slot for slot, perm in enumerate(mine)}
        board = self._board_attack_compulsions()
        found: list[AttackRequirement] = []
        for slot, perm in enumerate(mine):
            if not perm.is_creature or perm.tapped:
                continue
            found.extend(
                AttackRequirement(slot, perm.card.name)
                for _ in range(self._attack_requirement_count(perm, board))
            )
            for triggers in self._conditional_attack_requirements(perm, creatures, board):
                found.append(AttackRequirement(
                    slot, perm.card.name,
                    frozenset(slot_of[id(other)] for other in triggers),
                ))
        if not found:
            return [], {}
        able = self._cost_free_attack_targets(controller_index)
        return [requirement for requirement in found if requirement.attacker in able], able

    # ------------------------------------------------------------------
    # The comparison
    # ------------------------------------------------------------------

    def attack_requirement_summary(
        self, controller_index: int,
    ) -> "tuple[list[AttackRequirement], int]":
        """*controller_index*'s requirements and the most of them one legal,
        cost-free declaration obeys — told to the player **before** they
        declare (the web's ``combat.attack_requirements``)."""
        requirements, able = self._attack_requirements_and_targets(controller_index)
        if not requirements:
            return [], 0
        found = self._most_obeyed_attack_declaration(
            controller_index, requirements, able=able,
        )
        return requirements, found.best

    def attack_requirement_refusal(
        self, controller_index: int, declared: "list[Permanent]",
    ) -> str | None:
        """Why declaring *declared* disobeys CR 508.1d, or None when it obeys it.

        *declared* is assumed to have passed every CR 508.1c restriction
        already: the gate asks restrictions first, so a declaration is refused
        for the rule it breaks outright before it is refused for one it merely
        under-obeys.

        When every requirement here can be obeyed together, the refusal names
        each one this declaration leaves unobeyed — "Pirate Token, Bear must
        attack if able" — as the step always has. When they cannot, it names
        one a declaration obeying the most does obey and this one does not,
        and how many can be obeyed together, because "Eager Ooze must attack
        if able" read alone beside a Dueling Grounds is a riddle.
        """
        requirements, able = self._attack_requirements_and_targets(controller_index)
        if not requirements:
            return None
        mine = list(self.controlled_by(controller_index))
        declared_ids = {id(perm) for perm in declared}
        attacking = {slot for slot, perm in enumerate(mine) if id(perm) in declared_ids}
        obeyed = sum(1 for requirement in requirements if requirement.obeyed(attacking))
        if obeyed == len(requirements):
            return None
        found = self._most_obeyed_attack_declaration(
            controller_index, requirements, able=able,
            preferred={slot: None for slot in attacking},
        )
        if found.best <= obeyed:
            if not found.exact:
                self.log.append(
                    "CR 508.1d: the attack-requirement search ran out of room; "
                    "the declaration stands on the best it found"
                )
            return None
        witness = set(found.witness.attackers)
        missed = [
            requirement for requirement in requirements
            if requirement.obeyed(witness) and not requirement.obeyed(attacking)
        ]
        if found.best == len(requirements):
            # One name per creature, not per requirement: two sources on one
            # Juggernaut are one creature missing, two Eager Oozes are two.
            named: dict[int, str] = {}
            for requirement in missed:
                named.setdefault(requirement.attacker, requirement.name)
            return f"{', '.join(named.values())} must attack if able"
        return (
            f"{missed[0].reason} (this declaration obeys {obeyed} of the "
            f"{found.best} attack requirements that can be obeyed together)"
        )

    def obeying_attack_declaration(
        self,
        controller_index: int,
        preferred: "list[int]",
        *,
        against: int | None = None,
        rank=None,
    ) -> AttackDeclaration:
        """*preferred*, or the declaration nearest it that CR 508.1d accepts.

        The AI's half of the gate, and ``obeying_block_declaration``'s twin.
        *preferred* is the slots the seat would attack with, all aimed at
        *against* (None: the one living opponent). Handed back unchanged when
        the declaration as preferred passes the restrictions and obeys the
        most it can; otherwise the search is asked for one that does, trying
        *preferred*'s creatures as attackers first and aiming them at
        *against* first, so what comes back keeps as much of the seat's choice
        as the maximum allows — and may aim a creature elsewhere when the
        maximum needs it to (a Juggernaut that can attack only the
        planeswalker beside a Propaganda).

        *rank* is the caller's policy for which compelled creature to send
        when a cap allows fewer than are compelled — ``rank(permanent) ->
        float``, higher sent first. A valuation, and not this module's to make.

        The answer pays no cost the preference did not already pay: a costed
        attacker the seat chose is kept when the preference is accepted, and
        a search never adds one of its own. **What the search leaves out of
        the preference is offered back** (:meth:`_with_the_preference_kept`):
        a maximisation over requirements first, then the seat's preference —
        so an attacker the seat chose and pays for (under Propaganda, a toll
        the maximum does not ask) still attacks wherever adding it obeys as
        many requirements and breaks no restriction.
        """
        unchanged = AttackDeclaration(
            attackers=list(preferred),
            seats={slot: against for slot in preferred} if against is not None else {},
        )
        requirements, able = self._attack_requirements_and_targets(controller_index)
        if not requirements:
            return unchanged
        mine = list(self.controlled_by(controller_index))
        chosen = [mine[slot] for slot in preferred if 0 <= slot < len(mine)]
        target_seat = against
        if target_seat is None:
            living = self.opponents_of(controller_index)
            target_seat = living[0] if len(living) == 1 else None
        if target_seat is not None and all(
            perm.is_creature and not perm.tapped and self.can_attack(perm, target_seat)
            for perm in chosen
        ) and self.attack_declaration_refusal(
            chosen, defenders={perm.permanent_id: target_seat for perm in chosen},
        ) is None and self.attack_requirement_refusal(
            controller_index, chosen,
        ) is None and self._declaration_is_payable(
            controller_index, chosen, [target_seat] * len(chosen),
        ):
            return unchanged
        found = self._most_obeyed_attack_declaration(
            controller_index, requirements, able=able,
            preferred={slot: (target_seat, None) if target_seat is not None else None
                       for slot in preferred},
            rank=rank,
        )
        return self._with_the_preference_kept(
            controller_index, found, requirements, mine, preferred, target_seat,
        )

    def _with_the_preference_kept(
        self, controller_index: int, found: AttackRequirementSearch,
        requirements: "list[AttackRequirement]",
        mine: "list[Permanent]", preferred: "list[int]", target_seat: "int | None",
    ) -> AttackDeclaration:
        """*found*'s declaration with each creature of *preferred* it left out
        added back, in the preference's order, aimed at *target_seat* —
        wherever the creature may attack that seat, the declaration with it
        breaks no CR 508.1c restriction, and it obeys no fewer requirements
        than the maximum (CR 508.1d decides what must attack; among the
        declarations that obey the most, which one is the player's choice).

        The search walks only the attacks that cost nothing (CR 508.1d: a
        player is not required to pay to obey a requirement), so a costed
        attacker the seat had chosen — and planned the toll for — fell out of
        every declaration it had to search for. Whatever is added back is a
        subset of what the preference already paid for.
        """
        witness = found.witness
        if target_seat is None:
            return witness
        attackers = list(witness.attackers)
        seats = dict(witness.seats)
        walkers = dict(witness.walkers)
        for slot in preferred:
            if slot in attackers or not 0 <= slot < len(mine):
                continue
            permanent = mine[slot]
            if not (
                permanent.is_creature and not permanent.tapped
                and self.can_attack(permanent, target_seat)
            ):
                continue
            trial = attackers + [slot]
            defenders = {
                mine[other].permanent_id: (
                    None if other in walkers else seats.get(other, target_seat)
                )
                for other in trial
            }
            if self.attack_declaration_refusal(
                [mine[other] for other in trial], defenders=defenders,
            ) is not None:
                continue
            if not self._declaration_is_payable(
                controller_index, [mine[other] for other in trial],
                [None if other in walkers else seats.get(other, target_seat) for other in trial],
            ):
                continue
            if sum(
                1 for requirement in requirements if requirement.obeyed(set(trial))
            ) < found.best:
                continue
            attackers = trial
            seats[slot] = target_seat
        return AttackDeclaration(attackers=sorted(attackers), seats=seats, walkers=walkers)

    def _declaration_is_payable(
        self, controller_index: int, attackers: "list[Permanent]",
        attacked_seats: "list[int | None]",
    ) -> bool:
        """Whether the whole declaration's CR 508.1h costs — the mana and the
        sacrifices, summed over every attacker — can be paid in full
        (CR 508.1j allows no partial payment), through the declaration's own
        planners. A preference that cannot be paid is not handed back
        unchanged: declared, it is refused whole (the planeswalker beside a
        Propaganda, where the requirement is obeyed for free and the toll for
        two creatures is more than the lands make)."""
        total, plan = self._declaration_mana_plan(
            controller_index, list(attackers), list(attacked_seats),
        )
        if total and plan is None:
            return False
        return self._declaration_sacrifice_plan(controller_index, list(attackers)) is not None

    # ------------------------------------------------------------------
    # The most that can be obeyed
    # ------------------------------------------------------------------

    def _most_obeyed_attack_declaration(
        self,
        controller_index: int,
        requirements: list[AttackRequirement],
        *,
        able: "dict[int, list] | None" = None,
        preferred: "dict[int, tuple[int, int | None] | None] | None" = None,
        rank=None,
    ) -> AttackRequirementSearch:
        """The most of *requirements* one legal, cost-free declaration obeys.

        A branch-and-bound search, one creature at a time, over which of the
        creatures able to attack without a cost (*able*) attack:

        * a cap on attackers (Caverns of Despair) and "can only attack alone"
          are checked as the declaration grows, because a branch that breaks
          either never recovers, and so is a per-defender cap (Crawlspace) —
          by a matching of the attackers to what each may attack;
        * the set restrictions adding a creature can satisfy (company, a
          bigger or a described companion) are asked of a whole declaration,
          through ``attack_declaration_refusal`` with the matching's aim.

        The bound on a branch is what it obeys for certain, plus the
        unconditional requirements still open on the creatures left (under a
        cap, the largest that many), plus every conditional requirement not
        yet lost. The search stops at the bound of the whole board, which
        every board whose requirements can all be obeyed together reaches on
        its first branch.

        *preferred* maps a slot to what it would attack (None: no preference
        of target); those creatures are tried as attackers first, so the
        witness is the legal declaration nearest the preference.
        """
        mine = list(self.controlled_by(controller_index))
        if able is None:
            able = self._cost_free_attack_targets(controller_index)
        preferred = dict(preferred or {})
        unconditional: dict[int, int] = {}
        conditionals: list[AttackRequirement] = []
        for requirement in requirements:
            if requirement.conditional:
                conditionals.append(requirement)
            else:
                unconditional[requirement.attacker] = (
                    unconditional.get(requirement.attacker, 0) + 1
                )
        compelled = set(unconditional) | {r.attacker for r in conditionals}

        def ranked(slot: int) -> float:
            return float(rank(mine[slot])) if rank is not None else 0.0

        order = sorted(
            able,
            key=lambda slot: (
                0 if slot in compelled else 1,
                0 if slot in preferred else 1,
                -unconditional.get(slot, 0),
                -ranked(slot),
                slot,
            ),
        )
        position_of = {slot: i for i, slot in enumerate(order)}

        # What each creature is tried against first: its preferred target,
        # then each player in seat order, then each planeswalker.
        def target_order(slot: int) -> list:
            wanted = preferred.get(slot)
            return sorted(
                able[slot],
                key=lambda target: (
                    0 if wanted is not None and target == wanted
                    else 1 if wanted is not None and target[1] is None and target[0] == wanted[0]
                    else 2,
                    0 if target[1] is None else 1,
                    target[0],
                    target[1] or 0,
                ),
            )

        aims = {slot: target_order(slot) for slot in order}
        cap = participation_cap(self.all_permanents(), "attack")
        seat_caps = {
            seat: defender_attack_cap(self.controlled_by(seat))
            for seat in {target[0] for targets in able.values() for target in targets}
        }
        capped = any(limit is not None for limit in seat_caps.values())
        # How many may attack at all: the global cap, and — when everything any
        # creature here may attack is a capped player — the caps' sum, which
        # is what keeps sixteen compelled creatures against three Crawlspaces
        # from exploring every way of choosing the six that fit.
        room = cap
        if capped and not any(
            target[1] is not None or seat_caps.get(target[0]) is None
            for targets in able.values() for target in targets
        ):
            total = sum(limit for limit in seat_caps.values() if limit is not None)
            room = total if room is None else min(room, total)
        lone = {slot for slot in order if self._can_only_attack_alone(mine[slot])}

        def assignment(slots: "list[int]") -> "dict[int, tuple] | None":
            """Aim every slot in *slots* at something it may attack cost-free,
            within each player's cap — Kuhn's matching, a capped player being
            as many places as its cap and a planeswalker or an uncapped player
            unlimited (CR 508.1b: an attack at a planeswalker is not an
            attack at its controller)."""
            chosen: dict[int, tuple] = {}
            holders: dict[int, list[int]] = {}

            def place(slot: int, seen: set) -> bool:
                for target in aims[slot]:
                    limit = seat_caps.get(target[0]) if target[1] is None else None
                    if limit is None:
                        chosen[slot] = target
                        return True
                    if target[0] in seen:
                        continue
                    seen.add(target[0])
                    holding = holders.setdefault(target[0], [])
                    if len(holding) < limit:
                        holding.append(slot)
                        chosen[slot] = target
                        return True
                    for other in list(holding):
                        holding.remove(other)
                        if place(other, seen):
                            holding.append(slot)
                            chosen[slot] = target
                            return True
                        holding.append(other)
                        chosen[other] = target
                return False

            for slot in slots:
                if not place(slot, set()):
                    return None
            return chosen

        def bound(position: int, attacking: "set[int]") -> int:
            fixed = sum(unconditional.get(slot, 0) for slot in attacking)
            open_gains = sorted(
                (unconditional[slot] for slot in order[position:] if slot in unconditional),
                reverse=True,
            )
            if room is not None:
                open_gains = open_gains[: max(0, room - len(attacking))]
            conditional = 0
            for requirement in conditionals:
                if requirement.attacker in attacking:
                    conditional += 1
                elif position_of.get(requirement.attacker, -1) >= position:
                    conditional += 1
                elif not (requirement.triggers & attacking):
                    conditional += 1
            return fixed + sum(open_gains) + conditional

        result = AttackRequirementSearch(best=-1)
        top = bound(0, set())
        nodes = 0
        attacking: list[int] = []
        attacking_set: set[int] = set()

        def leaf() -> bool:
            aimed = assignment(attacking)
            if aimed is None:
                return False
            perms = [mine[slot] for slot in attacking]
            if self.attack_declaration_refusal(
                perms,
                defenders={
                    mine[slot].permanent_id: (None if target[1] is not None else target[0])
                    for slot, target in aimed.items()
                },
            ) is not None:
                return False
            met = sum(
                1 for requirement in requirements if requirement.obeyed(attacking_set)
            )
            if met > result.best:
                result.best = met
                result.witness = AttackDeclaration(
                    attackers=sorted(attacking),
                    seats={slot: target[0] for slot, target in aimed.items()},
                    walkers={
                        slot: target[1] for slot, target in aimed.items()
                        if target[1] is not None
                    },
                )
                return met >= top
            return False

        def search(position: int) -> bool:
            """True when the search is over (the bound of the board is
            reached, or the budget is spent)."""
            nonlocal nodes
            nodes += 1
            if nodes > _NODE_BUDGET:
                result.exact = False
                return True
            if bound(position, attacking_set) <= result.best:
                return False
            if position == len(order):
                return leaf()
            slot = order[position]
            attack_first = slot in preferred or slot in compelled
            for attacks in ((True, False) if attack_first else (False, True)):
                if attacks:
                    if cap is not None and len(attacking) + 1 > cap:
                        continue
                    if attacking and (slot in lone or lone & attacking_set):
                        continue
                    attacking.append(slot)
                    attacking_set.add(slot)
                    if capped and assignment(attacking) is None:
                        done = False
                    else:
                        done = search(position + 1)
                    attacking.pop()
                    attacking_set.discard(slot)
                else:
                    done = search(position + 1)
                if done:
                    return True
            return False

        search(0)
        if result.best < 0:
            # Only a spent budget leaves nothing found; the empty declaration
            # is always legal.
            result.best = sum(1 for requirement in requirements if requirement.obeyed(set()))
            result.witness = AttackDeclaration()
        result.visited = nodes
        return result
