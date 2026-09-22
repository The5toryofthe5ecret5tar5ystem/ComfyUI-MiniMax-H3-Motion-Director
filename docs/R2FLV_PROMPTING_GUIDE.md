# Ref2va + FL2v Hybrid (r2flv) - Prompting Guide

Audience: humans writing prompts for a `r2flv` Motion Director project, and AI writers
asked to author one. Everything here describes the engine as it behaves today: the
reference pass (Ref2va), the boundary anchors, and the first/last keyframe pinning
(FL2v) that turns the anchors into the visual endpoints of every shot.

Companion files:
- `docs/PROMPT_WRITING_GUIDE.md` - the r2v / ref2va segment template and reference slot
  map. That vocabulary still applies; this guide adds the r2flv specifics and the rules
  for the PROJECT prompt that r2flv makes load-bearing.
- `docs/USER_GUIDE.md` - what each UI control does.

---

## 1. How r2flv works (what your text actually feeds)

### 1.1 Two render passes, one keyframe bridge

An r2flv project renders in two passes:

1. **Boundary anchors.** For N shots there are N+1 boundaries: the opening pose, every
   cut, and the closing pose. Each boundary is rendered once as its own 22-frame piece
   (default "anchor length") from a prompt the engine COMPOSES (section 1.3). Anchors
   are the pose references of the project - one picture per boundary.
2. **Fills.** Each shot is rendered as a normal Ref2va segment - reference pictures
   steer identity, its own group prompt carries the action - with a difference: the
   shot's FIRST frame is pinned with the anchor of the boundary it starts at, and its
   LAST frame with the anchor of the boundary it ends at. The sampler interpolates
   between the two approved poses; the references keep steering who is on screen.

Consequences for prompt writing:

- A shot's visual endpoints are **decided by the boundary texts**, not by the shot
  prompt alone. If shot 7 ends with text that contradicts boundary 8's beat, the render
  fights itself and the cut looks wrong.
- Anchors are rendered from a **composition** (below) whose dominant block is the
  PROJECT prompt. This is why the project prompt rules in section 2 are strict.

### 1.2 The three text layers

| Layer | Lives in | Feeds | Owns |
|---|---|---|---|
| **Project prompt** (the "global") | `timeline.global.prompt`; the "Project prompt..." button in the Boundary anchors bar | the shared block of EVERY anchor render; stands in for any group whose own prompt is empty | identity, cast-appearance, world/room, style, camera philosophy, audio policy, motion rules - facts true in EVERY shot |
| **Group prompt** (per shot) | each group card's PROMPT box | that shot's fill | what happens in THIS shot: opening state, action, ending pose, camera moves, cues, dialogue |
| **Boundary beat** | each boundary cell in the strip (editable) | that boundary's anchor render | the single instant the cut holds - who is in frame, where, doing what |

A fill does NOT concatenate the project prompt. It uses its own group text. The project
prompt only substitutes when a group prompt is empty. The project prompt's true consumer
is the anchor pass - and it is the single most powerful lever on every anchor image.

### 1.3 How an anchor prompt is composed (the exact recipe)

For boundary k the engine builds one prompt from five ingredients:

```text
<shared>            the PROJECT prompt, verbatim  (the dominant block)
<subject>           the owner group's subject_definitions (skipped if already inside shared)
<beat>              boundary k's beat, or the default "holds a calm, natural pose,
                    looking toward the camera" when the cell is empty
<from_tail>         the LAST 2 action sentences of the shot that ENDS on this boundary
<to_head>           the FIRST 2 action sentences of the shot that STARTS on it
<camera>            the camera sentence of the shot that ENDS here (its LAST camera
                    sentence, kept to its final 160 characters); if that shot has
                    none, the FIRST camera sentence of the shot that STARTS here
                    (kept to its first 160 characters)
```

Rules the composition imposes:

- **First and last sentences are load-bearing.** They get borrowed by the neighbouring
  boundary anchors. Write them as poses ("End with...", "Begin with..."), not as
  transitions or plot.
- The tail/head borrow is clamped to about 240 characters, the camera clause to about
  160. Two short sentences survive intact; one long paragraph gets cut.
- A sentence is treated as a camera line only when it **opens like framing** - "The
  camera...", "Wide shot...", "Close-up...", "The final shot...", "Static frame...".
  A pose sentence that merely mentions "camera" is treated as a pose (this is
  intentional; write camera lines as their own sentences that start with framing words).
