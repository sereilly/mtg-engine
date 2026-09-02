from __future__ import annotations

from ..combat_assignment import ASSIGNS_NO_COMBAT_DAMAGE
from ..cost_tap_records import TAPPED_TO_PAY_FOR
from ..combat_permissions import (ATTACK_AS_THOUGH_NO_DEFENDER,
                                  CANT_BLOCK_UNTIL_EOT)
from ..damage_events import (DAMAGE_DENIES_REGENERATION,
                             DAMAGE_EXILES_INSTEAD)
from ..target_immunity import SHROUD_WAIVED_FOR_SEATS

_MANA_SYMBOLS = ("W", "U", "B", "R", "G", "C")
_EOT_METADATA_KEYS = (
    # Riddleform's self-animation: the record *is* the effect, so sweeping it
    # here is what ends it — nothing was stashed and nothing is restored.
    "animate_until_end_of_turn",
    # "…destroy all Merfolk **tapped this turn** to pay for its abilities."
    # (Vodalian War Machine.) The window is one turn, and the sweep is what
    # says so: with no entry here the record would make "this turn" mean
    # "ever", and the trigger would reach back over the whole game.
    TAPPED_TO_PAY_FOR,
    "assign_combat_damage_as_unblocked_until_eot",
    "cant_be_blocked_until_eot",
    # "...can't be blocked **by Walls** this turn" (Tower of Coireall):
    # the narrowed twin of the flag above, a list of blocker classes rather
    # than a boolean, because the class is payload.
    "cant_be_blocked_by_until_eot",
    # "…can't be blocked this turn **except by Walls**" (Joven's Tools): the
    # whitelist twin of the entry above, and its own key because the two say
    # opposite things about every blocker neither of them names — one record
    # read as the other would let the whole board through.
    "cant_be_blocked_except_by_until_eot",
    # "Target creature **can't block** this turn." (Panic.) The other side of
    # the same combat: the two flags above are about being blocked, this one is
    # about blocking.
    CANT_BLOCK_UNTIL_EOT,
    # "Until end of turn, Autumn Willow can be the target of spells and
    # abilities controlled by target player as though it didn't have shroud."
    # The sweep *is* the duration: the waiver is a list of seats on the
    # permanent and nothing else ends it.
    SHROUD_WAIVED_FOR_SEATS,
    "must_attack_until_eot",
    "destroy_if_did_not_attack_eot",
    "destroy_if_attacked_eot",
    "attacked_this_turn",
    # "…except for creatures that **couldn't attack**." (Season of the Witch.)
    # Stamped as the declare-attackers step begins (CR 508.1), swept here with
    # its twin above: the two are one turn's record read together, and a stamp
    # that outlived the turn would exempt a creature for a combat that is over.
    "could_attack_this_turn",
    # "a creature that has been dealt damage this turn" (Giant Shark) - the
    # record damage_events.deal_damage stamps on whatever took the damage.
    "was_dealt_damage_this_turn",
    # "Damage that would be dealt to that creature this turn can't be
    # prevented or dealt instead to another permanent or player."
    # (Whippoorwill.)
    "damage_cant_be_prevented_or_redirected_until_eot",
    "redirect_one_damage_to_owner_until_eot",
    # Layer 7b temporary set effects (613.4b)
    "absolute_power_until_eot",
    "absolute_toughness_until_eot",
    # Layer 7d power/toughness switch (613.4d)
    "pt_switched",
    # CR 609.4 combat permission: "…can attack this turn as though it didn't
    # have defender" (Wall of Wonder). Named through
    # `engine/combat_permissions.py` so the write, the read and this sweep
    # cannot spell the channel three ways.
    # "This creature assigns no combat damage **this turn**." (Floral
    # Spuzzem.) The window is the whole of what the mark says, so the sweep
    # here is what ends it.
    ASSIGNS_NO_COMBAT_DAMAGE,
    ATTACK_AS_THOUGH_NO_DEFENDER,
    # Disintegrate-style riders that last only "this turn"
    "cant_be_regenerated_this_turn",
    "exile_if_dies_this_turn",
    # The same two riders held on the **damager** rather than on the damaged
    # (Runesword), named through `engine/damage_events.py` so the write, the
    # read and this sweep cannot spell the channel three ways.
    DAMAGE_DENIES_REGENERATION,
    DAMAGE_EXILES_INSTEAD,
    # Sengir Vampire damage-source tracking (cleared each turn)
    "damaged_by_sources_this_turn",
    # "…**if a creature dealt damage by this creature this turn died**"
    # (Krovikan Vampire). The other end of the record above: what a permanent
    # damaged and then outlived. Swept with it, because they are halves of one
    # turn-scoped fact and a ledger that outlived the damage record would
    # reanimate a creature on a turn nothing had died on.
    "damaged_creatures_that_died_this_turn",
    # The other direction of the same record: whom this permanent has dealt
    # damage to this turn (Whirling Dervish's intervening-if). Two keys because
    # they answer two questions and are read by two different clauses — the
    # victim's list names its killers, this one names a damager's victims.
    "dealt_damage_to_seats_this_turn",
    # Pyramids: unused land-destruction shield expires with the turn
    "land_destruction_shield_this_turn",
    # Ebony Horse: combat-damage shield on the untapped attacker
    # "One or more target creatures become red until end of turn" (Dwarven Song
    # and its four Legends siblings). The indefinite `color_override` beside it
    # is a lace and must survive the turn, which is why this is a second key
    # rather than a flag on the first.
    "color_override_until_eot",
    # "Prevent all combat damage that would be dealt by target creature this
    # turn" (Horn of Deafening, Lady Evangela). The direction is the value, so
    # the key is one rather than one per direction.
    "prevent_combat_damage_direction_until_eot",
    # "…that were blocked by that creature **this turn**" (Glyph of Doom). The
    # block pairs a blocker was part of, kept per turn because a turn holds
    # several combats and `blocked_this_combat` is cleared by each one.
    "blocked_attacker_ids_this_turn",
    # The same pairs written from the attacker's end — the blockers a creature
    # was blocked by this turn (Venomous Breath's two-way relation). Swept with
    # its mirror, or the two halves of one relation would answer for different
    # windows.
    "blocked_by_blocker_ids_this_turn",
    # The same pairs with the attacker's controller frozen beside each id
    # (Glyph of Reincarnation). Swept with the ids it keys, or a later turn's
    # sentence would read a seat from a block that is no longer in the window.
    "blocked_attacker_controllers_this_turn",
    # How many times a permanent regenerated this turn (Spiny Starfish), written
    # by ``engine/regeneration._apply``. Swept here rather than by a turn stamp
    # for the same reason its neighbours are: the window the card prints is one
    # turn, and the sweep is the only thing that says so.
    "regenerated_this_turn",
)

