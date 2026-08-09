from __future__ import annotations

import re
from functools import lru_cache

from ..models import CardDefinition, Permanent, PlayerState
from ..oracle import compile_card_oracle
from ..trigger_utils import matching_triggers

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
        if player.battlefield:
            for permanent in player.battlefield:
                self.log.append(
                    f"{permanent.card.name} leaves the game ({player.name} left the game, CR 800.4a)"
                )
            player.battlefield = []
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
            for player in self.players:
                survivors_ss: list[Permanent] = []
                for perm in player.battlefield:
                    needs_island = next(matching_triggers(
                        perm.effective_card,
                        condition_kinds={"no_islands"},
                        instruction_kinds={"sacrifice_self"},
                    ), None) is not None
                    needs_any_land = next(matching_triggers(
                        perm.effective_card,
                        condition_kinds={"no_lands"},
                        instruction_kinds={"sacrifice_self"},
                    ), None) is not None
                    controls_island = any(
                        p.card.primary_type == "land" and p.has_type("island")
                        for p in player.battlefield
                    )
                    controls_any_land = any(p.card.primary_type == "land" for p in player.battlefield)
                    if (needs_island and not controls_island) or (needs_any_land and not controls_any_land):
                        self._permanent_to_graveyard(player, perm)
                        reason = "controls no lands" if needs_any_land and not controls_any_land else "controls no Islands"
                        self.log.append(f"{perm.card.name} sacrificed ({reason})")
                        changed = True
                        continue
                    survivors_ss.append(perm)
                player.battlefield = survivors_ss

            # Jihad: "When the chosen player controls no nontoken permanents of
            # the chosen color, sacrifice this enchantment." A state trigger
            # (CR 603.8) checked alongside SBAs like the no-lands sacrifices
            # above, so it fires the moment the last matching permanent leaves.
            for player in self.players:
                survivors_cc: list[Permanent] = []
                for perm in player.battlefield:
                    if (
                        "when the chosen player controls no nontoken permanents of the chosen color"
                        in perm.effective_card.oracle_text.lower()
                        and isinstance(perm.metadata.get("chosen_player_index"), int)
                        and not self._chosen_color_permanent_condition(perm)
                    ):
                        self._permanent_to_graveyard(player, perm)
                        self.log.append(
                            f"{perm.card.name} sacrificed (the chosen player controls no "
                            "nontoken permanents of the chosen color)"
                        )
                        changed = True
                        continue
                    survivors_cc.append(perm)
                player.battlefield = survivors_cc

            # City in a Bottle: "other nontoken permanents with a name
            # originally printed in [set] are on the battlefield, their
            # controllers sacrifice them." Modeled as a continuous state
            # check (like the no-lands trigger above) rather than a one-shot
            # trigger, so it also catches a banned permanent entering after
            # City in a Bottle is already in play.
            if banned_set_codes:
                for player in self.players:
                    survivors_cb: list[Permanent] = []
                    for perm in player.battlefield:
                        # The card's original printing, not whichever set loaded
                        # first — see _set_lockout_banning_card.
                        card_set = perm.card.original_printing.lower()
                        if (
                            id(perm) not in banner_perm_ids
                            and not perm.metadata.get("is_token")
                            and card_set in banned_set_codes
                        ):
                            self._permanent_to_graveyard(player, perm)
                            self.log.append(f"{perm.card.name} sacrificed (City in a Bottle)")
                            changed = True
                            continue
                        survivors_cb.append(perm)
                    player.battlefield = survivors_cb

            # Old Man of the Sea: linked-duration steal ends the instant it
            # untaps OR the stolen creature's power exceeds its own (unlike
            # Aladdin's simpler "for as long as you control this creature"),
            # so it's checked continuously here rather than only on leave.
            for perm in self.all_permanents():
                if not perm.metadata.get("stolen_while_tapped_and_weaker"):
                    continue
                stolen = perm.metadata.get("stolen_permanent")
                if stolen is None:
                    continue
                if not perm.tapped or stolen.effective_power > perm.effective_power:
                    self._revert_stolen_permanent(perm)
                    perm.metadata.pop("stolen_while_tapped_and_weaker", None)
                    changed = True

            # Sandals of Abdallah: the artifact whose islandwalk target died
            # this turn is destroyed (flagged in _permanent_to_graveyard).
            for player in self.players:
                doomed_sandals = self._destroy_swept_permanents(
                    player,
                    lambda p: p.metadata.get("destroy_linked_death"),
                    allow_regeneration=False,
                )
                for artifact in doomed_sandals:
                    self.log.append(
                        f"{artifact.card.name} was destroyed (the creature it granted islandwalk died)"
                    )
                    changed = True

            # 704.5d: tokens in non-battlefield zones cease to exist
            for player in self.players:
                # Tokens that somehow ended up in graveyard/hand/exile cease to exist
                player.graveyard = [c for c in player.graveyard if not getattr(c, "_is_token", False)]

            # 704.5f: creature with toughness 0 or less → graveyard (regeneration cannot replace)
            def _zero_toughness(perm: Permanent) -> bool:
                raw_t = str(perm.card.raw.get("toughness", "0"))
                has_fixed_toughness = raw_t.lstrip("-").isdigit()
                has_dynamic_toughness = not has_fixed_toughness and "absolute_toughness" not in perm.metadata
                # is_creature (CR 613 layer 4), not the printed type line: an
                # artifact animated by Animate Artifact, or a land animated by
                # Kormus Bell, is a creature and CR 704.5f applies to it. Reading
                # the printed type meant an animated Mox sat at 0/0 forever.
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
            for player in self.players:
                for perm in player.battlefield:
                    perm.metadata.pop("received_deathtouch", None)

            # 704.5i: planeswalker with 0 loyalty → graveyard
            def _zero_loyalty(perm: Permanent) -> bool:
                if "Planeswalker" not in perm.card.type_line:
                    return False
                loyalty = perm.metadata.get("loyalty")
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
                legendary_by_name: dict[str, list[int]] = {}
                for idx, perm in enumerate(player.battlefield):
                    if "Legendary" in perm.card.type_line:
                        legendary_by_name.setdefault(perm.card.name, []).append(idx)
                for name, indices in legendary_by_name.items():
                    if len(indices) > 1:
                        # Keep first; put the rest in graveyard
                        for idx in sorted(indices[1:], reverse=True):
                            removed = player.battlefield.pop(idx)
                            self._permanent_to_graveyard(player, removed)
                            self.log.append(f"{name} put into graveyard (704.5j: legend rule)")
                        changed = True

            # 704.5k: world rule — keep only the most recently timestamped world permanent
            world_perms: list[tuple[PlayerState, int, Permanent]] = []
            for player in self.players:
                for idx, perm in enumerate(player.battlefield):
                    if "World" in perm.card.type_line:
                        world_perms.append((player, idx, perm))
            if len(world_perms) > 1:
                # Keep last (most recent timestamp = highest position), remove rest
                for player, idx, perm in world_perms[:-1]:
                    if perm in player.battlefield:
                        player.battlefield.remove(perm)
                        self._permanent_to_graveyard(player, perm)
                        self.log.append(f"{perm.card.name} put into graveyard (704.5k: world rule)")
                changed = True

            # 704.5m: Aura/Role not attached to a legal object → graveyard
            def _illegally_attached(perm: Permanent) -> bool:
                if "Aura" not in perm.card.type_line and "Role" not in perm.card.type_line:
                    return False
                if "attached_to" not in perm.metadata:
                    # Manually placed without tracking — skip 704.5m
                    return False
                attached_to = perm.metadata.get("attached_to")
                if attached_to is None:
                    return True
                return not any(attached_to in p.battlefield for p in self.players)

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

            # An Aura attached to a permanent that "can't be enchanted by other
            # Auras" (Consecrate Land) is illegally attached and is put into its
            # owner's graveyard. The Aura granting the restriction is exempt. This
            # covers Consecrate Land entering onto a land that already had Auras.
            for player in self.players:
                survivors = []
                for perm in player.battlefield:
                    attached_to = perm.metadata.get("attached_to")
                    if (
                        "Aura" in perm.card.type_line
                        and attached_to is not None
                        and self._cant_be_enchanted(attached_to)
                        and "can't be enchanted by other auras" not in perm.card.oracle_text.lower()
                    ):
                        self._permanent_to_graveyard(player, perm)
                        self.log.append(f"{perm.card.name} put into graveyard (enchanted land can't be enchanted by other Auras)")
                        changed = True
                        continue
                    survivors.append(perm)
                player.battlefield = survivors

            # CR 702.16c / 702.16n: an Aura with a quality the enchanted permanent
            # has protection from is put into its owner's graveyard, unless the
            # Aura's own text says the effect doesn't remove it (702.16n, e.g.
            # White Ward).
            for player in self.players:
                survivors = []
                for perm in player.battlefield:
                    attached_to = perm.metadata.get("attached_to")
                    if "Aura" in perm.card.type_line and attached_to is not None:
                        protection = self._protection_colors(attached_to)
                        if protection and (protection & self._effective_colors(perm)):
                            text = perm.card.oracle_text.lower()
                            exempt = "remove this aura" in text or "remove all auras" in text
                            if not exempt:
                                self._permanent_to_graveyard(player, perm)
                                self.log.append(
                                    f"{perm.card.name} put into graveyard (702.16c: enchanted permanent has protection)"
                                )
                                changed = True
                                continue
                    survivors.append(perm)
                player.battlefield = survivors

            # CR 702.16d: Equipment with a quality the equipped permanent has
            # protection from becomes unattached, but stays on the battlefield.
            for player in self.players:
                for perm in player.battlefield:
                    if "Equipment" not in perm.card.type_line:
                        continue
                    attached_to = perm.metadata.get("attached_to")
                    if attached_to is None:
                        continue
                    protection = self._protection_colors(attached_to)
                    if protection and (protection & self._effective_colors(perm)):
                        perm.metadata["attached_to"] = None
                        self.log.append(
                            f"{perm.card.name} became unattached (702.16d: equipped permanent has protection)"
                        )
                        changed = True

            # 704.5n: Equipment attached to illegal permanent → becomes unattached (stays on battlefield)
            for player in self.players:
                for perm in player.battlefield:
                    if "Equipment" not in perm.card.type_line:
                        continue
                    attached_to = perm.metadata.get("attached_to")
                    if attached_to is None:
                        continue
                    on_bf = any(attached_to in p.battlefield for p in self.players)
                    if not on_bf:
                        perm.metadata["attached_to"] = None
                        self.log.append(f"{perm.card.name} became unattached (704.5n: equipped creature left battlefield)")
                        changed = True

            # 704.5p: non-Aura, non-Equipment, non-Role permanent in attached state → unattach
            for player in self.players:
                for perm in player.battlefield:
                    if "Aura" in perm.card.type_line or "Equipment" in perm.card.type_line or "Role" in perm.card.type_line:
                        continue
                    if perm.metadata.get("attached_to") is not None:
                        perm.metadata["attached_to"] = None
                        self.log.append(f"{perm.card.name} became unattached (704.5p: illegal attached state)")
                        changed = True

            # 704.5q: +1/+1 and -1/-1 counter cancellation
            for player in self.players:
                for perm in player.battlefield:
                    plus = perm.metadata.get("plus_counters", 0)
                    minus = perm.metadata.get("minus_counters", 0)
                    if plus > 0 and minus > 0:
                        cancel = min(plus, minus)
                        perm.metadata["plus_counters"] = plus - cancel
                        perm.metadata["minus_counters"] = minus - cancel
                        self.log.append(f"{perm.card.name}: cancelled {cancel} +1/+1 and -1/-1 counters (704.5q)")
                        changed = True

            # 704.5r: counter cap enforcement
            for player in self.players:
                for perm in player.battlefield:
                    cap_info = _parse_counter_cap(perm.card.oracle_text)
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
            for player in self.players:
                for perm in player.battlefield:
                    if perm.card.primary_type != "creature":
                        continue
                    # Find all Roles attached to this creature, grouped by controller
                    roles_by_ctrl: dict[int, list[tuple[int, Permanent]]] = {}
                    for ctrl_idx, ctrl_player in enumerate(self.players):
                        for role_idx, role_perm in enumerate(ctrl_player.battlefield):
                            if "Role" not in role_perm.card.type_line:
                                continue
                            if role_perm.metadata.get("attached_to") is not perm:
                                continue
                            roles_by_ctrl.setdefault(ctrl_idx, []).append((role_idx, role_perm))
                    for ctrl_idx, roles in roles_by_ctrl.items():
                        if len(roles) <= 1:
                            continue
                        ctrl_player = self.players[ctrl_idx]
                        # Keep the last (most recent), remove the rest
                        for _, role_perm in roles[:-1]:
                            if role_perm in ctrl_player.battlefield:
                                ctrl_player.battlefield.remove(role_perm)
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

        return any_changed
