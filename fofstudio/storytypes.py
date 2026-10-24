"""Story types (how the story is built) and writer types (how it's written: the writing style, not
Owlbert's speaking voice). Chosen on the Stories page; "Let the AI pick" gives the three story options
three different types and writers, so videos don't all sound alike.

From the research "Story types writer voices animation" (project docs). Every type keeps the
debunking rules: open on a true fact, state the claim once with a warning, name one trick, give one
question to ask, end on the fact. Writer styles are described by their traits, never by naming a
living writer, and the house rules (grade 6-8 reading, facts only from the evidence, never mock
believers) always win over the style.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

SHARED_RULES = """Rules for every story type:
- The opening never states the myth as if it were true: open on a true fact, a mystery question, the scale
  of the spread, or a consequence.
- State the claim ONCE, in the claim scene only, after a warning ("Heads up: here's the claim, and it
  doesn't hold up."), in plain words, not its catchy slogan. Afterwards call it "the claim" or "the rumor".
- State the core fact at least three times: early, in the verdict, and in the outro.
- The tell scene names ONE technique and shows exactly where the claim uses it.
- The toolkit scene gives ONE question the viewer can reuse, with a harmless everyday example.
- Who benefited and who was harmed: say what's documented ("court records show"), what's alleged, and
  what's opinion. Never invent quotes for real people.
- Humor aims at sellers and tricks, never at believers or victims."""


@dataclass(frozen=True)
class Beat:
    name: str
    role: str
    share: int          # rough % of the running time
    how: str            # what to write


@dataclass(frozen=True)
class StoryType:
    key: str
    name: str
    blurb: str
    hook: str
    ending: str
    beats: tuple[Beat, ...]
    suits: str
    careful_ok: bool = False      # usable for tragedies (real deaths or victims)
    writers: tuple[str, ...] = ()

    @property
    def roles(self) -> list[str]:
        return [b.role for b in self.beats]

    def sheet(self) -> str:
        lines = [f"Story type: {self.name}. {self.blurb} Hook: {self.hook} Ending: {self.ending}", "Beats in order:"]
        lines += [f"{k}. {b.name} ({b.role}, about {b.share}% of the video): {b.how}" for k, b in enumerate(self.beats, 1)]
        return "\n".join(lines)


B = Beat
STORY_TYPES: dict[str, StoryType] = {t.key: t for t in [
    StoryType("fact_sandwich", "The Fact Sandwich", "The classic debunk: the fact, the claim once, the proof, the trick, "
              "the fact again. Clear and calm; the safe default.", "a surprising true fact", "a calm restatement of the fact",
              (B("Fact hook", "intro", 8, "Open with the true fact in one punchy sentence (15 words or fewer), then why it matters."),
               B("Warning + claim", "claim", 7, "Warn that a false claim is coming, state it once in neutral words, say where it spread."),
               B("The record", "record", 30, "Lay out 3-5 pieces of evidence, strongest first, each with its source. One vivid example."),
               B("The trick", "tell", 15, "Name the technique and show exactly where the claim uses it."),
               B("Who it hurt", "harm", 8, "The documented consequences."),
               B("Who it helped", "benefit", 7, "Who profited, documented."),
               B("Next time", "toolkit", 10, "The one question to ask next time, with an everyday example."),
               B("Verdict", "verdict", 10, "The rating, and the fact restated."),
               B("Sign-off", "outro", 5, "The fact a third time, warmly.")),
              "any topic, including tragedies (sober tone)", True, ("wire_bulletin", "explainer", "socratic_professor")),
    StoryType("patient_zero", "Patient Zero: how a rumor is born", "A biography of the rumor itself: the true event it grew "
              "from, the moment it was bent, and how it spread.", "the scale of the spread, then 'but where did it start?'",
              "back to the true origin",
              (B("Cold open on the spread", "intro", 8, "Show how far it spread (shares, years, countries) without stating the claim; end on 'But where did it start?'"),
               B("The real starting point", "record", 12, "The true event or kernel the rumor grew from."),
               B("The distortion", "claim", 7, "Warning, then the claim once; pinpoint the moment the truth was bent."),
               B("Spread timeline", "record", 25, "3-6 dated milestones: when, where, who amplified it, what changed. Link them with 'but' and 'therefore'."),
               B("Who fed it", "benefit", 10, "The accounts or sellers that gained, documented."),
               B("The fallout", "harm", 12, "The documented consequences."),
               B("Why it stuck", "tell", 10, "The technique that made it sticky."),
               B("Toolkit", "toolkit", 6, "A question like 'Can I find the original source and date?'"),
               B("Verdict", "verdict", 10, "The rating; restate the true origin.")),
              "viral hoaxes, misquotes, fake images, health rumors, urban legends", True, ("chronicler", "investigator")),
    StoryType("whodunit", "Who Started This? (a mystery)", "Owlbert as detective: the mystery is who made or profited from the "
              "claim; clues rule suspects out one by one.", "an open question", "a 'case closed' moment",
              (B("The case file", "intro", 8, "Pose the mystery question and give one true fact about the case."),
               B("The claim on the evidence board", "claim", 6, "Warning, then the claim once."),
               B("Clues", "record", 30, "Each clue is a documented fact that rules out an innocent explanation; end each with a 'but'."),
               B("Red herring", "record", 8, "An obvious suspect turns out innocent: be fair."),
               B("The method", "tell", 10, "How the trick worked, before who did it."),
               B("The reveal", "benefit", 14, "The documented originator or beneficiary and what they gained; if nobody can be identified, say so."),
               B("The damage", "harm", 10, "The documented harm."),
               B("Detective's notebook", "toolkit", 6, "The question to ask next time."),
               B("Case closed", "verdict", 8, "The verdict, and the fact restated.")),
              "hoaxes with a known creator, fake campaigns, astroturf", False, ("night_shift_detective", "case_file_podcaster")),
    StoryType("follow_money", "Follow the Money", "A scam exposé built on the money trail: the pitch, the product, the buyers, "
              "the seller's profit.", "a striking price or money figure, then 'So who's selling this?'",
              "the fact, plus 'keep your wallet closed'",
              (B("The price tag", "intro", 8, "A true, striking money figure; then 'So who's selling this?'"),
               B("The pitch", "claim", 7, "Warning, then the sales claim once, paraphrased (no slogans)."),
               B("The money trail", "benefit", 25, "3-5 documented steps from the viewer's wallet to the seller: product, affiliate, company, owner."),
               B("What the evidence says", "record", 20, "The science or the record on the product."),
               B("Who paid", "harm", 12, "Customers' losses and complaints, in total, never mocking anyone."),
               B("The sales trick", "tell", 12, "e.g. fake experts, scary words, fake scarcity."),
               B("Wallet check", "toolkit", 8, "e.g. 'Who profits if I believe this?'"),
               B("Verdict", "verdict", 8, "The verdict and the fact.")),
              "miracle cures, supplements, crypto, guru courses, survival-gear sellers", True, ("investigator", "case_file_podcaster")),
    StoryType("rise_and_fall", "Rise and Fall of a Grifter", "The life story of the person who sold the claim: the rise, the "
              "cracks, the fall. They're the main character, not the hero.", "the seller at their peak",
              "a mirror of the opening image, then the fact",
              (B("Opening image", "intro", 5, "The person at their peak, plus one true fact that hints at the fall."),
               B("Set-up", "record", 10, "Who they were before: documented background only."),
               B("Catalyst", "claim", 5, "The moment they started pushing the claim: warning, then the claim once."),
               B("The rise", "benefit", 25, "Followers, money and fame gained, documented."),
               B("Cracks", "record", 10, "The first evidence against them."),
               B("The bill comes due", "harm", 15, "Consequences for followers; investigations."),
               B("The fall", "record", 10, "Lawsuits, bans, collapse, documented."),
               B("How they did it", "tell", 8, "The technique."),
               B("Toolkit", "toolkit", 5, "The question to ask next time."),
               B("Final image + verdict", "verdict", 7, "Mirror the opening; restate the fact.")),
              "public sellers of hoaxes (gurus, influencers, historical quacks)", False, ("case_file_podcaster", "chronicler")),
    StoryType("long_con", "The Long Con", "The scam told in the stages of a classic con trick, like a heist film, from the con "
              "artist's playbook.", "'Here's how you take millions with a story'", "'now you know the playbook'",
              (B("The score", "intro", 8, "A true fact about the size of the con."),
               B("The tale", "claim", 7, "Warning, then the pitch once."),
               B("Stage 1: pick the mark", "record", 10, "Who was targeted and why, documented."),
               B("Stage 2: the convincer", "record", 12, "The early 'win' or fake proof that hooked people."),
               B("Stage 3: raise the stakes", "record", 12, "How the asks grew."),
               B("Stage 4: the sting", "benefit", 10, "The payoff to the seller."),
               B("Stage 5: the blow-off", "harm", 10, "How victims were kept quiet or blamed themselves (with care)."),
               B("The playbook, named", "tell", 10, "Name the technique and show it at work."),
               B("Toolkit", "toolkit", 8, "The question that breaks the con."),
               B("Verdict", "verdict", 13, "The verdict and the fact.")),
              "MLMs, Ponzi-style schemes, fake charities, 'secret knowledge' courses", False,
              ("night_shift_detective", "play_by_play_caller")),
    StoryType("trial", "The Trial", "The claim is on trial: the believers' best case, examined; the evidence against; "
              "cross-examination; the verdict. The evidence decides, not airtime.", "'Today, the claim is on trial.'",
              "a gavel moment",
              (B("Court is in session", "intro", 6, "A true fact, and the rule: evidence decides, not airtime."),
               B("The charge", "claim", 6, "Warning, then the claim once."),
               B("Exhibits for the claim", "record", 15, "The 2-3 strongest points believers make, each immediately tagged with what it really shows."),
               B("The expert witness", "record", 25, "The evidence against, from qualified sources. At least twice the time of the exhibits."),
               B("Cross-examination", "tell", 15, "Expose the trick in the exhibits."),
               B("Harm to others", "harm", 8, "Sober and respectful."),
               B("Motive", "benefit", 7, "Who gained, documented."),
               B("The verdict", "verdict", 8, "The gavel, and the fact restated."),
               B("Instructions for next time", "toolkit", 5, "The question to ask."),
               B("Court adjourned", "outro", 5, "The fact once more.")),
              "pseudoscience, settled claims that sound contested, historical myths", False, ("advocate_for_evidence",)),
    StoryType("lab", "Owlbert's Lab", "Myth-busting: turn the claim into a testable prediction, design a fair test, and "
              "look at what real experiments found.", "'Can we test it?'", "a stamped result",
              (B("Lab coat on", "intro", 7, "A true fact, then 'let's test it.'"),
               B("The hypothesis", "claim", 7, "Warning, then the claim once as a prediction: 'If this were true, we'd expect...'"),
               B("The method", "record", 15, "How a fair test works, with controls, in plain words."),
               B("The results", "record", 25, "What real studies or records found, with sources."),
               B("Why it seemed true", "tell", 15, "The trick: e.g. one story taken as proof, or randomness read as a pattern."),
               B("The cost of believing", "harm", 8, "The documented harm."),
               B("Who sells it", "benefit", 6, "Who profits, if anyone (documented)."),
               B("Try this at home", "toolkit", 9, "A simple question or mini-test the viewer can run."),
               B("Busted or not", "verdict", 8, "The result, and the fact.")),
              "health myths, science or engineering myths, viral challenges (narrated, not demonstrated)", False,
              ("stargazer", "explainer")),
    StoryType("trick_first", "How the Trick Works", "Teach the trick first on something silly and harmless, then reveal the "
              "real claim uses the same trick. Closest to the prebunking research.", "a little demonstration",
              "'You can't un-see it now.'",
              (B("The magic trick", "intro", 8, "Owlbert shows the technique on something silly and non-political (an everyday ad, a cartoon)."),
               B("Reveal the method", "tell", 15, "Name the technique and how it fools us."),
               B("Spot it yourself", "toolkit", 8, "The question that catches it."),
               B("Now, the real thing", "claim", 6, "Warning, then the claim once: 'Notice anything?'"),
               B("Breaking it down", "record", 28, "The facts."),
               B("Who's pulling the strings", "benefit", 12, "Who gained, documented."),
               B("Why it matters", "harm", 10, "The harm."),
               B("Verdict", "verdict", 13, "Restate the fact and the technique's name.")),
              "any recurring trick; very polarised topics", False, ("socratic_professor", "porch_humorist")),
    StoryType("the_turn", "The Turn (no villain)", "A gentle four-part story with a twist of perspective instead of a fight: "
              "for honest mistakes, misquotes and 'everyone knows' myths.", "a familiar picture", "reflective and kind",
              (B("The world", "intro", 12, "A true, familiar scene or fact."),
               B("Going deeper", "record", 25, "More true detail; the viewer builds a picture."),
               B("The common belief", "claim", 6, "Warning, then the myth once ('Many of us were taught...')."),
               B("The turn", "record", 25, "A new angle (the whole data, the full quote, the real timeline) that changes everything; name the mechanism."),
               B("Why it matters", "harm", 8, "Small and honest; it can be 'it doesn't hurt much, but...'"),
               B("Toolkit", "toolkit", 9, "The question to ask."),
               B("Reconciliation", "verdict", 15, "What we knew plus the turn equals the whole truth; restate the fact.")),
              "misquotes, '10% of the brain' myths, historical misconceptions, honest science mistakes", False,
              ("campfire_teller", "stargazer")),
    StoryType("rabbit_hole", "The Rabbit Hole and Back", "Follows a clearly made-up composite believer ('Meet Sam, a made-up "
              "person, but their story is real for many') into the claim and back out: empathy, not mockery.",
              "a relatable person", "'it's never too late to check'",
              (B("Comfort zone", "intro", 8, "'Meet Sam, a made-up person, but their story is real for many', plus one true fact."),
               B("A real want", "intro", 8, "Sam wants something real: health, certainty, belonging, money."),
               B("Meeting the claim", "claim", 8, "Warning, then the claim once, as Sam meets it."),
               B("Going along", "benefit", 12, "Sam joins in; who gains from Sam's attention and money (documented)."),
               B("What the record says", "record", 10, "The belonging feels good, but the evidence quietly says otherwise."),
               B("The price", "harm", 14, "Typical documented harms, from real reporting, in total."),
               B("The way back", "tell", 15, "What helped Sam see the technique, and the facts."),
               B("Changed", "toolkit", 10, "The question Sam asks now."),
               B("Verdict", "verdict", 15, "Restate the fact, and a kind word to anyone who believed.")),
              "wellness cults, rabbit holes, MLMs, flat earth; viewers who half believe", False,
              ("campfire_teller", "field_naturalist")),
    StoryType("abt", "Quick Hit (And-But-Therefore)", "A tight short form: two true facts, BUT the claim, the facts, the "
              "trick, THEREFORE what's true. Best for 3-6 minutes.", "'And... and... but'", "the 'therefore' is the call to action",
              (B("AND", "intro", 15, "Two true, observable facts that set the scene."),
               B("BUT", "claim", 10, "'But a claim is spreading that...' (warning, then the claim once)."),
               B("The facts", "record", 35, "The evidence."),
               B("The trick", "tell", 15, "The technique."),
               B("THEREFORE", "verdict", 15, "What's actually true and what to do."),
               B("Toolkit + sign-off", "toolkit", 10, "The question, and the fact once more.")),
              "breaking rumors, a single viral image or quote, short videos", True, ("wire_bulletin", "explainer")),
    StoryType("history_rhymes", "History Rhymes: then and now", "Two stories side by side: an old hoax that's fully resolved, "
              "and its modern version, using the same trick in a new costume.", "two dates side by side",
              "'History doesn't repeat, but hoaxes do.'",
              (B("Two dates", "intro", 7, "'In [year], people believed... In [year], they still do' - led by a fact."),
               B("Then: the old hoax", "record", 22, "A historical case, fully resolved with known facts."),
               B("Now: the new version", "claim", 6, "Warning, then the modern claim once."),
               B("Now: the record", "record", 20, "The evidence on the modern claim."),
               B("Same trick, new costume", "tell", 12, "The shared technique."),
               B("Who profited then and now", "benefit", 10, "Documented."),
               B("The cost then and now", "harm", 8, "Documented."),
               B("Toolkit", "toolkit", 7, "The question to ask."),
               B("Verdict", "verdict", 8, "The verdict and the fact.")),
              "moral panics, quack medicine, old forgeries and new fakes", True, ("chronicler", "porch_humorist")),
]}
DEFAULT_TYPE = "fact_sandwich"


@dataclass(frozen=True)
class Writer:
    key: str
    name: str
    sounds_like: str
    humor: int
    prompt: str
    examples: tuple[str, ...]

    @property
    def light(self) -> bool:
        """Too playful for a careful topic."""
        return self.key in ("picture_book_narrator", "play_by_play_caller", "gentle_satirist", "porch_humorist")


@lru_cache(maxsize=1)
def _writer_data() -> dict:
    return json.loads((Path(__file__).parent / "data" / "writers.json").read_text(encoding="utf-8"))


def house_rules() -> str:
    return _writer_data()["house_rules"]


def writers() -> dict[str, Writer]:
    return {w["key"]: Writer(w["key"], w["name"], w["sounds_like"], int(w["humor"]), w["prompt"],
                             tuple(w.get("examples", []))) for w in _writer_data()["writers"]}


DEFAULT_WRITER = "socratic_professor"


def allowed_types(careful: bool) -> list[StoryType]:
    return [t for t in STORY_TYPES.values() if t.careful_ok or not careful]


def allowed_writers(careful: bool, humor: int) -> list[Writer]:
    return [w for w in writers().values() if not (careful and w.light) and not (humor < 2 and w.humor >= 3)]


def pick_three(creative: dict, seed: str = "") -> list[tuple[StoryType, Writer]]:
    """The type and writer for each of the three story options. A fixed choice is used for all three;
    "auto" gives three different types (each with a writer that suits it)."""
    import random
    rnd = random.Random(seed)
    careful, humor = bool(creative.get("careful")), int(creative.get("humor", 1))
    ok_types = allowed_types(careful)
    ok_writers = {w.key: w for w in allowed_writers(careful, humor)}
    want_type, want_writer = creative.get("story_type", "auto"), creative.get("writer", "auto")
    if want_type in STORY_TYPES and STORY_TYPES[want_type] in ok_types:
        types = [STORY_TYPES[want_type]] * 3
    else:
        types = rnd.sample(ok_types, k=min(3, len(ok_types)))
        while len(types) < 3:
            types.append(STORY_TYPES[DEFAULT_TYPE])
    out = []
    used: set[str] = set()
    for t in types:
        if want_writer in ok_writers:
            w = ok_writers[want_writer]
        else:
            choices = [ok_writers[k] for k in t.writers if k in ok_writers and k not in used] or \
                [w for k, w in ok_writers.items() if k not in used] or list(ok_writers.values())
            w = rnd.choice(choices)
        used.add(w.key)
        out.append((t, w))
    return out


def writer_block(w: Writer) -> str:
    ex = "\n".join(f"- {e}" for e in w.examples[:3])
    return (f"{house_rules()}\n\nWRITING STYLE (how the words are written; Owlbert's warmth stays): {w.name}, "
            f"which sounds like {w.sounds_like}\n{w.prompt}\n"
            + (f"Example lines in this style (about a different topic; match the style, never copy them):\n{ex}\n" if ex else "")
            + "The style changes the wording, never the facts: say each fact plainly first, then add flavor. "
              "Keep the style strongest in the opening, the transitions and the ending, and plain during evidence.")
