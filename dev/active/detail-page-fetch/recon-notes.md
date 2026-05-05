# Recon notes — captured 2026-05-05 06:37:13Z

URL: https://www.autoscout24.com/offers/mini-cooper-se-mini-cooper-se-navi-kamera-shz-1-hd-mtl-149-electric-black-14293eda-e181-4da6-9ea7-3c60f5f6b678

## Schema findings

For each enrichment field:
- **JSON path** (tuple of keys)
- **Shape enum** (`flat-list[str]`, `list[dict-with-items]`, `localized-html-blob`, `string`, `null`, `other`)
- **Excerpt** (pretty-printed JSON of that sub-tree)
- **Notes / gotchas**

### equipment
- JSON path: `("props", "pageProps", "listingDetails", "vehicle", "equipment")`
- Shape: dict (categories → list[dict-with-items])
- Excerpt:
  ```json
  {
    "comfortAndConvenience": [
      {
        "id": "Automatic climate control, 2 zones",
        "categoryName": "Comfort & Convenience",
        "categoryId": "comfortAndConvenience"
      },
      {
        "id": "Auxiliary heating",
        "categoryName": "Comfort & Convenience",
        "categoryId": "comfortAndConvenience"
      }
    ],
    "entertainmentAndMedia": [ ... ],
    "extras": [ ... ],
    "safetyAndSecurity": [ ... ]
  }
  ```
- Notes: The equipment value is a **dict keyed by category name** (e.g. `comfortAndConvenience`, `entertainmentAndMedia`, `extras`, `safetyAndSecurity`). Each value is a list of dicts with keys `id` (the feature label string), `categoryName`, and `categoryId`. To get a flat list of all equipment strings, iterate all category lists and collect `.id` values. This is NOT a flat-list[str] — downstream parser must flatten the dict-of-lists.

### exterior_color
- JSON path: `("props", "pageProps", "listingDetails", "vehicle", "bodyColor")`
- Shape: string
- Excerpt:
  ```json
  "Black"
  ```
- Notes: Primary color string field. Also available as `bodyColorRaw` (same value) and `bodyColorOriginal` (manufacturer name, e.g. `"Midnight black"`). Use `bodyColor` for the normalized display value; use `bodyColorOriginal` if the exact manufacturer name is needed.

### interior_color
- JSON path: `("props", "pageProps", "listingDetails", "vehicle", "upholsteryColor")`
- Shape: string
- Excerpt:
  ```json
  "Black"
  ```
- Notes: The field is NOT at `vehicle.interior` or `vehicle.interiorColor`. The correct path is `vehicle.upholsteryColor`. The companion field `vehicle.upholstery` contains the material type (e.g. `"Cloth"`). Both `upholsteryColor` and `upholstery` must be combined to fully describe the interior.

### upholstery
- JSON path: `("props", "pageProps", "listingDetails", "vehicle", "upholstery")`
- Shape: string
- Excerpt:
  ```json
  "Cloth"
  ```
- Notes: Material type string (e.g. `"Cloth"`, `"Leather"`, `"Alcantara"`). Combine with `upholsteryColor` from `vehicle.upholsteryColor` for a complete interior description.

## Open issues for downstream steps
- `equipment` is a **dict-of-category-lists** (not flat-list[str]): parser must iterate all category values and collect `item["id"]` strings to produce a flat equipment list. Category keys observed: `comfortAndConvenience`, `entertainmentAndMedia`, `extras`, `safetyAndSecurity`.
- `interior_color` maps to `vehicle.upholsteryColor` (NOT `vehicle.interior` or `vehicle.interiorColor`). The initial primary path `vehicle.interior` was null — the alternate-path resolution in the recon script found `upholsteryColor`.
- Fixture contains real listing data (dealer name, city/zip, possibly phone). Spot-checked: no API keys, bot tokens, or application secrets found in the captured HTML. PII is limited to normal AutoScout24 seller contact info which is intentional (realism preserved per task requirements).
- The captured listing is a MINI Cooper SE (electric), which may differ in equipment categories from a petrol Cooper. Re-run `scripts/recon_detail.py` if schema validation against a petrol variant is needed.
