# pack-v2-delta.json: changelog

Additions on top of chip-pack/1. Nothing existing is renamed or removed. Styles shipped: Classic (default), Toon, Button. Pupil sizes: S / M / L (default M).

## Top level

| Field | Meaning |
|---|---|
| `format` | `"chip-pack/2"`. |
| `rigAdd` | New rig layers in the existing rig format, plus `before` / `after` giving draw order. |
| `palette` | New colour roles only (`pupil`, `lid`). |
| `nightTint` | `l: 0.65` is the night lightness multiplier. `floor` lists colours (main, light, hi) that never drop below L 0.55. Without the floor, pupil contrast falls to 2.1:1 at night. |
| `sprites` | New art only. Names are `<layer>@<style>` (e.g. `eyeL@toon`). `{"mirror": "<sprite>"}` means: W is the longest source row; flip each row within W; anchor x becomes W − 1 − x. |
| `eyes` | Eye styles (below). |
| `lids` | Parametric lid profiles per side, so lidded frames are built from the `open` frame. Layout: `[top outer, top mid, top inner, bottom outer, bottom mid, bottom inner]` as fractions of the socket height, joined by a quadratic curve. |
| `fallbacks` | `eye` and `mouth` maps: frame → frame, applied repeatedly until a drawn frame is found. Every chain ends at a required frame (eye: open / half / shut; mouth: neutral). |
| `saccade` | Gaze-jump timing (below). |
| `skinSlots` | Maximum sizes in px: eye 40×48, pupil 24×24, front 40×48, mouth 28×14, faceBase 128×96, faceTop 128×26. |
| `skinGuide` | 52-line markdown guide for skin authors. |

## rigAdd

- `pupilL`, `frontL`: children of `eyeL`, draw order eye → pupil → front. Same for `pupilR`, `frontR` under `eyeR`.
- `faceBase`: parent head, drawn before `look`. Hidden unless a skin fills it.
- `faceTop`: parent head, drawn after `mouth`. Hidden unless a skin fills it.
- Front layers sit at `[0,0]` and share their eye sprite's anchor. The runtime sets each pupil's `at` on every saccade.

## palette

- `pupil`: near-black, slightly tinted by the accent (`from main, l .1, c .25, dh 0`).
- `lid`: black (`l 0, c 0, dh 0`). It is the colour of lid pieces in the front layer. A skin overrides it with its fur or skin colour.
- Note: this takes the palette from 20 to 22 colours. If 20 is a hard cap, `pupil` can reuse `bg`, and `lid` can be a per-skin value rather than a palette entry.

## sprites

- Back layers: `eyeL@<style>`, `eyeR@<style>` (mirror for Toon and Button). Classic keeps today's `eyeL` / `eyeR` as its back layer.
- `pupilL@<style>`: sizes S, M and L as frames centred in one shared box. The anchor is the box centre. `pupilR` points to the same sprite.
- `frontL@<style>`, `frontR@<style>`: key `x` marks lid pixels, drawn in `palette.lid`.
- Toon and Button store 12 back frames. Lidded looks come from the front layer, which adds a 2 px lid-coloured band outside the eye to cover the open eye's baked glow.

## eyes

- `default`: style used when none is chosen (`classic`).
- `styles.<id>`:
  - `label`, `blurb`: UI text.
  - `sprites`: sprite names for `eyeL`, `eyeR`, `pupilL`, `pupilR`, `frontL`, `frontR`.
  - `shift`: `[2,1]`. Whole-eye shift in rig px for frames that have a pupil (the pupil moves inside its box instead).
  - `converge`: `1`. Pupils move 1 px inward per eye when the target is near or the cursor is idle.
  - `pupils`: `["S","M","L"]`. `pupilDefault`: `"M"`.
  - `frames.<frame>`:
    - `pupil`: `"auto"` uses the user's size; `null` hides the pupil layer; or a specific pupil frame.
    - `box`: `[x0,y0,x1,y1]`, the pupil anchor position at gaze −1 and +1 for the left eye, in eye-sprite px. Each axis maps gaze −1…+1 linearly, rounded to whole px, so gaze 0 is the centre. The pupil layer's `at` is the box point minus the eye anchor. Add ±`converge` in x, inward, when near or idle. Valid for size L; S and M are centred inside the L box.
    - `boxR`: same for the right eye. New because the eyes differ in shape and lids.
    - `back`: back frame to show under this front frame (lidded frames use `open`).
    - `shift`: overrides the style shift. No-pupil frames (shut, happy, heart, heart2, star, star2, spiral, glitch) use `[5,3]`.
  - A missing front frame is drawn as nothing. A blink keeps the shift of the mood it interrupts.

## saccade

| Field | Value | Meaning |
|---|---|---|
| `frames` | 2 | Max redraws per move. |
| `oneFrameUpTo` | 8 | Jumps up to 8 px take 1 frame. |
| `secondFrameAt` | 0.67 | Larger jumps go this fraction of the way first, then land. |
| `overshoot` | 0 | No overshoot. |
| `hold` | 4 | Frames to hold after each move. |
| `deadband` | 3 | Moves under 3 px are ignored. |
| `maxRate` | 3 | Max gaze updates per second. |
| `idleToCentre` | 2.5 | Seconds idle before the pupils return to centre. |

## fallbacks

Eye: wide, small → open; lid30, drowsy, sleepy, bored, suspicious → half; focus, strain, angry, sad, worried, squint, think → open; happy → shut; heart, star, spiral, glitch → open; heart2 → heart; star2 → star.

Mouth: grin → happy → neutral; small, flat, o → neutral; asleep → small; hmm → flat; frown → flat; sad → frown; worried → sad; dizzy → frown; talkA → o; talkB → neutral; whistle → o; yawn → o.

## Self-check results

| Check | Result |
|---|---|
| All 24 eye frames resolve per style (directly or via fallbacks), and every frame used by moods, clips and states resolves | Pass |
| Fallback chains end at a required frame | Pass |
| Pupil pixels on black: 5,184 placements (every pupil frame, 9 gaze positions, S/M/L, both sides, converge on/off) | 0 failures |
| Blink (half, shut, half) | Looks right in all 3 styles (checked on a rendered contact sheet) |
| Pupil vs eye contrast, worst case over 24 hues × 3 chromas | L 0.62: 5.1:1 day, 3.8:1 night. L 0.9: 14.8:1 day, 4.5:1 night |
| Valid JSON | Pass. 150 KB total; Classic 31 KB, Toon 54 KB, Button 48 KB |

Caveats:
- Toon: iris vs sclera is 1.2:1 on near-white accents. The black pupil core still shows the gaze.
- Red accent under protanopia: 3.7:1 day, 2.6:1 night.
- Classic angry, looking up-right: the pupil is about 60% under the brow (within the ≥ 40% visible rule).
- Verified headless plus a rendered contact sheet only; not tested in a real browser or on the device.

## Engine note (merge, 2026-10-30)

`palette.lid` clashed with chip-pack/1's `lid` (the laptop lid on the desk), so the merge refused it. The eyelid
colour is now `eyelid` (palette entry and the `x` key of every front sprite). Read `lid` as `eyelid` above.
