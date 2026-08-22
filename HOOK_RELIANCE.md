# Hook Reliance

How much of the card pool is supported by having its **name** written down — `engine/card_hooks.py`, the one sanctioned place to key behaviour on a card name — rather than by having its text read.

Every individual entry there is defensible and guarded; this is the measure of the pile. A name-keyed entry costs one hand-written rule and buys one card. A grammar production costs one and buys every card printed with that template. So this fraction is the engine's marginal cost per card, and it is the number that decides whether the architecture reaches the full release line.

**Generated** — run `python scripts/hook_reliance.py` to refresh.

The measures are **ceilings**, the opposite direction to `GRAMMAR_COVERAGE.md`'s floors and for the same reason: there the hazard is the general reader losing ground, here it is the special-case readers gaining it.

**Every percentage below is over *supported* cards**, and the measure names say so. A card the engine cannot play is not a card a hook is carrying, so counting it would mean that ingesting a set supported at 30% inflates the denominator, leaves the numerator behind, and reports *falling* reliance — a ceiling passing because the pool got harder. Support rate is reported beside the measures as pool reach, which is a real number and a different question.

## The headline

**92 of 668 supported cards (13.8%)** carry at least one name-keyed entry, across **98 entries** in 7 registries. The pool is 668 cards, 100.0% supported.

Held at this rate, supporting the 26,113-card release line would need about **3,831 hand-written entries** covering **3,596 cards**. That projection is the point of the number, not a forecast: it is the cost of assuming the current sample is representative, and the sample is five sets from 1993–94.

## By set

| Set | Cards | Supported | Hooked cards | Rules lines | Hooked lines | Entries | Entries/100 supported |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| LEA | 290 | 290 (100.0%) | 51 (17.6%) | 388 | 46 (11.9%) | 55 | 19.0 |
| LEB | 292 | 292 (100.0%) | 51 (17.5%) | 389 | 46 (11.8%) | 55 | 18.8 |
| 2ED | 292 | 292 (100.0%) | 51 (17.5%) | 389 | 46 (11.8%) | 55 | 18.8 |
| ARN | 78 | 78 (100.0%) | 32 (41.0%) | 107 | 30 (28.0%) | 35 | 44.9 |
| 3ED | 296 | 296 (100.0%) | 54 (18.2%) | 389 | 46 (11.8%) | 56 | 18.9 |
| M21 | 285 | 285 (100.0%) | 0 (0.0%) | 503 | 0 (0.0%) | 0 | 0.0 |
| ATQ *(measured)* | 85 | 83 (97.6%) | 9 (10.8%) | 117 | 6 (5.1%) | 8 | 9.6 |
| **ALL (shipped, deduped)** | **668** | **668 (100.0%)** | **92 (13.8%)** | **1022** | **82 (8.0%)** | **98** | **14.7** |

*(measured)* — ATQ are ingested for measurement and **not shipped**: `cards/manifest.json` lists them under `measured`, the engine's catalog does not load them, and no player can put one in a deck. They are reported here and excluded from the ALL row and from the ceilings, because a ratchet over a set nobody has implemented would fire on its composition rather than on anything anyone did. A measured set moves up to `sets` when it is fully supported.

**Read the rows, not the average.** The base sets are near-identical reprint lists, so four of these rows are one data point wearing four hats — and the ALL row, deduped across reprints, is dominated by it. The independent comparison is between that block and the sets printed to a different brief.

## Registries

| Registry | Cards | Entries |
| --- | ---: | ---: |
| `CARD_LINE_INSTRUCTIONS` | 86 | 87 |
| `ON_LEAVE_BATTLEFIELD` | 6 | 6 |
| `DRAW_STEP_MODIFIERS` | 1 | 1 |
| `ENCHANTED_LAND_TAPPED_FOR_MANA` | 1 | 1 |
| `ON_SELF_RESOLVED` | 1 | 1 |
| `ON_SPELL_COUNTERED` | 1 | 1 |
| `UNTAPPED_ARTIFACT_PROTECTORS` | 1 | 1 |

## Cards carried by a name

- **Abu Ja'far** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Aladdin** (`ON_LEAVE_BATTLEFIELD`)
- **Aladdin's Lamp** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Animate Dead** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Armageddon Clock** (`CARD_LINE_INSTRUCTIONS`)
- **Balance** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Berserk** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Blaze of Glory** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Camouflage** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Channel** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Chaos Orb** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **City in a Bottle** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Consecrate Land** (`ON_LEAVE_BATTLEFIELD`)
- **Contract from Below** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Crumble** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Cursed Land** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Cyclone** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Cyclopean Tomb** (`CARD_LINE_INSTRUCTIONS`, `ON_LEAVE_BATTLEFIELD`) — 1 line
- **Darkpact** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Demonic Attorney** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Demonic Hordes** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Diamond Valley** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Dragon Whelp** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Drain Life** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Drain Power** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Drop of Honey** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Dwarven Weaponsmith** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Earthbind** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Ebony Horse** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **El-Hajjâj** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Erg Raiders** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Erhnam Djinn** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Eye for an Eye** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **False Orders** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Farmstead** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Forcefield** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Fork** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Gaea's Liege** (`CARD_LINE_INSTRUCTIONS`, `ON_LEAVE_BATTLEFIELD`) — 1 line
- **Ghazbán Ogre** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Guardian Angel** (`CARD_LINE_INSTRUCTIONS`, `ON_SELF_RESOLVED`) — 1 line
- **Guardian Beast** (`UNTAPPED_ARTIFACT_PROTECTORS`)
- **Hurkyl's Recall** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Illusionary Mask** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Island Sanctuary** (`DRAW_STEP_MODIFIERS`)
- **Ivory Tower** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Jade Monolith** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Jade Statue** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Jandor's Saddlebags** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Jeweled Bird** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Kudzu** (`ENCHANTED_LAND_TAPPED_FOR_MANA`)
- **Living Artifact** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Lord of the Pit** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Magnetic Mountain** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Mana Short** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Merchant Ship** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Metamorphosis** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Mijae Djinn** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Mishra's War Machine** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Nafs Asp** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Natural Selection** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Nether Shadow** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Nettling Imp** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Old Man of the Sea** (`CARD_LINE_INSTRUCTIONS`, `ON_LEAVE_BATTLEFIELD`) — 1 line
- **Oubliette** (`CARD_LINE_INSTRUCTIONS`, `ON_LEAVE_BATTLEFIELD`) — 1 line
- **Paralyze** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Personal Incarnation** (`CARD_LINE_INSTRUCTIONS`) — 2 lines
- **Pestilence** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Power Leak** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Power Sink** (`ON_SPELL_COUNTERED`)
- **Pyramids** (`CARD_LINE_INSTRUCTIONS`) — 2 lines
- **Raging River** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Reverse Damage** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Reverse Polarity** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Ring of Ma'rûf** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Rocket Launcher** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Rukh Egg** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Sacrifice** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Sandals of Abdallah** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Serendib Djinn** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Shahrazad** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Simulacrum** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Sindbad** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Siren's Call** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Stone Giant** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **The Rack** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Timetwister** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Twiddle** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Unstable Mutation** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Volcanic Eruption** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Wheel of Fortune** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Word of Command** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Ydwen Efreet** (`CARD_LINE_INSTRUCTIONS`) — 1 line
