"""What an AI seat declares in combat: its attackers (CR 508.1) and its
blockers (CR 509.1).

:func:`choose_attackers` and :func:`choose_combat_blockers` decide;
``ai_combat`` makes the declarations and owns the fallbacks for a refused
one. Each declaration is pruned until it is legal **as a set**, because the
per-creature predicates (:func:`legal_attackers`, the engine's
``_can_block_attacker``) cannot see a restriction about who else was
declared — "can only attack alone", "can't block unless another creature
blocks", a cap per defender (:func:`_legal_declaration`,
:func:`_legal_block_declaration`) — nor a requirement the set itself creates
(:func:`_with_conditional_requirements`), nor a total cost the whole
declaration has to pay (CR 508.1h, 509.1d: :func:`_unaffordable_attacker`,
:func:`_unaffordable_blocker`).

Which trades are worth making is :func:`_score_block_pair`'s, with the
damage estimates beside it.
"""

from __future__ import annotations

from .game import Game
from .aura_restrictions import aura_restriction_active
from .combat_permissions import MUST_BLOCK_ATTACKERS_UNTIL_EOT
from .models import Permanent
from .oracle import compile_card_oracle
from .ai_scoring import choose_attack_target, _permanent_value


def legal_attackers(game: Game, attacking_player_index: int, against: int | None = None) -> list[int]:
    """Return battlefield indices of every creature that may legally attack this
    turn — untapped, not summoning sick, and allowed to attack an opponent.

    When ``against`` is given, mirrors the original single-opponent behavior
    (legal against that one specific opponent). When omitted, returns creatures
    legal against ANY living opponent."""
    player = game.players[attacking_player_index]
    opponents = [against] if against is not None else game.opponents_of(attacking_player_index)
    return [
        idx
        for idx, perm in enumerate(player.battlefield)
        if perm.card.primary_type == "creature"
        and not perm.tapped
        and not game._is_summoning_sick(perm)
        and any(game.can_attack(perm, opp) for opp in opponents)
    ]


