"""Video styles: the same facts, told and drawn in different ways.

Every style keeps the same factual skeleton (fact first, the myth shown once and marked as a claim,
how the lie was built, the trick named, the real story, the fact again). A style changes Owlbert's
tone, the pacing, how long each shot holds, and the picture recipe for the image and video models.

Pacing figures are starting points from the research report ("Creative styles and studio polish");
adjust them after watching a few episodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Style:
    key: str
    name: str
    blurb: str                 # one line for the picker
    tone: str                  # for the writer
    wpm: int                   # Owlbert's narration speed in this style (words per minute)
    shot_seconds: float        # average time each picture stays on screen
    look: str                  # picture recipe added to every image prompt
    negative: str              # what the picture must not look like
    motion: str                # added to animation prompts
    owl_look: str              # how Owlbert's scenes are staged
    sample: str                # a short original passage in this style, for the writer to match
    humor: int = 1             # 0 none ... 3 lots (always 0 on careful topics)
    caricature: bool = False   # may show cartoon caricatures of the public figures who sold the lie
    cartoon: bool = False      # clearly not photographic (required for caricatures)
    shot_types: tuple[str, ...] = field(default=("broll", "owl", "detail"))


STYLES: dict[str, Style] = {s.key: s for s in [
    Style("documentary", "Archival documentary",
          "Serious and measured. Old documents, period places, slow camera moves.",
          "Grave and measured. Owlbert speaks quietly, lets the evidence carry the weight, reads quotes in full.",
          138, 6.0,
          "archival documentary still, period-accurate setting, film grain, warm desaturated colour grade, "
          "soft window light, 16:9 cinematic composition",
          "cartoon, anime, neon, oversaturated",
          "slow push-in, dust drifting in light, very subtle movement",
          "Owlbert at a lamp-lit library desk piled with old newspapers",
          "The memo was dated March the ninth. Four pages, typed, no letterhead. By the end of the week, its "
          "wording was on the radio in three states, and nobody reading it aloud had asked where it came from.",
          humor=0),
    Style("classroom", "Owlbert's Classroom",
          "A warm lesson at the chalkboard. Great for teaching one trick.",
          "Warm and teacherly. Owlbert talks to his students, asks questions, draws diagrams, uses simple "
          "everyday examples before the real case.",
          145, 5.0,
          "warm classroom illustration, green chalkboard with chalk diagrams, wooden desks, golden afternoon "
          "light, storybook painting style, 16:9",
          "photograph, photorealistic, gore",
          "chalk dust drifting, gentle camera drift across the board",
          "Owlbert at the chalkboard holding a pointer, a cozy classroom behind him",
          "Hoo, eyes up here, class. Say I tell you the bridge is about to fall, and, by luck, I sell helmets. "
          "Before you buy, ask the oldest question there is: who gains if you believe me?",
          humor=1, cartoon=True),
    Style("cartoon", "Cartoon explainer",
          "Bright flat 2D cartoon with one big visual metaphor, like a fear machine with gears.",
          "Curious and playful. One big metaphor carries the idea. Quick, clear, friendly.",
          155, 4.0,
          "flat 2D vector cartoon, bold clean outlines, bright limited palette of teal, cream, coral and gold, "
          "simple shapes, playful explainer animation style, 16:9",
          "photograph, photorealistic, 3D render, gore",
          "bouncy cartoon motion, simple looping movement, smooth animation",
          "Owlbert in a bright cartoon studio with gears and arrows floating behind him",
          "Picture a machine. You pour worry in the top, and out the bottom drops a forty-dollar bucket of "
          "freeze-dried beans. Today we take the cover off and look at every gear.",
          humor=2, cartoon=True, shot_types=("broll", "owl", "metaphor")),
    Style("satire", "Political-cartoon satire",
          "Editorial-cartoon ink style. Big-head caricatures of the people who sold the lie.",
          "Wry and sharp, punching up. Exaggerates only what the sellers are documented doing; every joke is "
          "followed by the plain sourced fact.",
          155, 3.5,
          "newspaper editorial cartoon, black ink line art with watercolour wash, exaggerated proportions, "
          "labels drawn as simple symbols, cream paper texture, 16:9",
          "photograph, photorealistic, realistic skin, 3D render",
          "slight wobble of ink lines, simple cartoon movement",
          "Owlbert as a cartoon in an editorial cartoon panel, raising one eyebrow",
          "And who should arrive with a solution? The same men who announced the problem, holding a catalog. "
          "Prices, as the record shows, were going up by the week.",
          humor=3, caricature=True, cartoon=True, shot_types=("broll", "caricature", "owl", "metaphor")),
    Style("newscast", "Mock newscast",
          "'Owl News at Eleven': a news desk, breaking-news banners, field reports.",
          "Anchor cadence. Owlbert reports from the desk and 'goes live' to the scene. Real dated headlines only.",
          160, 4.0,
          "retro television news studio set, desk with monitors, blue and gold broadcast lighting, 1990s "
          "TV graphics feel, 16:9",
          "photorealistic faces, gore",
          "slow studio camera dolly, monitors flickering softly",
          "Owlbert behind a TV news desk in a suit jacket, a city skyline on the monitor behind him",
          "Good evening. Our top story: it is December, nineteen ninety-nine, and the end of the world now "
          "comes with a payment plan. We go live to a convention hall in Atlanta.",
          humor=2, cartoon=True),
    Style("truecrime", "True-crime investigation",
          "Case files, an evidence board with red string, redacted pages.",
          "Hushed and suspenseful. Owlbert opens the case file and walks the evidence in order.",
          140, 5.0,
          "detective case file aesthetic, cork evidence board with red string and pinned documents, desk lamp, "
          "deep shadows, moody teal and amber light, 16:9",
          "cartoon, bright colours, gore, blood",
          "slow push-in on the evidence board, lamp light flickering",
          "Owlbert in a dim office studying an evidence board pinned with papers",
          "Exhibit one is a receipt. Exhibit two is a broadcast, recorded the same afternoon. Lay them side by "
          "side and a pattern starts to show.",
          humor=0),
    Style("courtroom", "Courtroom sketch",
          "The record on trial: exhibits A, B, C, drawn like a courtroom sketch artist.",
          "Formal and precise. Owlbert presents exhibits to the jury, the viewer. The court record is the hero.",
          140, 5.0,
          "courtroom sketch artist drawing, pastel and charcoal on paper, loose expressive lines, wood-panelled "
          "courtroom, 16:9",
          "photograph, photorealistic",
          "gentle drift across the sketch, pastel dust",
          "Owlbert as counsel at a courtroom lectern, sketched in pastel",
          "The court did not have to guess. It had the emails. Exhibit B, read into the record on the second day, "
          "settles the question in a single sentence.",
          humor=0, cartoon=True),
    Style("noir", "Noir detective",
          "Black and white, rain, venetian-blind shadows. Owlbert the hard-boiled detective.",
          "First-person hard-boiled detective voice. Short punchy lines. The claim 'walks into the office'.",
          135, 5.5,
          "film noir, high-contrast black and white, venetian blind shadows, rain on the window, smoky office, "
          "1940s, 16:9",
          "colour, bright, cartoonish, gore",
          "rain streaking, slow smoke drift, light from passing cars",
          "Owlbert in a fedora at a detective's desk, blinds casting stripes across him",
          "The claim walked into my office on a Tuesday. Nice suit, big promises, no paperwork. In my line of "
          "work, that's the first thing you notice.",
          humor=1, cartoon=True),
    Style("comic", "Comic book",
          "Inked panels, halftone dots, bold captions. The tricks are the villains.",
          "Punchy captions and big moments. The manipulation tricks are the villains, never the believers.",
          150, 3.5,
          "comic book panel, bold ink lines, halftone dot shading, vivid flat colours, dramatic angles, 16:9",
          "photograph, photorealistic, gore",
          "dramatic push-in, speed lines, panel shake",
          "Owlbert as a comic-book hero landing on a rooftop, cape-like wings spread",
          "Meet the Cherry Picker. He keeps the one number that scares you and quietly drops the other "
          "ninety-nine. His weakness? Anyone who asks to see the whole basket.",
          humor=2, cartoon=True, shot_types=("broll", "owl", "metaphor")),
    Style("papercut", "Paper cut-out",
          "Handmade construction-paper layers, whimsical and gentle.",
          "Whimsical and gentle, like a storybook. Good for younger viewers and Shorts.",
          145, 4.5,
          "paper cut-out collage, layered construction paper, visible paper texture, soft drop shadows, "
          "handmade stop-motion look, 16:9",
          "photograph, photorealistic, gore",
          "paper layers sliding with gentle parallax, stop-motion feel",
          "Owlbert as a paper cut-out puppet in a paper library",
          "Once upon a calendar, a little date with two digits caused a very big fuss. Some people fixed it. "
          "Some people, it turns out, sold tickets to the fuss.",
          humor=2, cartoon=True),
    Style("infomercial", "Retro infomercial parody",
          "1990s pitchman energy, VHS scanlines, starbursts: 'But wait, there's more!'",
          "Over-the-top 1990s pitchman parody of the sellers' own pitch, interrupted by Owlbert's sober facts.",
          165, 3.0,
          "1990s infomercial set, VHS scanlines, starburst graphics, bright studio lights, cheesy product "
          "display table, 16:9",
          "photorealistic faces, gore",
          "VHS wobble, quick zoom on the product, flashing starburst",
          "Owlbert holding up a product with a raised eyebrow on a cheesy infomercial set",
          "But wait, there's more! Act now and the end of the world comes with a free water filter! Hoo. Let's "
          "pause the tape and check what the receipts actually say.",
          humor=3, cartoon=True, shot_types=("broll", "owl", "metaphor")),
    Style("heist", "Heist / con caper",
          "How the con was pulled: crew introductions, blueprints, freeze frames.",
          "A heist movie told in reverse: we introduce the 'crew' (the tricks), the blueprint and the score, "
          "then show how the con was spotted.",
          155, 3.5,
          "heist movie style, blueprints on a table, split screens, freeze-frame with bold name cards, "
          "teal and orange cinematic grade, 16:9",
          "gore, photorealistic faces",
          "freeze frame then snap back to motion, slow slide across the blueprint",
          "Owlbert leaning over a blueprint table under a hanging lamp",
          "Every con needs a crew. The Fake Expert to sound sure. The Fear to make you hurry. And the Product, "
          "waiting at the door. Here's how they planned the job.",
          humor=2, cartoon=True, shot_types=("broll", "owl", "metaphor")),
]}

DEFAULT = "documentary"


def get(key: str | None) -> Style:
    return STYLES.get(key or DEFAULT, STYLES[DEFAULT])


def choices() -> list[tuple[str, str]]:
    return [(s.key, s.name) for s in STYLES.values()]