- **Camera sentences are read from `detailed_description` first.** When that section
  carries a camera sentence it always wins, so write the framing at the hand-off as
  the description's closing sentence: the next boundary anchors borrow the END of it,
  and the fill reads it too. A `Camera:` line in the prompt head (before `summary:`)
  now works as a fallback when the description has none - but it is the weaker
  placement (any camera sentence inside the description beats it).
- The opening boundary (cell 1) has no shot ending on it (empty `from_tail`); the
  closing boundary (cell N+1) has no shot starting on it (empty `to_head`). Give those
  two cells full beats.
- Anchors render with the project's references and the connected RefMod conditioning, so
  the reference-covered characters keep their identity inside the anchor renders too.

### 1.4 The composed anchor block looks like this

```text
<shared project text>

<beat> ... (the summary line reads "The closing beat of this shot: <beat>")

detailed_description:
Live-action, the same location and lighting as the surrounding shots.
<from_tail / to_head/ camera assembled here>
Audio: <the neighbours' audio line, or calm room tone>.
```

You do not write this by hand. You write the three layers; the engine assembles the
block. Write with that assembly in mind.

### 1.5 Operational notes that affect iteration

- **Anchors are cached per seed.** Editing prompts or beats does NOT invalidate an
  existing anchor PNG. To redraw a boundary you must reroll it (the ↻ button) - that
  deletes the boundary's images and picks a new seed - then render.
- The strip's "rendered" state can show an image rendered from older text. When in
  doubt, reroll the boundary before judging a prompt change.
- Empty beats are the most common cause of "generic" anchors: the default beat is a
  neutral standing pose.
- Placement "1s before the cut" (lead) means the anchor pose is the shot's state about
  one second before its end; keep the corresponding sentences near the end of the shot
  text so they describe that exact moment.

---

## 2. The project prompt - the shared block

Everything in this section is the core of r2flv prompt authorship. The project prompt is
prepended to every anchor render, so each sentence must be TRUE FOR EVERY SHOT of the
project.

### 2.1 The invariant rule

The project prompt may contain only **cast, world, style and rules** - facts that do not
change from shot to shot. Anything that changes (positions, poses, who is present, what
just happened, camera moves, props that appear once) belongs to the shot text or the
beats.

Ask of every sentence: "is this true in shot 1 AND shot N?" If not, it goes elsewhere.

### 2.2 Cast - characters covered by reference pictures

