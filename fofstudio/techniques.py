"""Owlbert's "Tell" cards: the manipulation tricks each video names and teaches.

Teaching the trick works better than only correcting the claim. Short "prebunking" videos that
named one technique made people about twice as good at spotting it, and it held up in a YouTube
field test with about 5.4 million viewers (Roozenbeek & van der Linden, Science Advances 2022).
The list comes from John Cook's FLICC families, the five techniques in that study, and the
channel's own "follow the money".
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Technique:
    key: str
    name: str          # what Owlbert calls it on the card
    meaning: str       # one plain sentence
    everyday: str      # a harmless everyday example, for the "neutral microdose"
    ask: str           # the question to ask next time
    icon: str          # a picture idea for the card


TECHNIQUES: dict[str, Technique] = {t.key: t for t in [
    Technique("fake_expert", "The Fake Expert", "Someone sounds like an authority, but not on this subject.",
              "A famous chef tells you which car engine is safest.",
              "Is this person an expert in THIS, and what do the real experts say?", "a lab coat on a coat hanger"),
    Technique("cherry_picking", "Cherry Picking", "Showing the one fact that fits and hiding the rest.",
              "An ad shows the single five-star review and skips the hundred one-star ones.",
              "What's missing? Can I see the whole basket?", "a hand picking one cherry from a full tree"),
    Technique("fear", "Fear Selling", "Scaring you so you act before you think.",
              "'Only two left! Offer ends in ten minutes!'",
              "Why am I being rushed, and who gains if I panic?", "a ticking clock next to a price tag"),
    Technique("follow_money", "Follow the Money", "The person warning you profits from the thing they warn about.",
              "The man shouting that the bridge will fall also sells helmets.",
              "Who makes money if I believe this?", "a megaphone with a price tag"),
    Technique("false_choice", "The False Choice", "Pretending there are only two options when there are more.",
              "'Either you buy this mattress or you'll never sleep again.'",
              "Are those really the only two choices?", "a fork in the road with a hidden third path"),
    Technique("scapegoat", "The Scapegoat", "Blaming one group for a big, complicated problem.",
              "Blaming the new kid every time something goes missing.",
              "Is one group really behind all of this?", "a pointing finger and a crowd of shadows"),
    Technique("emotional_language", "Loaded Words", "Using scary or angry words instead of evidence.",
              "Calling a light rain 'a terrifying storm of destruction'.",
              "If I take out the scary words, what's actually being claimed?", "a megaphone spraying red exclamation marks"),
    Technique("conspiracy", "The Secret Plot", "Any evidence against the claim is treated as proof of a cover-up.",
              "'You can't find proof? That's how well they hid it!'",
              "What evidence would change this person's mind? If none, it isn't evidence-based.",
              "a magnifying glass over a blank page"),
    Technique("moving_goalposts", "Moving the Goalposts", "When a prediction fails, the claim changes instead of admitting it.",
              "'The world ends Tuesday.' Tuesday passes. 'I meant NEXT Tuesday.'",
              "What did they say would happen, and did it?", "goalposts on wheels"),
    Technique("ad_hominem", "Attack the Messenger", "Attacking the person instead of answering the evidence.",
              "'You can't trust his math, look at his haircut.'",
              "Did they answer the evidence, or just the person?", "a target drawn on a messenger's back"),
    Technique("anecdote", "One Story Proves All", "Using one dramatic story as if it proves a general rule.",
              "'My uncle smoked and lived to 100, so smoking is fine.'",
              "Is this one story, or what happens most of the time?", "one raindrop labelled 'the whole storm'"),
    Technique("magnified_minority", "The Loud Few", "Making a few dissenters look like half the experts.",
              "Two people disagree with ninety-eight, and the show seats them one against one.",
              "How many experts are on each side, really?", "a seesaw with two people outweighing a crowd"),
]}


def get(key: str) -> Technique | None:
    return TECHNIQUES.get(key)


def for_prompt() -> list[dict[str, str]]:
    return [{"key": t.key, "name": t.name, "meaning": t.meaning} for t in TECHNIQUES.values()]
