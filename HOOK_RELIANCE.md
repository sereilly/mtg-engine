# Hook Reliance

How much of the card pool is supported by having its **name** written down — `engine/card_hooks.py`, the one sanctioned place to key behaviour on a card name — rather than by having its text read.

Every individual entry there is defensible and guarded; this is the measure of the pile. A name-keyed entry costs one hand-written rule and buys one card. A grammar production costs one and buys every card printed with that template. So this fraction is the engine's marginal cost per card, and it is the number that decides whether the architecture reaches the full release line.

**Generated** — run `python scripts/hook_reliance.py` to refresh.

The measures are **ceilings**, the opposite direction to `GRAMMAR_COVERAGE.md`'s floors and for the same reason: there the hazard is the general reader losing ground, here it is the special-case readers gaining it.

**Every percentage below is over *supported* cards**, and the measure names say so. A card the engine cannot play is not a card a hook is carrying, so counting it would mean that ingesting a set supported at 30% inflates the denominator, leaves the numerator behind, and reports *falling* reliance — a ceiling passing because the pool got harder. Support rate is reported beside the measures as pool reach, which is a real number and a different question.

## The headline

**62 of 1725 supported cards (3.6%)** carry at least one name-keyed entry, across **68 entries** in 6 registries. The pool is 1725 cards, 100.0% supported.

Held at this rate, supporting the 26,113-card release line would need about **1,029 hand-written entries** covering **939 cards**. That projection is the point of the number, not a forecast: it is the cost of assuming the current sample is representative, and the sample is five sets from 1993–94.

## By set

| Set | Cards | Supported | Hooked cards | Rules lines | Hooked lines | Entries | Entries/100 supported |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| LEA | 290 | 290 (100.0%) | 35 (12.1%) | 388 | 33 (8.5%) | 39 | 13.4 |
| LEB | 292 | 292 (100.0%) | 35 (12.0%) | 389 | 33 (8.5%) | 39 | 13.4 |
| 2ED | 292 | 292 (100.0%) | 35 (12.0%) | 389 | 33 (8.5%) | 39 | 13.4 |
| ARN | 78 | 78 (100.0%) | 21 (26.9%) | 107 | 19 (17.8%) | 23 | 29.5 |
| ATQ | 85 | 85 (100.0%) | 3 (3.5%) | 120 | 3 (2.5%) | 3 | 3.5 |
| 3ED | 296 | 296 (100.0%) | 29 (9.8%) | 389 | 28 (7.2%) | 32 | 10.8 |
| LEG | 310 | 310 (100.0%) | 2 (0.6%) | 430 | 2 (0.5%) | 2 | 0.6 |
| DRK | 119 | 119 (100.0%) | 1 (0.8%) | 167 | 1 (0.6%) | 1 | 0.8 |
| FEM | 102 | 102 (100.0%) | 0 (0.0%) | 190 | 0 (0.0%) | 0 | 0.0 |
| 4ED | 368 | 368 (100.0%) | 21 (5.7%) | 520 | 20 (3.8%) | 23 | 6.2 |
| ICE | 373 | 373 (100.0%) | 1 (0.3%) | 601 | 0 (0.0%) | 1 | 0.3 |
| HML | 115 | 115 (100.0%) | 0 (0.0%) | 190 | 0 (0.0%) | 0 | 0.0 |
| 5ED | 434 | 434 (100.0%) | 12 (2.8%) | 631 | 11 (1.7%) | 13 | 3.0 |
| M21 | 285 | 285 (100.0%) | 0 (0.0%) | 503 | 0 (0.0%) | 0 | 0.0 |
| ALL *(measured)* | 144 | 97 (67.4%) | 0 (0.0%) | 175 | 0 (0.0%) | 0 | 0.0 |
| **Whole pool (shipped, deduped)** | **1725** | **1725 (100.0%)** | **62 (3.6%)** | **2670** | **58 (2.2%)** | **68** | **3.9** |

*(measured)* — ALL are ingested for measurement and **not shipped**: `cards/manifest.json` lists them under `measured`, the engine's catalog does not load them, and no player can put one in a deck. They are reported here and excluded from the ALL row and from the ceilings, because a ratchet over a set nobody has implemented would fire on its composition rather than on anything anyone did. A measured set moves up to `sets` when it is fully supported.

**Read the rows, not the average.** The base sets are near-identical reprint lists, so five of these rows (LEA, LEB, 2ED, 3ED, 4ED) are one data point wearing five hats — and the ALL row, deduped across reprints, is dominated by it. The independent comparison is between that block and the sets printed to a different brief.

## Registries

| Registry | Cards | Entries |
| --- | ---: | ---: |
| `CARD_LINE_INSTRUCTIONS` | 57 | 58 |
| `ON_LEAVE_BATTLEFIELD` | 6 | 6 |
| `DRAW_STEP_MODIFIERS` | 1 | 1 |
| `ON_SELF_RESOLVED` | 1 | 1 |
| `ON_SPELL_COUNTERED` | 1 | 1 |
| `UNTAPPED_ARTIFACT_PROTECTORS` | 1 | 1 |

## Cards carried by a name

- **Aladdin** (`ON_LEAVE_BATTLEFIELD`)
- **Aladdin's Lamp** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Balance** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Berserk** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Blaze of Glory** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Camouflage** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Channel** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Chaos Orb** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **City in a Bottle** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Consecrate Land** (`ON_LEAVE_BATTLEFIELD`)
- **Cyclone** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Cyclopean Tomb** (`CARD_LINE_INSTRUCTIONS`, `ON_LEAVE_BATTLEFIELD`) — 1 line
- **Darkpact** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Demonic Hordes** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Drain Power** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Drop of Honey** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Earthbind** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Erg Raiders** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Eye for an Eye** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Falling Star** (`CARD_LINE_INSTRUCTIONS`) — 1 line
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
- **Jeweled Bird** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Kudzu** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Mana Short** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Metamorphosis** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Mijae Djinn** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Nafs Asp** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Nether Shadow** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Old Man of the Sea** (`CARD_LINE_INSTRUCTIONS`, `ON_LEAVE_BATTLEFIELD`) — 1 line
- **Oubliette** (`CARD_LINE_INSTRUCTIONS`, `ON_LEAVE_BATTLEFIELD`) — 1 line
- **Personal Incarnation** (`CARD_LINE_INSTRUCTIONS`) — 2 lines
- **Power Sink** (`ON_SPELL_COUNTERED`)
- **Pyramids** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Raging River** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Reverse Damage** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Reverse Polarity** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Ring of Ma'rûf** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Rohgahh of Kher Keep** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Serendib Djinn** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Shahrazad** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Simulacrum** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Sindbad** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Siren's Call** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Sorrow's Path** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Stone Giant** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Timetwister** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Wheel of Fortune** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Word of Command** (`CARD_LINE_INSTRUCTIONS`) — 1 line
- **Ydwen Efreet** (`CARD_LINE_INSTRUCTIONS`) — 1 line
