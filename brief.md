Score 1–10 a MINI Hatch listing for a buyer with a specific spec wishlist.
Higher = better fit. Pipeline pre-filters already enforce: 3-door, automatic
gearbox, base Cooper (no S/SE/SD/JCW), petrol or unknown fuel.

# Hard dealbreakers — score MUST be 1 (defence-in-depth)

Even though pipeline filters catch these, mark 1 if you somehow see:
1. **5-door body** (`body_variant` says "5 Door" / "5-türer").
2. **Electric drivetrain** (`fuel` is "Electric" / "Elektro").
3. **Manual transmission** (`transmission` is "Manual" / "Manuell" / "Schaltgetriebe").
4. **Non-base Cooper** (`model` contains "Cooper S/SE/SD/JCW" or "John Cooper Works").

Convertible / Cabriolet listings ARE scored normally — they are not a
dealbreaker. Just apply the standard rules below; a Cooper Convertible with
no notable options sits at the baseline.

# Baseline = 4

Any in-spec listing that reaches you starts at **4**. This is the "bare 3-door
Cooper, automatic, gasoline, no notable wishlist features" anchor. It is
deliberately LOW — the buyer cares strongly about specific options, and a car
with none of them does not deserve a high score.

Do NOT penalise hard for missing items in the wishlist. Just don't add bonus.

# Bonuses (sum, then FLOOR to integer; cap at 10)

Read structured fields FIRST (`equipment_list`, `exterior_color`,
`interior_color`, `upholstery`). Fall back to `model_text` keywords
(`modelVersionInput`) if a field is "unknown".

The two **core** wishlist items (panoramic roof, leather upholstery) have
**field-vs-keyword tiered weights**: a confirmation in a structured field
is more trustworthy than a keyword in seller-written title text, so the
keyword-only weight is lower.

| Feature | Bonus | Source |
|---|---|---|
| **Panoramic roof — field-confirmed** (`Panoramadach` / `Panoramic glass roof` / `Panorama` / `PSD` literally in `equipment_list`) | **+2** | `equipment_list` |
| **Panoramic roof — keyword-only** (token in `model_text` but NOT in `equipment_list`) | **+1.5** | `model_text` |
| **Leather upholstery — field-confirmed** (`upholstery` is `Leather` / `Leder` / `Lederausstattung` / `Part leather` / `Teilleder`) | **+2** | `upholstery` |
| **Leather upholstery — keyword-only** (`Leder` token in `model_text`, `upholstery` is "unknown" or absent) | **+1.5** | `model_text` |
| **Light-blue strict exterior** (Hellblau / Island Blue / Iceberg Blue / Electric Blue / Light Blue / Light-Blue Metallic / LightBlueMetallic) | +1 | `exterior_color` |
| Other blue (`Blue` / `Blau` / `British Racing Blue` / `Midnight Blue`) | 0, mention in pros only | `exterior_color` |
| **Black interior** (`Schwarz` / `Black` / `Carbon Black` / `Lounge Carbon Black`) | +0.5 | `interior_color` |
| **Harman/Kardon audio** (`Harman/Kardon` / `Harman Kardon` / `HK` / `H/K`) | +0.5 | `equipment_list` or `model_text` |
| **Auto high beam / Matrix-LED / Adaptive headlights** (`Fernlichtassistent` / `Matrix-LED` / `Adaptive LED` / `Auto High Beam`) | +0.5 | `equipment_list` or `model_text` |
| **Heated seats** (`Sitzheizung` / `Heated seats` / `SHZ` in `equipment_list`) | 0; confirms baseline; mention in pros | |

Note: leather "field-confirmed" AND leather "keyword-only" are mutually
exclusive — if `upholstery` already says Leather, you take +2 and STOP. Same
for panoramic roof.

# SHZ unknown handling (softened)

If `equipment_list` is empty or doesn't list seat heating, do NOT subtract
points. Mention "seat heating unconfirmed" in `cons` and move on.

# Penalties

None. Missing wishlist items just don't add bonus. Do NOT subtract for
"cloth upholstery" / "no panoramic roof" / etc. — the low baseline already
reflects that.

# Round-and-cap rule — FLOOR ONLY

Sum the baseline plus all applicable bonuses. The final integer score is
**`math.floor(sum)`** — i.e. always **ROUND DOWN**. Never round up. Never
"round to nearest". Then cap at 10.

Examples:
- `4 + 2 + 2 = 8` → score **8**
- `4 + 1.5 + 1.5 = 7` → score **7**
- `4 + 2 + 0.5 = 6.5` → score **6** (FLOOR — NOT 7)
- `4 + 0.5 + 0.5 = 5` → score **5**
- `4 + 2 + 2 + 1 + 0.5 + 0.5 + 0.5 = 10.5` → score **10** (capped)

In your reasoning, **show the arithmetic explicitly** so the floor step is
auditable, e.g. "4 + 2 (pano field) + 0.5 (black int) = 6.5, floor → 6".

# Calibration anchor

Reference: `https://www.autoscout24.com/offers/mini-cooper-led-pdc-dab-gasoline-blue-fc5fdda6-add8-4dee-a4b1-98a390ffa50b`

This is a 3-door petrol Cooper, plain "blue" exterior (NOT light-blue),
LED + PDC + DAB. No leather, no panoramic roof, no Harman/Kardon, no Matrix-LED.

Math walkthrough:
- Baseline = 4
- Panoramic roof: NO → +0
- Leather: NO → +0
- Light-blue strict: NO (slug is "blue", not "Hellblau"/"Island Blue") → +0
- Other-blue family: NO numeric bonus, mention in pros → +0
- Black interior: unknown → +0
- Harman/Kardon: NO → +0
- Auto-high-beam / Matrix-LED: NO (plain LED is not Matrix) → +0
- SHZ unconfirmed → +0 (mention in cons only)

Sum = 4. Floor = **4**. Use this as your anchor for "bare in-spec — no
notable wishlist hits".

# Reasoning style

1–3 sentences IN RUSSIAN. CITE the substring you found (e.g. "found 'PSD' in
equipment_list", "'Black' in interior_color"). Show the arithmetic explicitly
so the floor step is visible. Pros / cons are short bullet phrases in Russian,
not full sentences. Quote German/English keywords verbatim.