_TURN_PHASES: tuple[str, ...] = (
    "beginning",
    "precombat_main",
    "combat",
    "postcombat_main",
    "ending",
)

_PHASE_STEPS: dict[str, tuple[str, ...]] = {
    "beginning": ("untap", "upkeep", "draw"),
    "precombat_main": ("precombat_main",),
    "combat": (
        "beginning_of_combat",
        "declare_attackers",
        "declare_blockers",
        "combat_damage",
        "end_of_combat",
    ),
    "postcombat_main": ("postcombat_main",),
    "ending": ("end", "cleanup"),
}

# Untap and cleanup are the regular no-priority steps in this simplified engine.
_NO_PRIORITY_STEPS = {"untap", "cleanup"}

# Instruction kinds where the controller must pay mana or face a consequence.
# These require an interactive choice from a human player.
_UPKEEP_PAY_KINDS = {
    "upkeep_pay_or_sacrifice_enchantment",
    # Cyclone: escalating {G} per wind counter, or sacrifice; paying deals
    # counter-many damage to each creature and each player.
    "upkeep_wind_counter_pay_or_sacrifice",
    "upkeep_pay_or_sacrifice_self",
    # Cumulative upkeep (CR 702.24a): pay the printed cost once per age counter
    # or sacrifice. Its escalation is the same `per_counter` payload key
    # Cyclone's is, read by `cumulative_upkeep.scaled_cost`.
    "cumulative_upkeep",
    "upkeep_pay_or_deal_damage_to_controller",
    "upkeep_pay_or_tap_and_sacrifice_opponent_land",
    # Rohgahh of Kher Keep: pay {R}{R}{R} or tap Rohgahh and every creature
    # named Kobolds of Kher Keep, then an opponent gains control of them all.
    "upkeep_pay_or_cede_named_creatures",
    # Rogue Skycaptain: an escalating {2} per wage counter, or the counters come
    # off and an opponent takes the creature. CR 702.24a's ability with a
    # different decline, on the same `per_counter` payload key.
    "upkeep_counter_toll_or_cede_control",
    # Optional pays with no decline consequence — pay to untap (Mana Vault /
    # Basalt Monolith untap themselves; Paralyze untaps the enchanted creature)
    # or pay for life (Farmstead's granted enchant-land upkeep ability).
    "upkeep_pay_to_untap_self",
    "upkeep_pay_to_untap_enchanted",
    "upkeep_pay_to_gain_life",
}
