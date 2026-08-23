# Memory-focused patches — queued for measurement-driven landing

Every candidate here is landing under a heaptrack profile (see
`06-heaptrack-9.0.8-version.md` for the recipe), not from a hunch.
Nothing lands as a patch until the profile shows the target
allocation site is worth the change.

## Landed so far

- **P57**: skip `wxTranslations::AddCatalog("kicad")` in headless
  mode. Heaptrack-driven. Removes ~30 000 allocation calls and
  ~1 MB peak heap on every kicad-cli invocation.

## Ready to draft, waiting for profile of the target scenario

### 1. `pcb export svg` on a 5 MB board — the plot-loop allocations

**Prediction from source read** (needs heaptrack against a real
5 MB board to validate):

- Every pad hits `pad->GetLayerSet() & aLayerMask` — LSET is a
  std::bitset<64>, the temporary allocation is small but numerous.
  On 5000 pads × 2 evaluations that's 10k temporaries.
  → *P54 already hoists this once per pad.* Measurement will
  confirm the savings.
- Every zone hits `zone->GetLayerSet().Seq()` — allocates a
  `std::vector<PCB_LAYER_ID>`.
  → *P56 already fixed this.*
- Every plotted text goes through `KIFONT::FONT::GetFont` which
  does a `std::map::find` + `[]` two-lookup pattern.
  → **queued P58**: single-iterator lookup in `GetFont`.
  Small win but tidy.

### 2. Board load — the parser and per-item allocation

- `PCB_IO_KICAD_SEXPR_PARSER::parse*` inserts new items one at a
  time. `BOARD::Add(item)` does `std::vector::push_back` on the
  right sub-collection. On a 5000-track board, 5000 push_backs =
  ~13 reallocations. Reserving up-front once we've seen the file
  size could win.
  → **queued P59**: precompute a first-pass tokenizer count of
  `(segment …)`, `(via …)`, `(footprint …)`, and reserve.

### 3. Footprint memory footprint (RAM)

Every `FOOTPRINT` on a 5000-footprint board holds:
- a `std::deque<PAD*>` — deque has ~500 B overhead per instance
- a `std::map<wxString, wxString>` for variant fields — sparse but
  present per FP
- multiple SHAPE_POLY_SET for courtyard, mask, paste

For repeated identical footprints (100 of the same LED0805), all
per-pad shapes could share a single SHAPE_POLY_SET via
`std::shared_ptr`. The current code already uses
`std::shared_ptr<SHAPE_POLY_SET>` for the *pad's* effective polygon,
so the mechanism exists — but the *template* footprint's
`shape_poly_set` isn't shared across pads that duplicate it.
- → **queued P60**: dedup pad `SHAPE_POLY_SET` across identical
  padstacks in the same library entry.
  **High RAM impact, complex ownership change.** Must land after
  the harness can measure peak RSS on a real board pre/post.

### 4. Zone triangulation cache

`SHAPE_POLY_SET::CacheTriangulation` produces a MEMBER
`m_triangulatedPolys` per polygon. On a copper-heavy 8-layer board
with many filled zones, this can easily hit tens of MB.

Zones being plotted go through
`zone->GetFilledPolysList(layer)->CloneDropTriangulation()` —
already drops the triangulation for the plot path. So plot doesn't
retain. Good.

For pcbnew's UI (GAL renderer), triangulation is cached and reused
across frames. That's correct.

**No obvious win here.** Left as "verified expected-behaviour" —
worth re-checking once the harness can measure UI memory
regressions across long-running pcbnew sessions.

### 5. String interning inside the s-expression parser

The parser materialises every layer/net token as a wxString.
Layer names ("F.Cu", "F.SilkS", …) repeat thousands of times.
wxString has ref-counting internally, so identical strings often
share buffers already — but *only* if constructed from the same
buffer. Building fresh wxString from raw parser bytes for each
occurrence does NOT share.

Interning through a `std::unordered_set<wxString>` inside the
parser session would collapse duplicates. Very high call count
site, small per-call win, medium-total.
→ **queued P61**: layer-name and net-name intern in
  `PCB_IO_KICAD_SEXPR_PARSER`.

### 6. wxLocale::Init temp allocs

The heaptrack profile shows `wxUILocale::InitLanguagesDB` doing
486 temp allocations just to look up the system locale — inside
wxWidgets, not kicad. Not fixable from our side. Filed as
external-known.

### Not worth pursuing

- `NOTIFICATIONS_MANAGER` ctor — one wxFileName. Cost is nil.
- `BACKGROUND_JOBS_MONITOR` ctor — empty body.
- `SETTINGS_MANAGER` ctor — thin; work happens later in
  `Load()`, which our headless path already trims.

## Landing order

Ordered by expected impact × risk:

1. **P58** (font single-lookup): tiny, safe, first
2. **P59** (parser reserve): needs benchmark on real board load;
   easy to validate
3. **P61** (parser string intern): higher call count site; medium
   engineering
4. **P60** (padstack shape dedup): highest RAM impact, biggest
   engineering change, lands last with full harness coverage

Each patch will carry a `Measured:` line in the commit message
showing pre/post from the harness — no more engineering-estimate
prose.
