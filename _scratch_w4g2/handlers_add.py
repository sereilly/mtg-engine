

@effect_handler("choose_blocks_for_defenders")
def choose_blocks_for_defenders(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Melee: "You choose which creatures block this combat and how those
    creatures block." CR 509.1a's chooser, substituted for the rest of this
    combat.

    One assignment, because that is the whole of what the card changes. The
    declaration stays the defending player's turn-based action, their creatures
    are the ones that block, every restriction and requirement is still checked
    against their board and CR 509.1d-f still charges them the cost — only the
    decisions inside CR 509.1a move. ``Game.block_chooser_index`` is the one
    place that is read, by the declaration's own gate, by the AI stepper and by
    the web layer, so "who is asked?" cannot come to have three answers.

    Set from the *resolving* seat rather than from the card's controller field:
    a copied Melee (Fork) is controlled by whoever copied it, and "you" on a
    spell is CR 109.5's controller of the spell.
    """
    seat = game.players.index(context.caster)
    game.combat_block_chooser = seat
    game.log.append(
        f"{context.card.name}: {context.caster.name} chooses this combat's blocks"
    )
    return True, "resolved"


def _blockers_of_attacker(game: Game, attacker_index: int) -> list[tuple[int, int]]:
    """``(defending seat, blocker index)`` for every creature blocking
    *attacker_index*.

    CR 802 means one attacker can only be blocked by the seat it is attacking,
    but ``combat_blockers`` is nested by defender and this reads it whole — the
    same shape ``_remove_blocker_from_combat``'s "still blocked" scan takes, and
    for the same reason: the question is about the attacker, not about a seat.
    """
    return [
        (seat, blocker_idx)
        for seat, blocker_map in game.combat_blockers.items()
        for blocker_idx, attackers in blocker_map.items()
        if attacker_index in attackers
    ]


@effect_handler("reassign_blockers_between_attackers")
def reassign_blockers_between_attackers(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """General Jarkeld: "Choose two target blocked attacking creatures. If each
    of those creatures could be blocked by all creatures that the other is
    blocked by, each creature that's blocking exactly one of those attacking
    creatures stops blocking it and is blocking the other attacking creature."

    The **mirror** of Sorrow's Path's ``swap_block_assignments``: that card
    chooses the two blockers and swaps what each blocks, this one chooses the
    two attackers and swaps who blocks each. The hypothetical is the same
    question asked from the other end, and it is answered by the same helper —
    ``_could_block_all``, which asks exactly the gate a real declaration passes
    (CR 509.1b), because two questions would be two answers.

    Three things this handler does *not* do, each because the card does not say
    it:

    * **Nothing is removed from combat.** "Stops blocking it and is blocking the
      other" leaves every creature a blocking creature throughout, so
      ``_remove_blocker_from_combat`` is not the route — it unblocks an attacker
      whose only blocker left, which CR 509.1h forbids and which the words here
      never ask for.
    * **Each chosen attacker stays blocked**, for that same rule, even where the
      trade leaves one with no blockers at all: it was blocked, nothing removed
      it from combat and no effect says it becomes unblocked, so it stays a
      blocked creature and assigns no combat damage (CR 510.1a).
    * **"Blocks" does not trigger again.** CR 509.3a fires only if the creature
      "wasn't a blocking creature at that time" and CR 509.3c only if the
      attacker "was an unblocked creature at that time" — neither is true here.
      The per-pair halves (CR 509.3b, CR 509.3d) do fire, because no creature
      was already blocking the attacker it moves to.

    "Blocking **exactly one** of those attacking creatures" is the clause that
    keeps this from being a plain swap: a creature blocking both chosen
    attackers is blocking neither of them exactly once and does not move.
    """
    if not (0 <= game.active_player_index < len(game.players)):
        return True, "no combat"
    active = game.players[game.active_player_index]
    # The attackers are the active player's, whoever activated the ability, so
    # the targets are resolved against that battlefield rather than against
    # ``context.target`` — a defending player's ability names its opponent's
    # creatures.
    chosen = resolve_target_permanents(game, context, player=active)
    if len(chosen) != 2 or chosen[0] is chosen[1]:
        return True, "no targets"
    first, second = chosen
    first_idx = game.battlefield_index_of(first)
    second_idx = game.battlefield_index_of(second)
    if first_idx is None or second_idx is None:
        return True, "no targets"
    # CR 608.2b at resolution: both must still be attacking and still blocked —
    # the same two words the picker narrowed on. An attacker removed from combat
    # since is no longer one of the creatures this sentence is about.
    if not (
        first_idx in game.combat_attackers and second_idx in game.combat_attackers
    ):
        game.log.append(
            f"{context.card.name}: its chosen creatures are no longer attacking"
        )
        return True, "targets illegal"

    blockers_of_first = _blockers_of_attacker(game, first_idx)
    blockers_of_second = _blockers_of_attacker(game, second_idx)
    if not blockers_of_first or not blockers_of_second:
        game.log.append(
            f"{context.card.name}: its chosen creatures are no longer blocked"
        )
        return True, "targets illegal"

    # "If each of those creatures could be blocked by all creatures that the
    # other is blocked by" — one condition over the pair, checked before
    # anything moves, exactly as Sorrow's Path checks its mirror of it.
    def _blocker_at(seat: int, blocker_index: int):
        return game.permanent_at(game.players[seat], blocker_index)

    hypothetical_holds = all(
        _blocker_at(seat, b_idx) is not None
        and _could_block_all(game, _blocker_at(seat, b_idx), [first_idx])
        for seat, b_idx in blockers_of_second
    ) and all(
        _blocker_at(seat, b_idx) is not None
        and _could_block_all(game, _blocker_at(seat, b_idx), [second_idx])
        for seat, b_idx in blockers_of_first
    )
    if not hypothetical_holds:
        game.log.append(
            f"{context.card.name}: {first.card.name} and {second.card.name} "
            "could not be blocked by each other's blockers — nothing happens"
        )
        return True, "reassignment illegal"

    moved: dict[int, dict[int, list[int]]] = {}
    for from_idx, to_idx, blockers in (
        (first_idx, second_idx, blockers_of_first),
        (second_idx, first_idx, blockers_of_second),
    ):
        for seat, b_idx in blockers:
            assigned = game.combat_blockers.get(seat, {}).get(b_idx)
            if assigned is None or to_idx in assigned:
                # Blocking **both** chosen attackers, so not "exactly one": it
                # stays where it is.
                continue
            assigned[assigned.index(from_idx)] = to_idx
            # CR 510.1d's pre-committed division is keyed by the attacker it was
            # declared against, so it travels with the block — left behind it
            # would divide this blocker's damage among a creature it no longer
            # blocks.
            division = game.combat_multiblock_damage.get(b_idx)
            if division is not None and from_idx in division:
                division[to_idx] = division.pop(from_idx)
            moved.setdefault(seat, {}).setdefault(b_idx, []).append(to_idx)

    if not moved:
        game.log.append(
            f"{context.card.name}: every blocker was blocking both creatures — "
            "nothing moves"
        )
        return True, "resolved"

    # The per-permanent combat flags and the band propagation are the projection
    # of the maps just rewritten, exactly as they are after a declaration.
    # Neither attacker stops being blocked, because nothing left combat
    # (CR 509.1h).
    game._prune_combat_state()
    for seat, assignments in moved.items():
        game._record_block_history(seat, assignments)
        game._fire_creature_blocks_triggers(seat, assignments, already_blocking=True)
        game._fire_becomes_blocked_triggers(seat, assignments, already_blocked=True)
    game.log.append(
        f"{context.card.name}: the creatures blocking {first.card.name} and "
        f"{second.card.name} traded places"
    )
    return True, "resolved"
