# AT0 — Brand Guide

The single source of truth. Write **AT0** · say **"Auto."**
Pairs with `MESSAGING.md` (the words) and `/social` (profile assets).

---

## 1. Name

- **Written:** `AT0` — capital A, capital T, numeral zero. The `0` is the beacon ring — it *is* the logo.
- **Spoken:** "Auto."
- **First mention:** `AT0 ("Auto")`, then `AT0`.
- **Never:** `AT-0`, `ATO`, `At0`, `at0`.

---

## 2. Logo

**The mark** = a beacon: amber ring + glowing core + a teal node (the family signature). Animated, it adds a sonar ping and a rotating teal sweep.

**Variants (each provided as a set):**
| Variant | Use |
|---|---|
| color | default, on dark |
| animated (SVG) | web headers, hero, loading |
| mono | one-color contexts; white on dark, `#0A0B0D` on light |
| favicon | tabs, tiny sizes |
| app icon | home screen, app tiles (512²) |
| social | OG / share cards (1200×630) |

**Clear space:** keep padding ≥ the core-dot diameter on all sides.
**Minimum size:** 24 px (favicon), 32 px (UI). Below that, use the favicon variant.
**On light backgrounds:** use the mono (`#0A0B0D`) or the on-light color variant — never the glow version.

**Don'ts:** don't stretch or rotate · don't recolor the ring · don't add effects/shadows · don't box it on busy photos · don't replace the teal node with another color · don't render the wordmark with a hyphen.

---

## 3. Sub-product family

Every module = the **same ring + teal node**, with a **unique center glyph**:

| Module | Glyph | Role |
|---|---|---|
| AT0 | core dot | the beacon (parent) |
| Forge | anvil | build code |
| Smithy | hammer | ideas → specs |
| Crucible | extruder/vessel | 3D print / fabricate |
| Family | house | home / people |
| Financial | upward trend | wealth / markets |
| Medical | pulse | health / clinical |
| Spark | fingerprint | persona / voice |
| Herald | newspaper | manage + grow social presence |
| Warden | shield + chief band | overall security — manages the security sub-agents |
| Sweep | radar sweep + blip | network security — scans the perimeter / tailnet (replaces network_watchdog) |
| Porchlight | lantern | scheduled security posture sweeps, notify-only |
| Keyturner | key | owns approved key & password rotations |
| Tapwire | tapped wire + honey catch | honeypot monitor — classifies hits, alerts, feeds Warden's posture |

Tools get evocative one-word names (Forge, Smithy, Crucible, Spark). Life domains stay descriptive (Family, Financial, Medical).

---

## 4. Color

| Token | Hex | Use |
|---|---|---|
| Obsidian | `#0A0B0D` | primary background |
| Surface | `#15181F` | cards / panels |
| Line | `#262C38` | borders / dividers |
| Beacon Amber | `#F2B65A` | primary accent |
| Beacon Hot | `#FF8A3D` | gradient end / energy |
| Signal Teal | `#62D8C4` | accent only (the family node) |
| Warm White | `#F2EFE9` | primary text |
| Muted | `#8A8F99` | secondary text |

**Ratio:** ~70% obsidian · 18% warm white · 9% amber · 3% teal. Teal is a spark, never a field.

---

## 5. Typography

| Role | Font | Notes |
|---|---|---|
| Display / logo | **Chakra Petch** | geometric, technical |
| Body | **Hanken Grotesk** | clean, readable |
| Status / labels | **Space Mono** | monospace, uppercase, letter-spaced |

All three are free on Google Fonts.

| Element | Size |
|---|---|
| H1 | 32–52 px bold |
| H2 | 22–26 px semibold |
| Body | 16–19 px |
| Label/caption | 12–14 px, tracked, uppercase |

**Neurodiversity-first:** short sections, headings, bullets, generous line-height. Clarity is a feature.

---

## 6. Sound

A short **earcon** marks AT0 coming online + confirming actions (`/sound`). Warm, calm, never harsh — amber in audio form, with a small teal sparkle. Keep UI sounds under ~1.5s and optional/mutable.

---

## 7. Voice (summary — full kit in `MESSAGING.md`)

- **Tagline:** Your whole life, on Auto.
- **Pillars:** Private by design · Memory that never resets · Autonomy you control.
- **Tone:** calm, concrete, human, confident — never hype. Lead with the benefit. Say "planned" when it's planned.

---

## 8. Where things live

```
docs/brand/
  BRAND.md            ← this file
  MESSAGING.md        ← the words
  /                   ← logo wordmark + symbol sets
  sub-products/       ← Forge, Smithy, Crucible, Family, Financial, Medical, Spark
  social/             ← avatars + banners
  sound/              ← earcon
```