def _legal_declaration(
    game: Game, attacking_player_index: int, chosen: list[int],
    *, against: int | None = None,
) -> list[int]:
    """*chosen*, pruned until the **declaration** itself is legal (CR 508.1c).

    `legal_attackers` above is a per-creature predicate, and a restriction can
    be about the set: "can only attack alone" (Errantry), "can't attack unless
    at least two other creatures attack" (Orcish Conscripts). Proposing a set
    that disobeys one is not a partial failure — `declare_attackers` refuses the
    **whole** declaration, so a Conscripts beside one Bear kept the Bear home
    too, and the seat attacked with nobody all game.

    The rule is asked of the engine rather than re-read here: a second copy in
    the AI would drift from the one the declaration enforces, and the direction
    it would drift is a seat that stops attacking for reasons the rules do not
    give. The engine names the offending permanent, which is what makes this a
    prune rather than a search — each pass drops exactly one creature, so it
    terminates.

    **Which one it names is the caller's business for a cap.** "No more than two
    creatures can attack" (Caverns of Despair, Crawlspace) is disobeyed by the
    set rather than by any member of it, so the engine names the *last* attacker
    in the list it was handed — a rule cannot say which creature the attacker
    would rather keep, and inventing an answer there would put AI valuation
    inside the rules engine. So the list is handed over weakest-last, and the
    surviving indices come back in their original order, which is what makes
    this a cap the AI attacks *under* rather than one it attacks *through*.

    *against* is the seat this declaration is aimed at, which the per-defender
    cap needs and the global one does not. It matters only at a table with more
    than two living players: with one opponent the engine fills it in, and with
    several it cannot guess, so a free-for-all declaration would be pruned
    against the global cap alone and then refused whole for the other.
    """
    # Through the seam (`permanent_at`), which is where an index becomes a
    # permanent: the AI carries slots because that is what the declaration takes,
    # and a raw `battlefield[i]` here would be a second place that has to be
    # right about what a slot means.
    pruned = [
        (idx, game.permanent_at(attacking_player_index, idx)) for idx in chosen
    ]
    pruned = [(idx, perm) for idx, perm in pruned if perm is not None]
    # Descending value, so the engine's "last one" is the one this seat can most
    # afford to leave home. Only the order of the *question* changes; the answer
    # is a set, and it is returned in the caller's order below.
    pruned.sort(key=lambda entry: -_permanent_value(entry[1]))
    while pruned:
        # **What the declaration costs is pruned against too, and it was not.**
        # CR 508.1h's costs are summed over the whole declaration
        # (`_declaration_mana_plan`, `_declaration_sacrifice_plan`), where
        # `legal_attackers` above can only ask "could this seat afford *this*
        # creature". So a seat with one land under a {1}-per-attacker toll
        # proposed three attackers, the declaration refused all three, and
        # `ai_combat`'s superset fallback — every legal attacker, the same
        # three — was refused for the same reason: the seat attacked with
        # nobody while it could plainly have attacked with one. Measured on
        # War Tax and true of every shipped card that prints a summed
        # declaration cost (Koskun Falls, Elephant Grass, Propaganda,
        # Brainwash, Leviathan, Flooded Woodlands, Reclamation).
        #
        # Asked of the engine's own planners rather than re-totalled here, for
        # the restriction loop's stated reason: a second copy would drift, and
        # the direction it drifts is a seat that stops attacking for reasons
        # the rules do not give. Weakest-last ordering means the creature
        # dropped is the one this seat can most afford to leave home, exactly
        # as it is for a cap.
        unaffordable = _unaffordable_attacker(
            game, attacking_player_index, [perm for _idx, perm in pruned], against
        )
        if unaffordable is not None:
            pruned = [
                (idx, perm) for idx, perm in pruned if perm is not unaffordable
            ]
            continue
        refusal = game.attack_declaration_refusal(
            [perm for _idx, perm in pruned],
            # Who this seat is aiming at, when the caller knows. Omitting it is
            # only safe at a table with one living opponent, where the engine
            # fills it in; `choose_attackers` picks a single target even in a
            # free-for-all, so a per-defender cap (Crawlspace) at *that* seat
            # would otherwise be invisible here and the whole declaration would
            # be refused again — the exact failure this prune exists to stop.
            defenders=(
                None if against is None
                else {perm.permanent_id: against for _idx, perm in pruned}
            ),
        )
        if refusal is None:
            break
        offender, _reason = refusal
        pruned = [(idx, perm) for idx, perm in pruned if perm is not offender]
    kept = {id(perm) for _idx, perm in pruned}
    return [idx for idx in chosen if id(game.permanent_at(attacking_player_index, idx)) in kept]


def _with_conditional_requirements(
    game: Game, attacking_player_index: int, chosen: list[int], legal: list[int]
) -> list[int]:
    """*chosen*, plus every legal attacker the set itself now **requires**.

    The mirror of :func:`_legal_declaration` one rule over. That one prunes
    until a restriction stops being disobeyed; this one adds until a
    *requirement* is obeyed — "If a creature you control attacks, this creature
    also attacks if able" (Ekundu Cyclops) is conditional on the rest of the
    declaration, so a set that was legal before a creature was added can stop
    being legal because of it.

    Asked of the engine rather than re-read here, for ``_legal_declaration``'s
    reason: a second copy of the rule in the AI drifts, and the direction it
    drifts is a seat whose whole declaration is refused and which therefore
    attacks with nobody all game.

    Terminates because each pass adds at least one creature out of a finite
    list, and a set that adds nothing is stable.
    """
    picked = list(chosen)
    while True:
        declared = [
            perm for perm in
            (game.permanent_at(attacking_player_index, idx) for idx in picked)
            if perm is not None
        ]
        added = [
            idx for idx in legal
            if idx not in picked
            and game._must_attack_beside(
                game.permanent_at(attacking_player_index, idx), declared
            )
        ]
        if not added:
            return picked
        picked.extend(added)