For every character or object that has reference pictures attached (Common References
or a group's own slots / the connected RefMod):

- Give a SHORT identity line with the `<Subject N>` label the group texts will reuse.
- Bind the visual adherence explicitly to the references: name the picture slots and
  what each one is the source of - face, body, wardrobe, props.
- Tell the model what NOT to copy from a reference (pose, framing, background) so a
  portrait's expression or a sheet's grid never leaks into renders.
- Still describe the character's wardrobe in words when the outfit matters to the
  action (so a shot can talk about the bow, the dagger, the boots), but keep it to the
  invariant items.

Example (reference-covered):

```text
<Subject 1> is a lithe, graceful elf woman in her early twenties with elegant pointed
ears and silver-blonde hair braided back. Follow the attached reference pictures for her
face, body and wardrobe: light, fitted leather-and-cloth armor in forest greens and
browns, a slim hunting bow and a quiver of arrows, a single silver dagger at her hip.
Never copy a reference's pose, framing or background - identity and wardrobe only.
```

### 2.3 Cast - characters NOT covered by reference pictures

This is the failure-prone half of r2flv, and the reason this section is long. If a
character appears in any shot but has NO reference image, the model has nothing to
anchor to. The project prompt is the ONLY place its look can live, and the shot texts
can only refer to it by name. Under-specified characters drift in size, colour and
wardrobe between boundaries.

Describe every non-reference character with this checklist. Omit a line only when it is
truly irrelevant:

1. **Nature / species**: "a colossal ogre", "a mounted knight", "a flock of crows".
2. **Exact scale with a human-readable comparison**: "two hundred feet tall - twenty
   stories - a head longer than the elf's whole body". Scale drift is the #1 killer;
   give a number AND an analogy.
3. **Build and posture**: muscle, bulk, hunch, how the mass sits (sloping shoulders,
   heavy gut, long arms).
4. **Skin / hide / surface**: material, colour, texture, sheen, imperfections.
5. **Face**: head shape and relative size, brow, eyes (size, colour, spacing), nose or
   snout, mouth and teeth (tusks, jutting jaw), ears, any covering (mane, horns, helm).
6. **Hair / mane / covering**: colour and behaviour (braided, matted, flowing).
7. **Clothing and gear, layer by layer**: from the base layer out (loincloth, belt with
   pouches and straps, collar), naming materials, colours and condition (ragged, studded,
   polished).
8. **Signature props**: what identifies it in silhouette from a distance.
9. **Voice and sound (H3 generates audio!)**: a deep booming roar, rattling chains,
   heavy footfall - describe what it sounds like so the audio pass can render it.
10. **Movement vocabulary**: how it moves at this scale - trees bending, ground tremors,
    water displacement. One or two clauses, invariant across shots.

Then add the **presence rule**, in some form:

```text
How near he is, what pose he holds, and whether he is present at all are set by each
shot's own description; never add him to a shot that does not name him. When both share
the frame, keep the enormous scale gap between the tiny elf and the giant readable.
```

This rule was learned the hard way. A project prompt that says "keep both characters
readable in every shot" orders the giant into close-ups of an empty room. A project
prompt that says "whether he stands, falls or lies dead" hands every anchor render a
menu of story states - including states that belong only to the last shot. Neither
sentence may appear. Presence, pose and condition are per-shot facts.

### 2.4 The world / location block

The world block is what keeps every render in the SAME place: the same room, the same
valley, the same lighting. Write it as a standing set, not as a scene description.

Checklist for the world block:

1. **Type and geography**: interior room in a house / canopy of a jungle / riverside bank.
   State the spatial relationships that recur ("the river cuts through the forest floor
   below the canopy"; "the door at the far end of the hall").
2. **Ground and surfaces**: floor material, mud, boards, carpet, water - and what the
   surfaces do under weight or light.
3. **Architecture and landmarks**: walls, windows, tree house, cliff line, bridge -
   anything a shot may later rely on for orientation.
4. **Furniture / props that are ALWAYS there**: bed, shelf, hammock, workbench. Only
   items present in every shot belong here; a chair used in one shot is a per-shot prop.
5. **Lighting**: time of day, direction and quality of light, colour temperature, what it
   does through openings (shafts through mist, window glow, candle flicker that is
   invariant).
6. **Atmosphere**: mist, dust, smoke, humidity, how much air is "visible".
7. **Colour palette**: the two or three dominant tones the grading should stay inside.
8. **Ambience (audio)**: the invariant bed - distant jungle, river rush, room tone. Per-
   shot sounds stay per-shot.
9. **Scope line**: one sentence that makes the world a menu, not a checklist:

```text
The river and the tree house are landmarks of this valley - a shot frames only what its
own description names.
```

What must NEVER be in the world block: story events, states ("half-submerged", "ablaze"),
positions of characters, one-shot props, camera moves, and any "every shot" absolutism
that is not literally true.

### 2.5 Style, camera, audio, motion - the four rule lines

- **Style**: realism level, film language, lens behaviour, texture fidelity, grading.
  Example: "cinematic live-action realism, epic fantasy scale, humid morning jungle light
  with shafts of golden sun through drifting mist and pollen, photoreal textures, shallow
  depth of field on close shots and sweeping deep focus on the scale shots."
- **Camera**: the invariant framing philosophy only, with scale rules conditioned on
  co-presence: "cinematic framing; when the elf and the ogre share a frame, keep both at
  their readable relative scale." Never a specific move; moves belong to shots.
- **Audio**: the policy, not the cues: whether dialogue exists at all ("never any
  dialogue"), how cues are named ("sound is named by each shot's own cues"), and the
  music rule ("non-diegetic music only where a shot's Music cue names it"). H3 generates
  audio from text, so this line is a real control: state the policy once, keep cues in
  the shots.
- **Motion rule**: the physical tone of the whole piece: "everything stays physically
  alive and grounded - no stiff posed stillness." One sentence; it applies everywhere and
  fixes the "posing like a statue" failure of long shots.

### 2.6 Forbidden in the project prompt (and why)

| Never write | Why it breaks |
|---|---|
| Story states: "dead", "wounded", "fallen", "standing", "burning" | Every anchor render receives it; early boundaries get pushed into late-story states |
| "in every shot" for anything conditional | Forces the element into frames that must not contain it |
| One-shot props or positions ("the dagger in the river") | Appears in every anchor - the prop teleports through the whole film |
| Per-shot camera moves | The anchor camera clause is borrowed from the shots; the global competes with them |
| Arc spoilers ("by the end the ogre is dead") | Leaks into shot 1 anchors |
| Dialogue lines, quoted phrases | H3's audio pass may voice them; keep speech inside shot-level `<d>` blocks only |
| Negative phrasing ("no...", "never a...") as the main voice | H3 is CFG-distilled and has no negative prompt; phrase positively where possible (the few policy lines like "never any dialogue" are the exception) |
| Em/en dashes | Stick to plain hyphens everywhere in prompt text |

Case study - the ogre that appeared in shot 1's anchor. The project prompt contained:

```text
Whether he stands, falls or lies dead, keep the enormous scale gap between the tiny elf
and the giant readable in every shot.
Camera: cinematic framing that keeps both the elf and the ogre's scale readable in every shot.
```

Every anchor - including the hammock wake-up, whose shot text says the ogre is never
visible - was told to keep him readable in frame, in any state, next to a river.
Unsurprisingly the renders produced a giant (sometimes "fallen") in early shots. The fix
was structural, not cosmetic: presence/pose/condition moved to the shots and beats; the
project prompt keeps only identity and a conditional scale rule ("when both share the
frame").

### 2.7 Project prompt template (fill every angle bracket)

```text
Setting and cast for an <N>-shot cinematic sequence in <world in one phrase>: <cast list,
each entry one noun phrase>. <One global policy sentence: dialogue or not.>

world:
<Set description per 2.4: geography, surfaces, landmarks, lighting, atmosphere, palette.>
<One scope sentence: landmarks exist; each shot frames only what it names.>
<Subject lines per 2.2 and 2.3 - identity, references to follow, wardrobe, scale analogies.>
<Presence rule per 2.3.>
Style: <grading, realism, lens behaviour.>
Camera: <invariant framing philosophy; conditional co-presence scale rule.>
Audio: <dialogue policy; cue policy; music policy.>
Motion rule: <physical tone sentence.>
```

---

## 3. Group prompts (the shots)

### 3.1 Sentence order: opening state, action, ending pose

Each group prompt is prose read top to bottom by the model, and its first and last
sentences are borrowed by neighbouring boundary anchors. Write in this order:

1. **Opening state** - where everything stands as the shot begins (one sentence).
2. **Action beats** - what happens, in order, each beat a short sentence with at most
   one subject each.
3. **Camera sentences** - their own sentences inside the description, opening with
   framing words (3.2).
4. **Ending pose** - the exact frame the boundary must hold: "End with <pose>."
5. **Cues** - sound and music named at the beat they occur.

Only characters actually on screen may be named. Do not carry the state of the whole
story in a shot text: describe the shot's own start state explicitly ("still wearing her
armour", "the ogre already down and half-submerged") - state carries forward by
statement, never by assumption.

### 3.2 Camera lines that actually register

Two rules decide whether a camera sentence reaches the boundary anchors: where it sits,
and how it opens.

**Where.** The composer reads `detailed_description` first. When that section carries a
camera sentence, only those count - a `Camera:` head line (before `summary:`) is never
considered then, so the safest place for the hand-off framing is the description
itself, best as one closing sentence: the boundary after this shot borrows the END of
the shot's LAST camera sentence, and the boundary before it falls back on the START of
the FIRST. If the description has no camera sentence at all, the whole prompt is
searched as a fallback - a head `Camera:` line then still reaches the anchors.

**How.** A sentence is read as the camera clause only when it OPENS like framing. Write
camera sentences as their own sentences:

- Good: "The camera starts close on her face and pulls back as the room sways."
- Good: "Wide shot: the whole canopy, the elf a speck on the branch."
- Ignored as camera (borrowed as pose instead): "She runs while the camera shakes."

### 3.3 Audio and music cues

H3 generates the soundtrack from your text. In each shot, name the cues where they
happen: "the wooden floor creaks under her feet", "a low rumble rolls through the
trunks". Music policy lives in the project prompt; the cue itself lives in the shot
("Music: driving adventure-orchestra starts as she breaks the canopy line"). Dialogue is
written only as explicit tagged lines around the words; if the project is silent, say so
in the project prompt once.

### 3.4 Write first/last sentences as poses

Because of the borrow rule (1.3), the neighbour's anchor will literally contain your
first two and last two sentences. Consequences:

- The LAST sentence of shot k should read as the pose boundary k+1 holds, e.g. "End with
  her crouched at the door, bow in hand, the floor still trembling."
- The FIRST sentence of shot k+1 should read as the state the same boundary opens with,
  e.g. "She bursts out onto the branch platform, already sprinting."
- Keep both short. The 240-character clamp means two clauses of 25 to 30 words survive;
  a 90-word paragraph does not.

### 3.5 Scoping early shots (leakproof rule)

Give early shots explicit scope when the story has a big reveal later: "Far off beyond
the trees something deep and heavy is moving. It is never visible in this shot - only its
low rumble reaches the tree house." Scope lines beat global disclaimers: they are local,
specific and cannot leak into other renders.

---

## 4. Boundary beats

A beat is the one instant the cut holds (or, with "1s before the cut", the instant about
a second before it). It is rendered alone, as a still, from the shared block plus the
neighbours' borrowed sentences.

Write a beat as: **who is in frame, where, holding what pose, with what expression** - and
nothing else.

- Good: "the elf mid-wake-up in her hammock, alarmed, the room still trembling"
- Good: "her rolling onto the riverbank as the ogre's head plunges into the river behind her"
- Bad: "the battle is over and she has won" (a story fact, not a visible pose)
- Bad: "she thinks about what happens next" (nothing visible)

Rules:

- Name ONLY what is visible at that instant. A character who is not in frame must not
  appear in the beat - the beat can summon them into the render.
- Keep beats consistent with the neighbours' first/last sentences; ideally lift the pose
  wording from them.
- Give cells 1 and N+1 full beats: nothing is borrowed there, the beat carries the entire
  pose.
- An empty beat falls back to "holds a calm, natural pose, looking toward the camera" -
  a generic standing pose - so empty cells are the most common cause of unusable anchors.

---

## 5. References, tokens and visual adherence

- Slots per group: up to 9 pictures, 3 videos, 3 audios; a Common References pool is
  shared first, then the group's own assets, renumbered from `<Picture 1>`. Insert the
  tokens (`<Picture N>`, `<Video K>`, `<Audio J>`) in the text where the element appears.
- Declare each reference's role and exclusions where the group text uses it (identity
  only, never pose or background), per the slot map in `PROMPT_WRITING_GUIDE.md`.
- The connected RefMod conditioning (reference modules wired into the Director node)
  keeps the reference subject's identity in both fills and anchors; a project whose
  character comes from RefMod does NOT need picture slots to look consistent - but the
  project prompt should still name the subject and describe invariant wardrobe items the
  shots will reference.
- Adherence degrades first on: scale relationships (fix with the analogy rule, 2.3),
  wardrobe changes mid-film (state them per shot; keep the base in the project prompt),
  and non-reference characters (the full-spec checklist, 2.3).

---

## 6. Worked example (the elf and the ogre project)

Project prompt (the fixed version - invariants only):

```text
Setting and cast for an eleven-shot cinematic action sequence in a dense tropical jungle
at early morning: an elf huntress, and - in the shots that call for him - a colossal ogre
two hundred feet tall. Never any dialogue.

world:
A dense tropical jungle at early morning, with a wide river cutting through the forest
floor and the elf's small wooden tree house high in the branches of one of the great
jungle trees. Mist drifts between the trunks and shafts of golden light fall through the
canopy. The river and the tree house are landmarks of this valley - a shot frames only
what its own description names.
<Subject 1> is a lithe, graceful elf woman in her early twenties with elegant pointed
ears and silver-blonde hair braided back. She wears light, fitted leather-and-cloth armor
in forest greens and browns, carries a slim hunting bow and a quiver of arrows, and keeps
a single silver dagger at her hip.
The ogre is a colossal brute two hundred feet tall - twenty stories - with thick
grey-green hide and heavy muscle, thick jutting tusks and small deep-set eyes, wearing
only a crude ragged loincloth, a wide studded leather belt and a heavy iron collar. How
near he is, what pose he holds, and whether he is present at all are set by each shot's
own description; never add him to a shot that does not name him. When both share the
frame, keep the enormous scale gap between the tiny elf and the giant readable.
Style: cinematic live-action realism, epic fantasy scale, humid morning jungle light with
shafts of golden sun through drifting mist and pollen, photoreal textures, shallow depth
of field on close shots and sweeping deep focus on the scale shots.
Camera: cinematic framing; when the elf and the ogre share a frame, keep both at their
readable relative scale.
Audio: sound is named by each shot's own cues; no dialogue at any point, and
non-diegetic music only where a shot's Music cue names it.
Motion rule: everything stays physically alive and grounded - no stiff posed stillness.
```

Shot 1 (early, ogre explicitly out of frame):

```text
Interior of the small tree house at dawn. She is curled in the vine hammock, half asleep,
when a low rumble rolls through the trunks and the floor boards shiver. She sits up in
one motion, snatches the bow from its hook and takes one stride toward the door, head
tilted to listen. Far off beyond the trees something deep and heavy is moving - it is
never visible in this shot, only its low rumble reaches the tree house. The camera starts
close and intimate on her face, then drifts back as the room sways. Audio: the rumble,
wood creaks, her quick breath. No music yet. End with her crouched at the door, bow in
hand, listening.
```

Boundary beat 2 (her at the door, no ogre named):

```text
her at the tree house door, bow in hand, about to burst outside
```

Shot 10 (ogre explicitly present, state stated locally):

```text
She rolls over the muddy bank and comes up on one knee as the ogre's head plunges into
the river behind her, throwing a wall of water across the bank; silt and leaves rain
down. She stays low, eyes on the sinking mass, and finally straightens. The camera stays
at her level, then rises with the spray. Music: a mournful solo horn fades with the
splash. End high above the broken treetops: the elf a tiny point on the riverbank beside
the fallen ogre.
```

Boundary beat 11 (only what is in frame - both characters named because both are
visible):

```text
high above the broken treetops: the elf a tiny point on the riverbank beside the fallen ogre
```

Note how the state words ("fallen ogre", "plunges") appear ONLY in the shot and its beat,
never in the project prompt. That is the whole discipline.

---

## 7. For AI writers: contract and checklist

When an AI is asked to write prompts for an r2flv project, give it: this guide, the story,
the shot count and lengths, the reference inventory (which characters have pictures /
RefMod and which do not), the location(s), the music strategy, and any dialogue policy.
Require exactly this output shape:

```text
1) PROJECT PROMPT
   <full text, section order: cast line / world block / subject lines / presence rule /
   Style / Camera / Audio / Motion rule>

2) SHOT PROMPTS
   1. <text with opening state, action beats, camera sentences, cues, ending pose>
   ...
   N. <text>

3) BOUNDARY BEATS
   1. <opening pose>
   2. <pose at the cut after shot 1>
   ...
   N+1. <closing pose>

4) QA NOTES
   <one line per check below>
```

Checklist the AI (and the human) must verify before handing the project off:

1. Project prompt contains NO story states, NO "in every shot" conditionals, NO one-shot
   props, NO per-shot camera moves, NO dialogue lines.
2. Every non-reference character has the full spec (scale number plus analogy, build,
   surface, face, gear, sound, movement).
3. Non-reference characters appear ONLY in shots/beats that name them; the presence rule
   exists and is phrased as "never add him to a shot that does not name him".
4. The world block describes a standing set with lighting, palette and one scope
   sentence; props named there really are in every shot.
5. Every shot: opening state, ordered action beats, at least one dedicated camera
   sentence opening with framing words, an explicit "End with..." pose.
6. Shot k's last pose and boundary k+1's beat agree; shot k+1's first sentence matches
   the same boundary.
7. Beat k names only characters visible at that instant; cells 1 and N+1 are non-empty.
8. Music cues exist in exactly the shots that want music; the project Audio line states
   the policy.
9. Plain hyphens only; no em/en dashes; no negative-prompt phrasing beyond policy lines.
10. No number, wardrobe item or state in the project prompt that a shot contradicts.

---

## 8. Operator reference

- Task: `r2flv - Ref2va + FL2v Hybrid` (references plus first/last keyframe pinning).
- Anchor strip: Mode Soft, chunk 22 frames by default, placement "1s before the cut",
  "Pin pose" on; edit beats directly in the cells; the "Project prompt..." button in the
  Boundary anchors bar edits `timeline.global.prompt` (the text this whole guide is
  about).
- Segment lengths must sit on H3's 17k+5 frame grid (124 = 5 s, 175 = 7 s at 24 fps;
  the UI snaps them for you).
- H3 has no negative prompt; keep one prompt block under roughly 7000 characters. The
  project prompt is repeated inside every anchor composition - budget it around
  1200 to 1800 characters so the composed anchor stays comfortable.
- Renders are seed-keyed: after editing text, reroll the boundary (which deletes its old
  images and re-seeds) before rendering, or you will be judging the old picture.
