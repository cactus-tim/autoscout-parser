Score 1–10 a MINI Hatch listing for a buyer with a very specific spec wishlist.
Higher = better fit.

# Hard dealbreakers — score MUST be 1

Penalise to 1 (and put each in `cons`) if ANY of these are true:

1. **5-door body**. The buyer wants only the 3-door hatch.
   - Source: the `body_variant` field. `"5 Door"` or `"5-türer"` → dealbreaker.
2. **Electric drivetrain**. The buyer does not want a BEV (e.g. Cooper SE).
   - Source: the `fuel` field. `"Electric"` / `"Elektro"` → dealbreaker.
3. **No seat heating**. The buyer requires heated front seats.
   - Source: look in `model_text` for the German abbreviation `SHZ`
     (Sitzheizung) or English `seat heating` / `heated seats`.
   - If the field is present but says nothing about heating, treat seat heating
     as **unknown** rather than absent. Do not auto-dealbreaker on missing data;
     instead drop the score by 2 and note in `cons` that it is unconfirmed.

# Ideal-spec bonuses (each present → +1, capped at score 10)

Look for these signals in `model_text` (German listings often abbreviate):

- **Leather seats** — `Leder`, `Leather`, `Lederausstattung`, `LED-Leder`
- **Panoramic roof** — `Pano`, `Panorama`, `Panoramadach`, `PSD` (Panorama-Schiebedach)
- **Light blue exterior** — `Island Blue`, `Electric Blue`, `Iceberg Blue`,
  `Hellblau`, `Light Blue`, `British Racing Blue` is dark blue, not light blue.
- **Black interior** — `Schwarz`, `Black`, `Carbon Black`, `Lounge Carbon Black`
  (the buyer wants a black cabin specifically; light/beige interiors are
  worse fit, not dealbreakers).
- **Harman/Kardon audio** — `Harman/Kardon`, `Harman Kardon`, `HK`, `H/K`
- **Auto high beam / adaptive headlights** — `Fernlichtassistent`, `Auto High
  Beam`, `Matrix-LED`, `Adaptive LED`

# Scoring guidance

- Start from a baseline of 5 for an in-spec 3-door petrol Cooper with seat
  heating and nothing else known.
- Add +1 per confirmed ideal feature above (cap at 10).
- Subtract 1 for each "unknown" critical feature (seat heating only).
- Apply hard dealbreakers as the FIRST check before any bonuses.
- Reasoning: 1–3 sentences. Be concrete: cite the exact substring you found
  (e.g. "found 'SHZ Pano HK' in model_text") so the buyer can verify.
- Pros / cons must be short bullet phrases, no full sentences.

# Examples

- 3-door petrol Cooper, `model_text` says `"SHZ Pano HK Leder"`, no colour info
  → score 8 (5 baseline + SHZ confirmed + Pano + HK + Leder, exterior/interior
  colour unknown).
- 5-door Cooper S, fully loaded → score 1 (5-door dealbreaker).
- 3-door Cooper SE Electric → score 1 (electric dealbreaker).
- 3-door petrol Cooper, `model_text` empty → score 3 (5 baseline − 2 for
  unconfirmed seat heating).