def choose_attackers(game: Game, attacking_player_index: int) -> list[int]:
    """Return indices of creatures that should attack this turn.

    MVP multiplayer behavior: picks one opponent (``choose_attack_target``) and
    decides, for each legal attacker, whether to send it at that opponent —
    splitting one attack across multiple opponents is a documented stretch goal,
    not implemented here."""
    player = game.players[attacking_player_index]
    opponent_index = choose_attack_target(game, attacking_player_index)
    opponent = game.players[opponent_index]

    legal_attackers_list = legal_attackers(game, attacking_player_index, against=opponent_index)
    if not legal_attackers_list:
        return []

    # Creatures that must attack if able (Siren's Call, Lure-style "attacks each
    # combat if able", etc.) are non-negotiable: declare_attackers rejects any
    # declaration that omits them, so they must be in the result regardless of
    # the profitability heuristic below.
    forced = [idx for idx in legal_attackers_list if game._must_attack_if_able(player.battlefield[idx])]

    # A creature enchanted with Lure ("All creatures able to block it do so") is
    # only worth attacking with if it actually gets declared. Treat it as forced
    # so the AI doesn't decline to attack with it (which would skip the defender's
    # block step entirely from the human's perspective).
    for idx in legal_attackers_list:
        if idx not in forced and aura_restriction_active(
            player.battlefield[idx], "must_be_blocked_by_all_able"
        ):
            forced.append(idx)

    opponent_blockers = [
        perm
        for perm in game.controlled_by(opponent)
        if perm.card.primary_type == "creature" and not perm.tapped
    ]
    if not opponent_blockers:
        return _legal_declaration(
            game, attacking_player_index, legal_attackers_list,
            against=opponent_index,
        )

    chosen = list(forced)
    for idx in legal_attackers_list:
        if idx in chosen:
            continue
        attacker = player.battlefield[idx]
        best_defender_score = max(
            _score_block_pair(blocker, attacker) for blocker in opponent_blockers
        )
        # Attack when the best possible block is not clearly profitable for the opponent.
        if best_defender_score <= _permanent_value(attacker):
            chosen.append(idx)
    chosen = _with_conditional_requirements(
        game, attacking_player_index, chosen, legal_attackers_list
    )
    chosen = _legal_declaration(
        game, attacking_player_index, chosen, against=opponent_index
    )

    # Go all-in when lethal is on the table — through the same prune, because a
    # declaration that is refused deals no damage at all. This returned the raw
    # legal set, so under either attack cap the lethal swing was refused whole
    # and the seat attacked with nobody on the turn it could have won.
    if sum(player.battlefield[i].effective_power for i in legal_attackers_list) >= opponent.life:
        return _legal_declaration(
            game, attacking_player_index, legal_attackers_list,
            against=opponent_index,
        )

    return sorted(chosen)


