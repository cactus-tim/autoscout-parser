Score 1–10 a MINI Hatch listing for a buyer with a specific spec wishlist.
Higher = better fit. Pipeline pre-filters already enforce: 3-door, automatic
gearbox, base Cooper (no S/SE/SD/JCW), petrol or unknown fuel. So most "expected
basics" are already met by anything that reaches the LLM.

# Hard dealbreakers — score MUST be 1 (defence-in-depth)

Even though pipeline filters catch these, mark 1 if you somehow see:
1. **5-door body** (`body_variant` says "5 Door" / "5-türer").
2. **Electric drivetrain** (`fuel` is "Electric" / "Elektro").
3. **Manual transmission** (`transmission` is "Manual" / "Manuell" / "Schaltgetriebe").
4. **Non-base Cooper** (`model` contains "Cooper S/SE/SD/JCW" or "John Cooper Works").

# Baseline = 6

Any in-spec listing that reaches you starts at **6**. This already accounts for
the basic comfort/electronics package (LED, PDC, DAB, Navi) being either
present or implied.

Do NOT penalise hard for missing items in the wishlist. The buyer's ideal is
aspirational; "merely good in-spec" is still a 6.

# Bonuses (each adds points; round to int at end; cap 10)

Read structured fields FIRST (`equipment_list`, `exterior_color`,
`interior_color`, `upholstery`). Fall back to `model_text` keywords
(`modelVersionInput`) if a field is "unknown".

| Feature | Bonus | Source |
|---|---|---|
| **Light-blue strict exterior** (Hellblau / Island Blue / Iceberg Blue / Electric Blue / Light Blue / Light-Blue Metallic / LightBlueMetallic) | +1 | `exterior_color` |
| Other blue (`Blue` / `Blau` / `British Racing Blue` / `Midnight Blue`) | 0, mention in pros only | `exterior_color` |
| **Black interior** (`Schwarz` / `Black` / `Carbon Black` / `Lounge Carbon Black`) | +0.5 | `interior_color` |
| **Leather upholstery** (`Leder` / `Leather` / `Lederausstattung` / `Teilleder`) | +1 | `upholstery` (preferred) or `equipment_list` |
| **Panoramic roof** (`Panoramadach` / `Panorama` / `Pano` / `PSD`) | +1 | `equipment_list` (preferred) or `model_text` |
| **Harman/Kardon audio** (`Harman/Kardon` / `Harman Kardon` / `HK` / `H/K`) | +0.5 | `equipment_list` or `model_text` |
| **Auto high beam / Matrix-LED / Adaptive headlights** (`Fernlichtassistent` / `Matrix-LED` / `Adaptive LED` / `Auto High Beam`) | +0.5 | `equipment_list` or `model_text` |
| **Heated seats** (`Sitzheizung` / `Heated seats` / `SHZ` in `equipment_list`) | confirms baseline; no extra bonus, mention in pros |  |

# SHZ unknown handling (softened)

If `equipment_list` is empty or doesn't list seat heating, do NOT subtract
points. Mention "seat heating unconfirmed" in `cons` and move on. Most listings
are sloppy about listing every option.

# Round-and-cap rule

Sum bonuses, add to baseline, ROUND to nearest int, CAP at 10.

# Calibration anchor

Reference: `https://www.autoscout24.com/offers/mini-cooper-led-pdc-dab-gasoline-blue-fc5fdda6-add8-4dee-a4b1-98a390ffa50b`

This is a 3-door petrol Cooper, plain "blue" exterior (NOT light-blue),
LED + PDC + DAB. No leather, no panoramic roof, no Harman/Kardon, no Matrix-LED.

Math walkthrough:
- Baseline = 6
- Light-blue strict: NO (slug is "blue", not "Hellblau"/"Island Blue") → +0
- Other-blue family: NO numeric bonus, mention in pros → +0
- Leather: NO → 0
- Pano: NO → 0
- Black interior: unknown → 0
- Harman/Kardon: NO → 0
- Auto-high-beam / Matrix-LED: NO (plain LED is not Matrix) → 0
- SHZ unconfirmed → no penalty (mention in cons only)

**Final: 6.** Use this as your anchor for "merely good in-spec".

# Reasoning style

1–3 sentences. CITE the substring you found (e.g. "found 'PSD' in equipment_list,
'Black' in interior_color"). Pros / cons are short bullet phrases, not full
sentences.
