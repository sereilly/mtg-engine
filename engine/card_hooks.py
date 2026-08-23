"""Name-keyed registries for card-specific behavior.

Most cards should be handled generically by the parser (engine/grammar) and
effect handlers (engine/handlers). When a card needs truly bespoke logic that
no generic instruction covers, register it here instead of hardcoding the card
name inside engine internals. This keeps per-card behavior in one place and
lets the card pool grow without touching the core rules code.

Cast triggers used to live here as two name-keyed registries, covering six
cards whose conditions the oracle compiler already understood — they were
name-keyed only because nothing dispatched "whenever a player casts a … spell"
and because "you may pay {N}" had no generic representation. Both gaps are
closed: the condition's colour is captured into its payload and dispatched by
``engine/events.py``, and the optional cost is an ordinary ``may`` instruction.
Prefer that route before adding a registry entry here.

Hook registries:
- CARD_LINE_INSTRUCTIONS — the instruction one printed *line* of one card
                        compiles to, when that line is a single card's text
                        rather than a template. Read by engine/oracle.py.
- ON_SELF_RESOLVED    — fired when the named instant/sorcery itself resolves
                        (keyed by the resolving card's own name), for bespoke
                        effects the single compiled instruction can't express.
- ON_SPELL_COUNTERED  — fired after the named card counters a spell (keyed by
                        the counterspell's own name).
- ON_LEAVE_BATTLEFIELD — fired when the named permanent is put into a graveyard
                        from the battlefield (keyed by the permanent's name).
- DRAW_STEP_MODIFIERS — the skip-your-draw-for-protection behavior (Island
                        Sanctuary), consumed by engine/phases/draw_step. Untap
                        restrictions and symmetric bonus draws left this file:
                        they are templates, derived from oracle text by
                        engine/untap_restrictions.py and
                        engine/draw_step_modifiers.py.
- ENCHANTED_LAND_TAPPED_FOR_MANA — bespoke behavior for the Aura on a land tapped
                        for mana (Kudzu), keyed by Aura name, consumed by
                        engine/mixins/turn_management.
Cost taxes left this file too: "<colour> spells cost {N} more to cast" is a
template, derived from oracle text by engine/cost_modifiers.py. So did the
land-tapping triggers (Mana Flare, Gauntlet of Might, Lifetap) — the compiler
now produces their conditions, so they are ordinary triggered abilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from .auras import attach_aura, detach_aura
from .land_types import end_land_type_change
from .models import next_permanent_id
from .oracle_types import OracleInstruction
from .mana_payment import generic_cost, total_pips

if TYPE_CHECKING:
    from .game import Game
    from .game_types import StackItem
    from .models import CardDefinition, Permanent, PlayerState

SelfResolvedHook = Callable[["Game", "PlayerState", "CardDefinition", int, "int | None"], None]
SpellCounteredHook = Callable[["Game", "CardDefinition", "StackItem"], None]
LeaveBattlefieldHook = Callable[["Game", "PlayerState", "Permanent"], None]


# --------------------------------------------------------------------------
# Per-line instructions for texts that are one card, not a template
# --------------------------------------------------------------------------
#
# `engine/parsing/` is deleted. Most of what it claimed was templating and
# moves to a grammar production; the rest is a *single card's sentence* wired to
# a handler written for that card — Chaos Orb's flip, Camouflage's blocker
# piles, Shahrazad's subgame. The audit found 133 of its 168 rules were literal
# substring matches, several encoding a whole card's text, and a grammar
# production for one of those would be the same substring match wearing a
# grammar hat: it would report the sentence as *understood* while claiming
# nothing another card could ever share.
#
# So they come here instead, where a card name is what the file is for. This is
# not new coverage and not a regression — it is the reading `engine/parsing/`
# already had, moved to the registry that says out loud that it is per-card.
#
# **The entry bar is that no second card, real or plausibly printable, shares
# the shape.** A sentence two cards could carry belongs in `engine/grammar/`,
# where the second card gets it for free. When a line here grows a production,
# its entry goes: the grammar is consulted first (engine/oracle.py), so a stale
# entry would be dead rather than wrong — and `tests/engine/test_card_lines.py`
# fails on one, because an entry that stops being load-bearing is an entry
# nobody would notice was lying.
#
# Keys are the line as `oracle.normalize_creature_line` renders it: lowercased,
# reminder text in parentheses removed, whitespace collapsed, trailing stop
# dropped. The guard test builds them from the pool's own cards, so a key that
# no longer matches a printed line fails rather than silently never matching.


@dataclass(frozen=True)
class CardLine:
    """What one printed line of one card compiles to.

    *effect_kind* is the label the legacy rule reported (``activated_prevent``,
    ``upkeep_effect``, …). It feeds reporting — ``SimulationResult``,
    ``scripts/support_report.py`` — rather than dispatch, and is carried here so
    deleting the rule that produced it does not silently re-bucket the card.
    """

    instruction: OracleInstruction
    effect_kind: str


def _line(kind: str, effect_kind: str, **payload: object) -> CardLine:
    return CardLine(OracleInstruction(kind, "", dict(payload)), effect_kind)


CARD_LINE_INSTRUCTIONS: dict[str, dict[str, CardLine]] = {
    "Abu Ja'far": {
        'when this creature dies, destroy all creatures blocking or blocked by '
        "it. they can't be regenerated":
            _line('destroy_creatures_in_combat_with_source', 'spell_pattern',
                bypass_regeneration=True),
    },
    "Aladdin's Lamp": {
        "{x}, {t}: the next time you would draw a card this turn, instead look at "
        "the top x cards of your library, put all but one of them on the bottom of "
        "your library in a random order, then draw a card. x can't be 0":
            _line("arm_lamp_draw_replacement", "activated_draw"),
    },
    'Animate Dead': {
        'when this aura enters, if it\'s on the battlefield, it loses "enchant '
        'creature card in a graveyard" and gains "enchant creature put onto the '
        'battlefield with this aura." return enchanted creature card to the '
        'battlefield under your control and attach this aura to it. when this '
        "aura leaves the battlefield, that creature's controller sacrifices it":
            _line('reanimate_creature', 'spell_pattern'),
    },
    'Balance': {
        'each player chooses a number of lands they control equal to the number '
        'of lands controlled by the player who controls the fewest, then '
        'sacrifices the rest. players discard cards and sacrifice creatures the '
        'same way':
            _line('balance_resources', 'spell_pattern'),
    },
    'Berserk': {
        'target creature gains trample and gets +x/+0 until end of turn, where '
        'x is its power. at the beginning of the next end step, destroy that '
        'creature if it attacked this turn':
            _line('berserk_pump', 'spell_pattern'),
    },
    'Blaze of Glory': {
        'target creature defending player controls can block any number of '
        'creatures this turn. it blocks each attacking creature this turn if '
        'able':
            _line('grant_unlimited_blocking', 'spell_pattern'),
    },
    'Camouflage': {
        "this turn, instead of declaring blockers, each defending player chooses "
        "any number of creatures they control and divides them into a number of "
        "piles equal to the number of attacking creatures for whom that player is "
        "the defending player. creatures those players control that can block "
        "additional creatures may likewise be put into additional piles. assign "
        "each pile to a different one of those attacking creatures at random. each "
        "creature in a pile that can block the creature that pile is assigned to "
        "does so":
            _line("randomize_blockers", "spell_pattern"),
    },
    'Channel': {
        "until end of turn, any time you could activate a mana ability, you may "
        "pay 1 life. if you do, add {c}":
            _line("channel_life_for_mana", "spell_pattern"),
    },
    'Chaos Orb': {
        "{1}, {t}: if this artifact is on the battlefield, flip it onto the "
        "battlefield from a height of at least one foot. if this artifact turns "
        "over completely at least once during the flip, destroy all nontoken "
        "permanents it touches. then destroy this artifact":
            _line("chaos_orb_flip", "activated_chaos_orb"),
    },
    # Only the first of the two lines carries the instruction: the handler bans
    # the casting *and* sacrifices the permanents, so hooking the second line
    # too would put the same effect on the card twice.
    'City in a Bottle': {
        "whenever one or more other nontoken permanents with a name originally "
        "printed in the arabian nights expansion are on the battlefield, their "
        "controllers sacrifice them":
            _line("ban_and_sacrifice_set_permanents", "spell_pattern", set_code="arn"),
    },
    # "Put up to X +1/+0 counters on this creature" is templating the grammar
    # already parses; the sentence after it is not. The cap is what makes the
    # handler this card's — lowering the first sentence alone would let the
    # counters past seven.
    'Contract from Below': {
        'discard your hand, ante the top card of your library, then draw seven '
        'cards':
            _line('discard_hand_ante_then_draw_seven', 'spell_pattern'),
    },
    'Crumble': {
        "destroy target artifact. it can't be regenerated. that artifact's "
        'controller gains life equal to its mana value':
            _line('destroy_artifact_controller_gains_mana_value', 'spell_pattern',
                bypass_regeneration=True),
    },
    # The damage is dealt by the enchant-land pass in phases/upkeep_step.py,
    # which reads the *amount* off this instruction. Deliberately not a trigger:
    # compiling one makes the Aura deal its damage twice (pinned by
    # test_cursed_land_deals_upkeep_damage_to_land_controller).
    'Cursed Land': {
        "at the beginning of the upkeep of enchanted land's controller, this aura "
        "deals 1 damage to that player":
            _line("deal_damage", "spell_pattern", amount=1),
    },
    'Cyclone': {
        'at the beginning of your upkeep, put a wind counter on this '
        'enchantment, then sacrifice this enchantment unless you pay {g} for '
        'each wind counter on it. if you pay, this enchantment deals damage '
        'equal to the number of wind counters on it to each creature and each '
        'player':
            _line('upkeep_wind_counter_pay_or_sacrifice', 'upkeep_effect'),
    },
    'Cyclopean Tomb': {
        "{2}, {t}: put a mire counter on target non-swamp land. that land is a "
        "swamp for as long as it has a mire counter on it. activate only during "
        "your upkeep":
            _line("add_mire_counter_to_target_land", "activated_landtype"),
    },
    'Darkpact': {
        'you own target card in the ante. exchange that card with the top card '
        'of your library':
            _line('exchange_ante_with_top_library', 'spell_pattern'),
    },
    'Demonic Attorney': {
        'each player antes the top card of their library':
            _line('each_player_antes_top_card', 'spell_pattern'),
    },
    'Demonic Hordes': {
        "at the beginning of your upkeep, unless you pay {b}{b}{b}, tap this "
        "creature and sacrifice a land of an opponent's choice":
            _line(
                "upkeep_pay_or_tap_and_sacrifice_opponent_land", "upkeep_effect",
                mana={"W": 0, "U": 0, "B": 3, "R": 0, "G": 0, "C": 0, "generic": 0},
            ),
    },
    'Diamond Valley': {
        '{t}, sacrifice a creature: you gain life equal to the sacrificed '
        "creature's toughness":
            _line('sacrifice_creature_gain_life_by_toughness',
                'activated_gain_life'),
    },
    'Dragon Whelp': {
        "{r}: this creature gets +1/+0 until end of turn. if this ability has been "
        "activated four or more times this turn, sacrifice this creature at the "
        "beginning of the next end step":
            _line("pump_self_with_sacrifice_condition", "activated_pump"),
    },
    'Drain Life': {
        'drain life deals x damage to any target. you gain life equal to the '
        "damage dealt, but not more life than the player's life total before "
        "the damage was dealt, the planeswalker's loyalty before the damage was "
        "dealt, or the creature's toughness":
            _line('deal_damage_and_gain_life', 'spell_pattern', amount='x'),
    },
    'Drain Power': {
        'target player activates a mana ability of each land they control. then '
        'that player loses all unspent mana and you add the mana lost this way':
            _line('drain_target_lands_mana', 'spell_pattern'),
    },
    'Drop of Honey': {
        "at the beginning of your upkeep, destroy the creature with the least "
        "power. it can't be regenerated. if two or more creatures are tied for "
        "least power, you choose one of them":
            _line("upkeep_destroy_least_power_creature", "upkeep_effect"),
    },
    'Earthbind': {
        'when this aura enters, if enchanted creature has flying, this aura '
        'deals 2 damage to that creature and this aura gains "enchanted '
        'creature loses flying."':
            _line('deal_damage', 'spell_pattern', amount=2),
    },
    'Ebony Horse': {
        '{2}, {t}: untap target attacking creature you control. prevent all '
        'combat damage that would be dealt to and dealt by that creature this '
        'turn':
            _line('untap_attacker_and_prevent_combat_damage', 'spell_pattern'),
    },
    'El-Hajjâj': {
        'whenever this creature deals damage, you gain that much life':
            _line('gain_life_equal_to_damage_dealt', 'triggered_gain_life'),
    },
    'Erg Raiders': {
        "at the beginning of your end step, if this creature didn't attack this "
        "turn, it deals 2 damage to you unless it came under your control this turn":
            _line("end_step_damage_if_not_attacked", "triggered_damage", amount=2),
    },
    'Erhnam Djinn': {
        'at the beginning of your upkeep, target non-wall creature an opponent '
        'controls gains forestwalk until your next upkeep':
            _line('grant_forestwalk_until_next_upkeep', 'upkeep_effect'),
    },
    'Eye for an Eye': {
        "the next time a source of your choice would deal damage to you this turn, "
        "instead that source deals that much damage to you and eye for an eye "
        "deals that much damage to that source's controller":
            _line("arm_mirror_damage", "spell_pattern"),
    },
    'False Orders': {
        "remove target creature defending player controls from combat. creatures "
        "it was blocking that had become blocked by only that creature this combat "
        "become unblocked. you may have it block an attacking creature of your choice":
            _line("remove_creature_from_combat", "spell_pattern"),
    },
    'Farmstead': {
        'enchanted land has "at the beginning of your upkeep, you may pay '
        '{w}{w}. if you do, you gain 1 life."':
            _line('target_gains_life', 'spell_pattern', amount=1,
                recipient='caster'),
    },
    'Forcefield': {
        "{1}: the next time an unblocked creature of your choice would deal combat "
        "damage to you this turn, prevent all but 1 of that damage":
            _line("grant_forcefield_shield", "activated_prevent"),
    },
    # `copy_top_stack_spell` copies the top of the stack rather than the named
    # target, and the two riders ("except that the copy is red", the optional
    # retarget) are the handler's own. All three are Fork's, not a shape.
    'Fork': {
        "copy target instant or sorcery spell, except that the copy is red. you "
        "may choose new targets for the copy":
            _line("copy_top_stack_spell", "spell_pattern"),
    },
    "Gaea's Liege": {
        '{t}: target land becomes a forest until this creature leaves the '
        'battlefield':
            _line('change_target_land_type', 'activated_landtype',
                land_type='forest'),
    },
    'Ghazbán Ogre': {
        "at the beginning of your upkeep, if a player has more life than each "
        "other player, the player with the most life gains control of this creature":
            _line("upkeep_most_life_gains_control", "upkeep_effect"),
    },
    # The first sentence is an ordinary numeric shield the grammar can read; the
    # rest of the line grants an activatable emblem, which is ON_SELF_RESOLVED
    # above. Claiming only the shield would drop the emblem silently, so the
    # whole line is one entry and the two halves stay in the same file.
    'Guardian Angel': {
        "prevent the next x damage that would be dealt to any target this turn. "
        "until end of turn, you may pay {1} any time you could cast an instant. if "
        "you do, prevent the next 1 damage that would be dealt to that permanent "
        "or player this turn":
            _line(
                "grant_prevention_shield", "spell_pattern",
                amount="x", to_self=False, to_source=False,
            ),
    },
    "Hurkyl's Recall": {
        'return all artifacts target player owns to their hand':
            _line('return_all_owned_artifacts_to_hand', 'spell_pattern'),
    },
    'Illusionary Mask': {
        '{x}: you may choose a creature card in your hand whose mana cost could '
        'be paid by some amount of, or all of, the mana you spent on {x}. if '
        'you do, you may cast that card face down as a 2/2 creature spell '
        'without paying its mana cost. if the creature that spell becomes as it '
        'resolves has not been turned face up and would assign or deal damage, '
        "be dealt damage, or become tapped, instead it's turned face up and "
        'assigns or deals damage, is dealt damage, or becomes tapped. activate '
        'only as a sorcery':
            _line('cast_face_down_creature', 'activated_cast'),
    },
    'Ivory Tower': {
        'at the beginning of your upkeep, you gain x life, where x is the '
        'number of cards in your hand minus 4':
            _line('upkeep_gain_life_over_hand_size', 'upkeep_effect', floor=4),
    },
    'Jade Monolith': {
        "{1}: the next time a source of your choice would deal damage to target "
        "creature this turn, that source deals that damage to you instead":
            _line("jade_monolith_redirect", "activated_prevent"),
    },
    'Jade Statue': {
        '{2}: this artifact becomes a 3/6 golem artifact creature until end of '
        'combat. activate only during combat':
            _line('animate_self_until_end_of_combat', 'activated_animate', power=3,
                toughness=6),
    },
    'Jeweled Bird': {
        "{t}: ante this artifact. if you do, put all other cards you own from the "
        "ante into your graveyard, then draw a card":
            _line("ante_self_then_clear_ante_and_draw", "activated_ante"),
    },
    'Lord of the Pit': {
        "at the beginning of your upkeep, sacrifice a creature other than this "
        "creature. if you can't, this creature deals 7 damage to you":
            _line(
                "upkeep_sacrifice_other_creature_or_deal_damage", "upkeep_effect",
                damage=7,
            ),
    },
    'Magnetic Mountain': {
        "at the beginning of each player's upkeep, that player may choose any "
        'number of tapped blue creatures they control and pay {4} for each '
        'creature chosen this way. if the player does, untap those creatures':
            _line('upkeep_pay_per_creature_untap_color', 'upkeep_effect', color='U',
                cost_per=4),
    },
    'Mana Short': {
        'tap all lands target player controls and that player loses all unspent '
        'mana':
            _line('tap_target_player_lands_and_drain_mana', 'spell_pattern'),
    },
    # "attacks and isn't blocked" is not a condition the trigger tables carry:
    # combat_damage_step.py finds this trigger by its `creature_attacks`
    # condition and then re-reads the source line for the rider. Until that
    # condition exists, a production would have to drop the rider — which is the
    # legacy rule's bug, not a migration of it.
    'Merchant Ship': {
        "whenever this creature attacks and isn't blocked, you gain 2 life":
            _line("target_gains_life", "spell_pattern", amount=2, recipient="caster"),
    },
    # Mana bought with the mana value of the creature its additional cost ate.
    # The cost itself is not the hook's — it is the general CR 601.2b table
    # (engine/cast_costs.py), paid while casting — so the key is the *effect*
    # sentence alone. Sacrifice's plainer spelling ("an amount of {B} equal to
    # the sacrificed creature's mana value") is a production now and its entry
    # went with it; what keeps this one is the "1 plus" and the spend
    # restriction, which no second card prints together.
    'Metamorphosis': {
        "add x mana of any one color, where x is 1 plus the sacrificed creature's "
        "mana value. spend this mana only to cast creature spells":
            _line("sacrifice_creature_for_mana", "spell_pattern",
                color=None, bonus=1, spend_only="creature"),
    },
    'Mijae Djinn': {
        "whenever this creature attacks, flip a coin. if you lose the flip, remove "
        "this creature from combat and tap it":
            _line("coin_flip_remove_attacker_and_tap", "triggered_coin_flip"),
    },
    "Mishra's War Machine": {
        'at the beginning of your upkeep, this creature deals 3 damage to you '
        'unless you discard a card. if it deals damage to you this way, tap it':
            _line('upkeep_damage_unless_discard', 'upkeep_effect', amount=3,
                taps_source=True),
    },
    'Nafs Asp': {
        "whenever this creature deals damage to a player, that player loses 1 life "
        "at the beginning of their next draw step unless they pay {1} before that "
        "draw step":
            _line(
                "arm_draw_step_life_loss_unless_pay", "triggered_delayed_life_loss",
                amount=1, cost=1,
            ),
    },
    'Natural Selection': {
        "look at the top three cards of target player's library, then put them "
        'back in any order. you may have that player shuffle':
            _line('reorder_target_library_top', 'spell_pattern'),
    },
    'Nether Shadow': {
        "at the beginning of your upkeep, if this card is in your graveyard with "
        "three or more creature cards above it, you may put this card onto the "
        "battlefield":
            _line(
                "upkeep_return_self_from_graveyard", "upkeep_effect",
                min_creatures_above=3,
            ),
    },
    'Nettling Imp': {
        "{t}: choose target non-wall creature the active player has controlled "
        "continuously since the beginning of the turn. that creature attacks this "
        "turn if able. destroy it at the beginning of the next end step if it "
        "didn't attack this turn. activate only during an opponent's turn, before "
        "attackers are declared":
            _line("mark_non_wall_target_to_attack", "activated_combat"),
    },
    # Aladdin's linked steal is a production (one condition, "for as long as you
    # control this"); this one is not. Its duration is two conditions, one of
    # them a comparison against the source's own power that is re-checked
    # continuously in game_ending.py — there is no second card to share it with.
    'Old Man of the Sea': {
        "{t}: gain control of target creature with power less than or equal to "
        "this creature's power for as long as this creature remains tapped and "
        "that creature's power remains less than or equal to this creature's power":
            _line("steal_creature_while_tapped_and_weaker", "activated_steal"),
    },
    'Oubliette': {
        'when this enchantment enters, target creature phases out until this '
        'enchantment leaves the battlefield. tap that creature as it phases in '
        'this way':
            _line('phase_out_target_creature_until_source_leaves', 'spell_pattern'),
    },
    'Paralyze': {
        "at the beginning of the upkeep of enchanted creature's controller, "
        'that player may pay {4}. if the player does, untap the creature':
            _line('upkeep_pay_to_untap_enchanted', 'upkeep_effect', mana={'W': 0,
                'U': 0, 'B': 0, 'R': 0, 'G': 0, 'C': 0, 'generic': 4}),
    },
    'Personal Incarnation': {
        "{0}: the next 1 damage that would be dealt to this creature this turn is "
        "dealt to its owner instead. only this creatures owner may activate this "
        "ability":
            _line("redirect_one_damage_to_owner", "activated_prevent"),
        "when this creature dies, its owner loses half their life, rounded up":
            _line("owner_loses_half_life", "triggered_loss"),
    },
    'Pestilence': {
        "at the beginning of the end step, if no creatures are on the battlefield, "
        "sacrifice this enchantment":
            _line("sacrifice_if_no_creatures", "triggered_sacrifice"),
    },
    'Power Leak': {
        "at the beginning of the upkeep of enchanted enchantment's controller, "
        'that player may pay any amount of mana. this aura deals 2 damage to '
        'that player. prevent x of that damage, where x is the amount of mana '
        'that player paid this way':
            _line('deal_damage', 'spell_pattern', amount=2),
    },
    # Two bullets of one modal activated ability, hooked separately. The
    # destroy half is not the generic destroy production's shape: "Aura attached
    # to a land" is a restriction `_filter_payload` has no field for, and the
    # handler reads it as `attached_to_land`.
    'Pyramids': {
        "{2}: the next time target land would be destroyed this turn, remove all "
        "damage marked on it instead":
            _line("shield_target_land_from_destruction", "activated_prevent"),
        '{2}: destroy target aura attached to a land':
            _line('destroy_target_permanent', 'activated_destroy',
                type_filter='enchantment', attached_to_land=True),
    },
    'Raging River': {
        'whenever one or more creatures you control attack, each defending '
        'player divides all creatures without flying they control into a "left" '
        'pile and a "right" pile. then, for each attacking creature you '
        'control, choose "left" or "right." that creature can\'t be blocked this '
        'combat except by creatures with flying and creatures in a pile with '
        'the chosen label':
            _line('left_right_combat_division', 'triggered_combat'),
    },
    'Reverse Damage': {
        'the next time a source of your choice would deal damage to you this '
        'turn, prevent that damage. you gain life equal to the damage prevented '
        'this way':
            _line('grant_reverse_damage_shield', 'spell_pattern'),
    },
    'Reverse Polarity': {
        'you gain x life, where x is twice the damage dealt to you so far this '
        'turn by artifacts':
            _line('gain_twice_artifact_damage_taken', 'spell_pattern'),
    },
    "Ring of Ma'rûf": {
        "{5}, {t}, exile this artifact: the next time you would draw a card this "
        "turn, instead put a card you own from outside the game into your hand":
            _line("arm_outside_game_draw_replacement", "activated_draw"),
    },
    'Rukh Egg': {
        'when this creature dies, create a 4/4 red bird creature token with '
        'flying at the beginning of the next end step':
            _line('arm_end_step_token', 'triggered_token', name='Bird Token',
                power=4, toughness=4, type_line='Creature — Bird',
                colors=('R',), keywords=('Flying',)),
    },
    'Sandals of Abdallah': {
        "{2}, {t}: target creature gains islandwalk until end of turn. when that "
        "creature dies this turn, destroy this artifact":
            _line("grant_islandwalk_and_linked_destroy", "activated_keyword"),
    },
    'Serendib Djinn': {
        "at the beginning of your upkeep, sacrifice a land. if you sacrifice an "
        "island this way, this creature deals 3 damage to you":
            _line(
                "upkeep_sacrifice_land_conditional_damage", "upkeep_effect",
                land_type="island", damage=3,
            ),
    },
    'Shahrazad': {
        "players play a magic subgame, using their libraries as their decks. each "
        "player who doesn't win the subgame loses half their life, rounded up":
            _line("opponents_lose_half_life", "spell_pattern"),
    },
    'Simulacrum': {
        'you gain life equal to the damage dealt to you this turn. simulacrum '
        'deals damage to target creature you control equal to the damage dealt '
        'to you this turn':
            _line('simulacrum_redirect', 'spell_pattern'),
    },
    'Sindbad': {
        "{t}: draw a card and reveal it. if it isn't a land card, discard it":
            _line('draw_reveal_discard_unless_land', 'activated_draw'),
    },
    "Siren's Call": {
        'creatures the active player controls attack this turn if able':
            _line('force_active_player_creatures_to_attack', 'spell_pattern'),
    },
    'Stone Giant': {
        "{t}: target creature you control with toughness less than this creature's "
        "power gains flying until end of turn. destroy that creature at the "
        "beginning of the next end step":
            _line("grant_flying_and_delayed_destruction", "activated_keyword"),
    },
    'The Rack': {
        "at the beginning of the chosen player's upkeep, this artifact deals x "
        'damage to that player, where x is 3 minus the number of cards in their '
        'hand':
            _line('upkeep_chosen_player_hand_overflow_damage', 'upkeep_effect',
                base=3, direction='deficit'),
    },
    'Timetwister': {
        'each player shuffles their hand and graveyard into their library, then '
        'draws seven cards':
            _line('timetwister', 'spell_pattern'),
    },
    'Twiddle': {
        'you may tap or untap target artifact, creature, or land':
            _line('tap_or_untap_target', 'spell_pattern'),
    },
    'Unstable Mutation': {
        "at the beginning of the upkeep of enchanted creature's controller, put "
        'a -1/-1 counter on that creature':
            _line('add_minus1_counter_to_enchanted', 'upkeep_effect'),
    },
    'Volcanic Eruption': {
        'destroy x target mountains. volcanic eruption deals damage to each '
        'creature and each player equal to the number of mountains put into a '
        'graveyard this way':
            _line('volcanic_eruption', 'spell_pattern'),
    },
    'Wheel of Fortune': {
        'each player discards their hand, then draws seven cards':
            _line('wheel_of_fortune', 'spell_pattern'),
    },
    'Word of Command': {
        "look at target opponent's hand and choose a card from it. you control "
        'that player until word of command finishes resolving. the player plays '
        'that card if able. while doing so, the player can activate mana '
        "abilities only if they're from lands that player controls and only if "
        'mana they produce is spent to activate other mana abilities of lands '
        'the player controls and/or to play that card. if the chosen card is '
        'cast as a spell, you control the player while that spell is resolving':
            _line('peek_hand_and_force_play', 'spell_pattern'),
    },
    'Ydwen Efreet': {
        "whenever this creature blocks, flip a coin. if you lose the flip, remove "
        "this creature from combat and it can't block this turn. creatures it was "
        "blocking that had become blocked by only this creature this combat become "
        "unblocked":
            _line("coin_flip_remove_blocker", "triggered_coin_flip"),
    },
}


def card_line_instruction(card_name: str | None, normalized_line: str) -> CardLine | None:
    """The registered reading of *normalized_line* on the card named *card_name*.

    Both halves of the key matter. Keying on the text alone would make this a
    second `engine/parsing/` — a table any card could match by wording — and
    keying on the name alone would claim every line of the card, including the
    ones a production already reads.
    """
    if not card_name:
        return None
    return CARD_LINE_INSTRUCTIONS.get(card_name, {}).get(normalized_line)


def _guardian_angel(
    game: Game,
    caster: PlayerState,
    resolved_card: CardDefinition,
    target_player_index: int,
    target_permanent_index: int | None,
) -> None:
    # The first sentence (prevent the next X damage) resolves through the compiled
    # instruction. This hook adds the second sentence's granted ability: an emblem
    # the caster may activate ("pay {1}: prevent next 1 damage") until end of turn.
    # "That permanent or player" is the spell's original target, so the emblem
    # remembers it and never re-prompts on activation.
    caster.prevent_one_damage_emblems.append({
        "target_player_index": target_player_index,
        "target_permanent_index": target_permanent_index,
    })
    game.log.append(f"{caster.name} gains a Guardian Angel prevention emblem until end of turn")


ON_SELF_RESOLVED: dict[str, SelfResolvedHook] = {
    "Guardian Angel": _guardian_angel,
}


def _power_sink(game: Game, counter_card: CardDefinition, countered: StackItem) -> None:
    ctrl = game.players[countered.caster_index]
    for perm in game.controlled_by(countered.caster_index):
        if perm.card.primary_type == "land":
            game.become_tapped(perm)
    ctrl.mana_pool = {k: 0 for k in ctrl.mana_pool}
    game.log.append(f"{counter_card.name} tapped all lands and drained mana from {ctrl.name}")


ON_SPELL_COUNTERED: dict[str, SpellCounteredHook] = {
    "Power Sink": _power_sink,
}


def _cyclopean_tomb_leaves(game: Game, owner: PlayerState, permanent: Permanent) -> None:
    # "When this artifact is put into a graveyard from the battlefield, at the
    # beginning of each of your upkeeps for the rest of the game, remove all mire
    # counters from a land that a mire counter was put onto with this artifact but
    # that a mire counter has not been removed from with this artifact."
    #
    # Set up a rest-of-game obligation that removes the mire counter from one such
    # land per upkeep (drained in Game.resolve_upkeep). Only lands that are still
    # mired qualify — any whose counter was already removed are excluded.
    mired = permanent.metadata.get("mired_lands") or []
    remaining = [land for land in mired if land.metadata.get("mire_counter")]
    if not remaining:
        return
    controller_index = game.players.index(owner)
    game.mire_cleanup_obligations.append(
        {"controller_index": controller_index, "lands": remaining}
    )
    game.log.append(
        f"{permanent.card.name} left the battlefield; "
        f"{len(remaining)} mired land(s) will be freed over future upkeeps"
    )


def _consecrate_land_leaves(game: Game, owner: PlayerState, permanent: Permanent) -> None:
    # "Enchanted land has indestructible and can't be enchanted by other Auras."
    # Both are continuous effects from this Aura — when it leaves the battlefield
    # the enchanted land loses indestructibility and may again be enchanted.
    land = permanent.metadata.get("attached_to")
    if land is None:
        return
    land.metadata.pop("is_indestructible", None)
    land.metadata.pop("cant_be_enchanted_by_auras", None)
    detach_aura(permanent, land)


def _gaeas_liege_leaves(game: Game, owner: PlayerState, permanent: Permanent) -> None:
    # "{T}: Target land becomes a Forest until this creature leaves the
    # battlefield." When Gaea's Liege leaves, the lands it forested revert to
    # their printed type (CR 611.3 — the duration ends).
    # Dropping this creature's own contribution, not clearing the land's type:
    # the land goes back to whatever the *remaining* effects say it is, which is
    # what "the duration ended" means. Reading the stored type back to check it
    # was still Forest was the bookkeeping this replaces — and it was wrong
    # whenever something newer had made the land something else, since the
    # Liege's effect would then have gone on applying invisibly.
    reverted = 0
    for land in permanent.metadata.get("forested_lands", []) or []:
        if end_land_type_change(land, source=permanent):
            reverted += 1
    if reverted:
        game.log.append(
            f"{permanent.card.name} left the battlefield; {reverted} land(s) reverted from Forest"
        )
    game._refresh_dynamic_creatures()


def _revert_linked_steal_on_leave(game: Game, owner: PlayerState, permanent: Permanent) -> None:
    # A linked-duration "gain control for as long as you control this" steal
    # (Aladdin's artifact, Old Man of the Sea's creature) ends when its source
    # leaves the battlefield (CR 611.3), mirroring how Control Magic / Steal
    # Artifact revert when their Aura leaves. Old Man's other end conditions
    # (untaps / stolen power exceeds its own) are swept continuously in
    # game_ending.py.
    game.end_control_changes_from(permanent)


def _oubliette_leaves(game: Game, owner: PlayerState, permanent: Permanent) -> None:
    # "Target creature phases out until this enchantment leaves the
    # battlefield. Tap that creature as it phases in this way." Scoped
    # exile-and-return (not full CR 702.26 phasing) tracked on Oubliette
    # itself — the phased creature and any Auras/Equipment that phased out
    # with it return, tapped, when Oubliette leaves.
    phased = permanent.metadata.pop("phased_out_permanent", None)
    owner_index = permanent.metadata.pop("phased_out_owner_index", None)
    attachments = permanent.metadata.pop("phased_out_attachments", None) or []
    # CR 400.7: this is the one path that puts the *same* ``Permanent`` object
    # back on the battlefield, so the new-object rule has to be applied by hand
    # — anything still holding the pre-phase-out id must not resolve to it.
    if phased is not None and isinstance(owner_index, int) and 0 <= owner_index < len(game.players):
        phased.tapped = True
        phased.permanent_id = next_permanent_id()
        game.players[owner_index].battlefield.append(phased)
        game.log.append(
            f"{phased.card.name} phases back in, tapped ({permanent.card.name} left the battlefield)"
        )
    for seat, attached_perm in attachments:
        if 0 <= seat < len(game.players):
            attached_perm.permanent_id = next_permanent_id()
            game.players[seat].battlefield.append(attached_perm)


ON_LEAVE_BATTLEFIELD: dict[str, LeaveBattlefieldHook] = {
    "Cyclopean Tomb": _cyclopean_tomb_leaves,
    "Consecrate Land": _consecrate_land_leaves,
    "Gaea's Liege": _gaeas_liege_leaves,
    "Aladdin": _revert_linked_steal_on_leave,
    "Old Man of the Sea": _revert_linked_steal_on_leave,
    "Oubliette": _oubliette_leaves,
}


# --------------------------------------------------------------------------
# Resolve-time trigger hooks
# --------------------------------------------------------------------------
# A triggered ability whose effect is a name-keyed hook is put on the stack like
# any other trigger. When it resolves, resolve_top_of_stack dispatches to
# TRIGGER_HOOKS[stack_item.hook_key], passing the StackItem; the handler reads
# stack_item.hook_event (captured when the trigger fired) and runs the effect.
# This is how the Rod/Cup/Sphere cycle and Verduran Enchantress raise their
# "you may pay {1} / draw a card" prompts at resolution rather than at fire time.

TriggerStackHook = Callable[["Game", "StackItem"], None]


def _resolve_optional_pay_trigger(game: Game, item: StackItem) -> None:
    """Resolve a deferred "you may pay {N}: gain life" / "you may draw a card"
    trigger (the color Rods, Verduran Enchantress). The pay/draw prompt is registered
    here — at resolution — so it appears only after the trigger leaves the stack,
    matching the Soul Net death-trigger behavior. A paid rider (Rods) is offered only
    when the controller can actually pay the {N}; a free rider (Verduran's draw) is
    always offered."""
    ev = item.hook_event or {}
    player_index = ev.get("player_index")
    if player_index is None or not (0 <= player_index < len(game.players)):
        return
    cost = generic_cost(int(ev.get("cost", 0)))
    entry: dict = {
        "card_name": ev["card_name"],
        "cost": cost,
        "life": int(ev.get("life", 0)),
    }
    if total_pips(cost) > 0 and not game._player_can_pay_optional(
        game.players[player_index], entry
    ):
        return
    if "draw" in ev:
        entry["draw"] = ev["draw"]
    if "prompt" in ev:
        entry["prompt"] = ev["prompt"]
    game.arm_pending_choice("optional_pay", player_index, **entry)


# hook_key → resolver.
TRIGGER_HOOKS: dict[str, TriggerStackHook] = {
    "optional_pay": _resolve_optional_pay_trigger,
}


# --------------------------------------------------------------------------
# Untap-step restrictions (CR 502) — moved out
# --------------------------------------------------------------------------
# Stasis, Winter Orb, Smoke, Meekstone and Magnetic Mountain used to be five
# name-keyed UntapRestriction entries here. Their wordings are templates, so
# the restriction is now derived from oracle text in
# engine/untap_restrictions.py and a card printed with one of those templates
# needs no registration at all.


# --------------------------------------------------------------------------
# Untapped artifact protectors
# --------------------------------------------------------------------------
# Guardian Beast: "As long as this creature is untapped, noncreature artifacts
# you control can't be enchanted, have indestructible, and other players
# can't gain control of them." Checked by
# effects.py:_untapped_artifact_protector_active at each relevant site
# (destroy, enchant-target legality, control-change legality) rather than
# precomputed, since the protection tracks the source's tapped state.

UNTAPPED_ARTIFACT_PROTECTORS: frozenset[str] = frozenset({"Guardian Beast"})


# --------------------------------------------------------------------------
# Top-of-library discard replacements — moved out
# --------------------------------------------------------------------------
# Library of Leng was a name-keyed frozenset here. It is now a text-keyed
# `discard` replacement in engine/replacements.py, offering the optional
# destination as a ReplacementChoice.


# --------------------------------------------------------------------------
# Draw-step modifiers (CR 504)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class DrawStepModifier:
    """Draw-step behavior granted by a permanent.

    optional_skip_grants_protection -- its controller may skip their draw to
                  gain "attack only me with flyers" protection (Island Sanctuary)
    """

    optional_skip_grants_protection: bool = False


# Howling Mine's "that player draws an additional card" moved out to
# engine/draw_step_modifiers.py: it is a template a long line of cards
# reprints, so it is derived from oracle text instead of registered here.
# Island Sanctuary stays because the quality it grants protection against
# ("creatures with flying and/or islandwalk") is specific to the card — until
# a second card grants a different quality there is nothing to generalize.
DRAW_STEP_MODIFIERS: dict[str, DrawStepModifier] = {
    "Island Sanctuary": DrawStepModifier(optional_skip_grants_protection=True),
}


# --------------------------------------------------------------------------
# Land-tapping triggers — moved out
# --------------------------------------------------------------------------
# Mana Flare, Gauntlet of Might and Lifetap were three name-keyed entries here,
# across two registries (MANA_PRODUCTION_MODIFIERS and ON_BECOMES_TAPPED). All
# three are templates the compiler now reads:
#
#   "Whenever a <type> [an opponent controls] becomes tapped, …" compiles to a
#   `permanent_becomes_tapped` condition carrying the type and the controller
#   scope as payload, dispatched by engine/events.py.
#   "Whenever a [<land type>] is tapped for mana, <player> adds …" compiles to
#   `land_tapped_for_mana` plus an `add_mana_for_tapped_land` instruction,
#   resolved inline by Game.tap_land_for_mana (CR 605.4a — a triggered mana
#   ability never uses the stack).
#
# A card printed with either template needs no registration at all.


# --------------------------------------------------------------------------
# Enchanted-land "when tapped for mana" bespoke effects
# --------------------------------------------------------------------------
# Fired for the Aura enchanting a land that was just tapped for mana, when the
# Aura needs behavior the generic paths can't express — beyond the
# enchanted_land_tapped trigger (Psychic Venom) and the "adds an additional"
# mana clause (Wild Growth) both handled inline in tap_land_for_mana. Keyed by
# Aura name. Signature: (game, controller_index, land, land_index, aura,
# reattach_index, defer_choice).

EnchantedLandTappedHook = Callable[
    ["Game", int, "Permanent", int, "Permanent", "int | None", bool], None
]


def _kudzu_on_land_tapped(
    game: Game,
    controller_index: int,
    land: Permanent,
    land_index: int,
    aura: Permanent,
    reattach_index: int | None,
    defer_choice: bool,
) -> None:
    """Kudzu: "Whenever enchanted land is tapped for mana, destroy that land.
    That land's controller may attach Kudzu to a land of their choice." The
    reattach target comes from ``reattach_index``; with no explicit choice a
    human controller defers to an interactive prompt (``pending_kudzu_reattach``,
    resolved by ``confirm_kudzu_reattach``), while AI/headless play deterministically
    takes the first other land."""
    player = game.players[controller_index]
    game.remove_from_battlefield(land)
    player.graveyard.append(land.card)
    aura.metadata.pop("attached_to", None)
    detach_aura(aura, land)
    game.log.append(f"Kudzu destroyed {land.card.name}")
    new_land = None
    if (
        isinstance(reattach_index, int)
        and 0 <= reattach_index < len(player.battlefield)
        and player.battlefield[reattach_index].card.primary_type == "land"
    ):
        new_land = player.battlefield[reattach_index]
    # A controller who is being asked picks the land to re-enchant: defer when no
    # choice was supplied and there is a land to move to. Headless/AI play keeps
    # the deterministic "first other land" default below.
    if new_land is None and defer_choice and any(
        p.card.primary_type == "land" for p in game.controlled_by(controller_index)
    ):
        game.arm_pending_choice("kudzu_reattach", controller_index, aura=aura)
        return
    if new_land is None:
        new_land = next(
            (p for p in game.controlled_by(controller_index) if p.card.primary_type == "land"),
            None,
        )
    if new_land is not None:
        attach_aura(aura, new_land)
        game.log.append(f"Kudzu attached to {new_land.card.name}")


ENCHANTED_LAND_TAPPED_FOR_MANA: dict[str, EnchantedLandTappedHook] = {
    "Kudzu": _kudzu_on_land_tapped,
}


# --------------------------------------------------------------------------
# Cost modifiers — moved out
# --------------------------------------------------------------------------
# Gloom was two hand-written functions keyed by name. "<colour> spells cost
# {N} more to cast" is a template Magic reprints constantly, so the tax is
# now derived from oracle text in engine/cost_modifiers.py.