def _legal_block_declaration(
    game: Game,
    defending_player_index: int,
    chosen: dict[int, int | list[int]],
) -> dict[int, int | list[int]]:
    """*chosen*, pruned until the **declaration** itself is legal (CR 509.1b).

    :func:`_legal_declaration` one step of combat over, and written from the
    identical defect. ``_can_block_attacker`` is a per-pair predicate, and a
    restriction can be about the set: "no more than two creatures can block each
    combat" (Caverns of Despair), "can't block unless at least two other
    creatures block" (Orcish Conscripts, and Mogg Flunkies' "can't block
    alone"), "can't block unless a creature with greater power also blocks"
    (Okk). Proposing a map that disobeys one is not a partial failure —
    ``declare_blockers`` refuses the **whole** declaration, so the defender
    blocked with nobody, this combat and every later one, in silence.

    The rule is asked of the engine rather than re-read here, for the attack
    side's reason exactly: a second copy in the AI would drift from the one the
    declaration enforces, and the direction it drifts is a seat that stops
    blocking for reasons the rules do not give. The engine names the offending
    permanent, which is what makes this a prune rather than a search — each pass
    drops exactly one blocker, so it terminates.

    A **map**, not a list, which is the one structural difference from the
    attack side: dropping the offender means dropping a key, and the attackers
    it was assigned go with it. Everything else about that blocker's assignment
    is left alone, because a partial block is a different declaration, not a
    smaller one.

    Only this seat's own map is pruned, and only against itself: CR 802.4b
    judges each defending player's blocks with every other player's blockers
    ignored, so a second defender declaring first cannot make this one's map
    illegal.

    Which blocker the engine names for a **cap** is this function's business,
    the way it is `_legal_declaration`'s: a cap is disobeyed by the set rather
    than by any member of it, so the engine names the *last* one it was handed.
    The list therefore goes over worst-block-last — scored by the same
    `_score_block_pair` that chose the blocks — which is what makes this a cap
    the AI blocks *under* rather than one it blocks *through*.
    """
    attacker_player = game.players[game.active_player_index]
    ordered: list[tuple[int, Permanent, float]] = []
    for blocker_idx, assigned in chosen.items():
        blocker = game.permanent_at(defending_player_index, blocker_idx)
        if blocker is None:
            continue
        attacker_indices = assigned if isinstance(assigned, list) else [assigned]
        attacker = next(
            (
                perm
                for perm in (
                    game.permanent_at(attacker_player, idx)
                    for idx in attacker_indices
                )
                if perm is not None
            ),
            None,
        )
        # The value of *the block*, not of the blocker: a cap forces the seat to
        # give one up, and the one to give up is the least useful block rather
        # than the smallest creature. With no attacker resolvable there is no
        # pair to score, so the creature's own value stands in.
        score = (
            _score_block_pair(blocker, attacker)
            if attacker is not None
            else _permanent_value(blocker)
        )
        ordered.append((blocker_idx, blocker, score))
    ordered.sort(key=lambda entry: -entry[2])

    while ordered:
        # What the declaration *costs*, pruned against for the attack side's
        # reason exactly: CR 509.1d totals the costs of every chosen blocker, so
        # a defender with one land under a {1}-per-blocker toll (War Cadence)
        # would propose two blocks, have the declaration refused whole, and fall
        # through `ai_combat`'s superset rung to blocking with nobody — while it
        # could plainly have blocked with one. True of every shipped card
        # printing a summed block cost too (Hipparion, Awesome Presence, and
        # Heat Wave's life half).
        unaffordable = _unaffordable_blocker(
            game, defending_player_index, attacker_player,
            {idx: chosen[idx] for idx, _perm, _score in ordered},
            {idx: perm for idx, perm, _score in ordered},
            [perm for _idx, perm, _score in ordered],
        )
        if unaffordable is not None:
            ordered = [
                entry for entry in ordered if entry[1] is not unaffordable
            ]
            continue
        refusal = game.block_declaration_refusal(
            [perm for _idx, perm, _score in ordered]
        )
        if refusal is None:
            break
        offender, _reason = refusal
        ordered = [
            entry for entry in ordered if entry[1] is not offender
        ]
    kept = {blocker_idx for blocker_idx, _perm, _score in ordered}
    return {
        blocker_idx: assigned
        for blocker_idx, assigned in chosen.items()
        if blocker_idx in kept
    }



def _unaffordable_attacker(game, seat, attackers, against):
    """The attacker to drop when this whole declaration cannot be paid for.

    None when it can. CR 508.1h locks in a *total* cost, so affordability is a
    property of the set rather than of any member — which means, exactly as for
    a cap, that no rule can say which creature to leave home. The weakest is
    last in the list this is handed, so naming it is the same policy the
    restriction prune already applies.

    Both halves of the cost are asked, because either can be the one that does
    not fit: mana (Koskun Falls, War Tax) and sacrifice (Flooded Woodlands,
    Leviathan). Asked of the engine's own planners, so what the AI believes it
    can afford and what the declaration will charge are one answer.
    """
    if not attackers:
        return None
    seats = None if against is None else [against] * len(attackers)
    total, plan = game._declaration_mana_plan(seat, list(attackers), seats)
    if total and plan is None:
        return attackers[-1]
    if game._declaration_sacrifice_plan(seat, list(attackers)) is None:
        return attackers[-1]
    return None



def _unaffordable_blocker(
    game, defender_seat, attacker_owner, assigned, blockers, ordered_perms
):
    """The blocker to drop when this whole block declaration cannot be paid for.

    None when it can. :func:`_unaffordable_attacker`'s twin one step of combat
    over, and every word of that docstring applies: CR 509.1d locks in a total,
    affordability is a property of the set, and no rule can say which block to
    give up — so the weakest, which is last in the list handed here, is named.

    Both currencies are asked, because either can be the one that does not fit:
    mana (Hipparion, Awesome Presence, War Cadence) and life (Heat Wave,
    CR 119.4). Through the engine's own planners, so what the AI believes it can
    afford and what the declaration will charge are one answer.
    """
    if not ordered_perms:
        return None
    plan_assignments = {
        idx: (list(a) if isinstance(a, list) else [a]) for idx, a in assigned.items()
    }
    resolved_attackers = {}
    for attacker_indices in plan_assignments.values():
        for attacker_idx in attacker_indices:
            perm = game.permanent_at(attacker_owner, attacker_idx)
            if perm is not None:
                resolved_attackers[attacker_idx] = perm
    life_owed = game._block_declaration_life(
        plan_assignments, blockers, resolved_attackers
    )
    if life_owed and game.players[defender_seat].life < life_owed:
        return ordered_perms[-1]
    total, plan = game._block_declaration_mana_plan(
        defender_seat, plan_assignments, blockers, resolved_attackers
    )
    if total and plan is None:
        return ordered_perms[-1]
    return None


def choose_combat_blockers(
    game: Game,
    defending_player_index: int,
    *,
    ignore_substitution: bool = False,
) -> dict[int, int | list[int]]:
    """The blocks an AI seat declares for *defending_player_index*.

    ``ignore_substitution`` asks for the defender's *own* best blocks even while
    another seat is choosing (see the Melee note below) — the fallback for when
    the empty declaration a substituted chooser wants is itself illegal, because
    a blocking requirement (Lure) compels a block. An illegal-but-preferred
    answer is no answer at all, and the alternative is the safety valve that
    wipes every seat's blocks.
    """
    combat = game.get_combat_state()
    if game.current_turn_phase != "combat" or game.current_step != "declare_blockers":
        return {}
    if defending_player_index not in game.combat_defending_players():
        return {}
    # "You choose which creatures block this combat and how those creatures
    # block." (Melee.) CR 509.1a's chooser is someone else, and the weights
    # below score a block for the *defender* — handed to an opponent making the
    # choice they would pick the blocks that best defend the seat they are
    # attacking. Every printing of this substitution is cast by the attacking
    # player, so the honest answer is the one the card is played for: block with
    # nothing. Asked of the seam rather than of the card, so a second printing
    # needs no weight here; if a requirement (Lure) makes the empty declaration
    # illegal, the caller falls back to the defender's own choice, which is at
    # least legal.
    chooser = game.block_chooser_index(defending_player_index)
    if (
        not ignore_substitution
        and chooser != defending_player_index
        and chooser in game.opponents_of(defending_player_index)
    ):
        return {}

    active_index = game.active_player_index
    # CR 802.4a: this defender may only block attackers aimed at them.
    attackers = [
        int(item["attacker_index"])
        for item in combat.get("attackers", [])
        if item.get("defending_player_index") == defending_player_index
    ]
    if not attackers:
        return {}

    defender = game.players[defending_player_index]
    attacker_player = game.players[active_index]

    available_blockers = [
        idx
        for idx, blocker in enumerate(defender.battlefield)
        if blocker.card.primary_type == "creature" and not blocker.tapped
    ]
    if not available_blockers:
        return {}

    legal_pairs: list[tuple[int, int, float]] = []
    # How many blockers each attacker needs at once, asked of the engine rather
    # than of the keyword: menace is the N=2 case of a printed template the
    # declaration gate reads through one helper (Gorilla Berserkers' "except by
    # three or more creatures"), and an AI that knew only the keyword would keep
    # submitting a declaration the gate bounces — which is a seat that declares
    # no blockers at all for the rest of the combat.
    minimum_blockers: dict[int, int] = {}
    for blocker_idx in available_blockers:
        blocker = defender.battlefield[blocker_idx]
        for attacker_idx in attackers:
            if attacker_idx < 0 or attacker_idx >= len(attacker_player.battlefield):
                continue
            attacker = attacker_player.battlefield[attacker_idx]
            minimum_blockers[attacker_idx] = game._minimum_blockers(attacker)
            if not game._can_block_attacker(blocker, attacker):
                continue
            legal_pairs.append((blocker_idx, attacker_idx, _score_block_pair(blocker, attacker)))

    if not legal_pairs:
        return {}

    assignments: dict[int, int] = {}
    used_blockers: set[int] = set()

    # Priority 1: prevent lethal where possible.
    incoming = _estimated_incoming_player_damage(game, defending_player_index)
    life = defender.life
    if incoming >= life:
        for blocker_idx, attacker_idx, _ in sorted(legal_pairs, key=lambda item: _estimated_damage_prevented(game, defending_player_index, item[1], item[0]), reverse=True):
            if blocker_idx in used_blockers:
                continue
            prevented = _estimated_damage_prevented(game, defending_player_index, attacker_idx, blocker_idx)
            if prevented <= 0:
                continue
            assignments[blocker_idx] = attacker_idx
            used_blockers.add(blocker_idx)
            incoming -= prevented
            if incoming < life:
                break

    # Priority 2: maximize favorable trades.
    for blocker_idx, attacker_idx, _ in sorted(legal_pairs, key=lambda item: item[2], reverse=True):
        if blocker_idx in used_blockers:
            continue
        if blocker_idx in assignments:
            continue
        assignments[blocker_idx] = attacker_idx
        used_blockers.add(blocker_idx)

    # Blaze of Glory: a creature marked "blocks each attacking creature this
    # turn if able" must be assigned every attacker it can legally block —
    # declare_blockers rejects anything less.
    for blocker_idx in available_blockers:
        blocker = defender.battlefield[blocker_idx]
        if not blocker.metadata.get("must_block_all_until_eot"):
            continue
        must = [
            attacker_idx
            for attacker_idx in attackers
            if 0 <= attacker_idx < len(attacker_player.battlefield)
            and game._can_block_attacker(blocker, attacker_player.battlefield[attacker_idx])
        ]
        if must:
            assignments[blocker_idx] = must

    # "Must be blocked if able" (Canopy Stalker): declare_blockers refuses a
    # declaration that leaves such an attacker unblocked while an able creature
    # stands by, so the AI assigns one — the cheapest still-free blocker, which
    # is a stated policy and not a valuation. Blocking is compulsory here, so
    # declining is not the safe fallback it is for menace below.
    for attacker_idx in attackers:
        attacker = game.permanent_at(attacker_player, attacker_idx)
        if attacker is None:
            continue
        if not any(
            i.kind == "must_be_blocked"
            for i in compile_card_oracle(attacker.effective_card).instructions
        ):
            continue
        if any(
            attacker_idx == assigned or (isinstance(assigned, list) and attacker_idx in assigned)
            for assigned in assignments.values()
        ):
            continue
        for blocker_idx in available_blockers:
            if blocker_idx in assignments:
                continue
            blocker = game.permanent_at(defender, blocker_idx)
            if blocker is not None and game._can_block_attacker(blocker, attacker):
                assignments[blocker_idx] = attacker_idx
                break

    # CR 509.1b's minimum-blocker restrictions (menace, and Gorilla Berserkers'
    # printed spelling of the same thing): declare_blockers refuses an
    # assignment that puts fewer than N blockers on such an attacker, so the AI
    # declines those blocks rather than submitting a declaration that bounces.
    # Ganging up is a valuation question for another day; not blocking is always
    # legal.
    menace_counts: dict[int, int] = {}
    for assigned in assignments.values():
        for attacker_idx in assigned if isinstance(assigned, list) else [assigned]:
            menace_counts[attacker_idx] = menace_counts.get(attacker_idx, 0) + 1
    for attacker_idx, count in menace_counts.items():
        if count >= minimum_blockers.get(attacker_idx, 1):
            continue
        for blocker_idx in list(assignments):
            assigned = assignments[blocker_idx]
            if isinstance(assigned, list):
                remaining = [a for a in assigned if a != attacker_idx]
                if remaining:
                    assignments[blocker_idx] = remaining
                else:
                    del assignments[blocker_idx]
            elif assigned == attacker_idx:
                del assignments[blocker_idx]

    # "Target creature blocks **this creature** this turn if able."
    # (Trumpeting Armodon.) The narrowed requirement: the mark on the blocker
    # names the attackers it owes a block to, by id. Assigned before the
    # unnarrowed Watchdog rule below, because obeying this one also obeys that
    # one — the reverse order would spend the creature on the wrong attacker
    # and leave the declaration illegal.
    for blocker_idx in available_blockers:
        if blocker_idx in assignments:
            continue
        blocker = game.permanent_at(defender, blocker_idx)
        if blocker is None:
            continue
        owed = blocker.metadata.get(MUST_BLOCK_ATTACKERS_UNTIL_EOT) or ()
        if not owed:
            continue
        for attacker_idx in attackers:
            attacker = game.permanent_at(attacker_player, attacker_idx)
            if attacker is None or attacker.permanent_id not in owed:
                continue
            if not game._can_block_attacker(blocker, attacker):
                continue
            joined = sum(
                1
                for assigned in assignments.values()
                if attacker_idx == assigned
                or (isinstance(assigned, list) and attacker_idx in assigned)
            )
            if joined + 1 < minimum_blockers.get(attacker_idx, 1):
                continue
            assignments[blocker_idx] = attacker_idx
            break

    # "This creature blocks each combat if able." (Watchdog.) CR 509.1c aimed
    # at the blocker: declare_blockers refuses a declaration that leaves such a
    # creature out while it could legally block something, so the AI assigns it
    # the first attacker it can block rather than submitting a declaration that
    # bounces every combat.
    #
    # **After the menace pruning above**, not before it: that loop strips
    # blocks that under-fill a minimum, and a compelled block stripped there
    # would leave the declaration illegal for the reason it was added. Which
    # is also why the minimum is checked here — CR 509.1c asks for the
    # requirement to be obeyed *without disobeying a restriction*, and joining
    # a menace attacker alone disobeys one.
    for blocker_idx in available_blockers:
        if blocker_idx in assignments:
            continue
        blocker = game.permanent_at(defender, blocker_idx)
        if blocker is None:
            continue
        if not any(
            i.kind == "must_block_each_combat"
            for i in compile_card_oracle(blocker.effective_card).instructions
        ):
            continue
        for attacker_idx in attackers:
            attacker = game.permanent_at(attacker_player, attacker_idx)
            if attacker is None or not game._can_block_attacker(blocker, attacker):
                continue
            joined = sum(
                1
                for assigned in assignments.values()
                if attacker_idx == assigned
                or (isinstance(assigned, list) and attacker_idx in assigned)
            )
            if joined + 1 < minimum_blockers.get(attacker_idx, 1):
                continue
            assignments[blocker_idx] = attacker_idx
            break

    # CR 509.1b's restrictions on the declaration as a whole, last — the mirror
    # of `_legal_declaration` at the tail of `choose_attackers`, and last for
    # its reason: every requirement above may still *add* a blocker, and a set
    # that was under the cap before one was added is not under it after.
    return _legal_block_declaration(game, defending_player_index, assignments)


def _score_block_pair(blocker: Permanent, attacker: Permanent) -> float:
    blocker_kills = blocker.effective_power >= attacker.effective_toughness
    attacker_kills = attacker.effective_power >= blocker.effective_toughness

    attacker_value = _permanent_value(attacker)
    blocker_value = _permanent_value(blocker)

    score = 0.0
    if blocker_kills and not attacker_kills:
        score += attacker_value + 4.0
    elif blocker_kills and attacker_kills:
        score += attacker_value - blocker_value * 0.6 + 2.0
    elif not blocker_kills and attacker_kills:
        score -= blocker_value + 2.0
    else:
        score += min(attacker.effective_power, blocker.effective_toughness) * 0.5

    # Prefer blocking higher impact attackers.
    score += attacker.effective_power * 0.3 + attacker.effective_toughness * 0.2
    return score


def _estimated_damage_prevented(game: Game, defending_player_index: int, attacker_idx: int, blocker_idx: int) -> int:
    attacker = game.players[game.active_player_index].battlefield[attacker_idx]
    blocker = game.players[defending_player_index].battlefield[blocker_idx]
    power = max(0, attacker.effective_power)
    if game._has_keyword(attacker, "trample"):
        return min(power, max(0, blocker.effective_toughness - blocker.damage_marked))
    return power


def _estimated_incoming_player_damage(game: Game, defending_player_index: int) -> int:
    combat = game.get_combat_state()
    total = 0
    for item in combat.get("attackers", []):
        if item.get("defending_player_index") != defending_player_index:
            continue
        attacker_idx = int(item.get("attacker_index", -1))
        if attacker_idx < 0 or attacker_idx >= len(game.players[game.active_player_index].battlefield):
            continue
        attacker = game.players[game.active_player_index].battlefield[attacker_idx]
        total += max(0, attacker.effective_power)
    return total
