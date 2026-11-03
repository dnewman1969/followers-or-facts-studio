"""What Owlbert says out loud (Dave, 2026-11-02: "some parts it was reading what sounded like a web site URL and
was odd and out of the story vibe ... not sound like a reference index").

Citations belong on screen (source cards, the description), never in the spoken narration. Three tools:
  spoken_source(source)  how a writer may name a source aloud: "a 2019 Senate report", "court records",
                         never its file name, web address or case number;
  speakable(text)        the last filter on narration: web addresses, domains, file names, case and docket
                         numbers and source IDs are taken out or said in words; words inside verified quotes are
                         left exactly as they are (the quote checks compare them word for word);
  unspeakable(text)      what speakable would change (for the script's checks and the production diary).
"""

from __future__ import annotations

import re
from typing import Any

_LEAD = r"(?:\b(?:at|on|from|via|see|visit|in|under)\s+)?"      # the little word that pointed at it
URL = re.compile(_LEAD + r"\b(?:https?://|www\.)[^\s,;)]+", re.I)
DOMAIN = re.compile(r"\b((?:[a-z0-9-]+\.)+)(com|org|net|gov|edu|info|tv|io|co|us|uk|news)\b(/[^\s,;)]*)?", re.I)
FILE = re.compile(_LEAD + r"\b[\w-]+\.(?:pdf|html?|php|aspx?|docx?|txt|jpe?g|png|mp4|mp3)\b", re.I)
DOCKET = re.compile(_LEAD + r"\b(?:case|docket|ecf|doc\.|dkt\.?|file)\s*(?:no\.?|number|#)?\s*"
                    r"[\w:.-]*\d[\w:-]*", re.I)
CASE_ID = re.compile(_LEAD + r"\b\d{1,2}:\d{2}-[a-z]{2}-\d{3,6}(?:-\w+)?\b", re.I)      # 1:18-cv-01234
SOURCE_ID = re.compile(r"\b(?:S|E|C|A)-[A-Z0-9-]{2,}\b|\b[A-Z]{1,3}\d{2,}[A-Z]?\b")   # S-COURT-12, E14, C-031
BRACKET_REF = re.compile(r"\s*[\[(](?:source|see|ref|via|cited|citation)[^\])]*[\])]", re.I)
QUOTED = re.compile(r"\"[^\"]*\"|“[^”]*”")
# a stage direction about the narrator, which he would read out (Dave's diary 2026-11-03: "Owlbert pushes his
# glasses up."): Owlbert speaks in the first person, so "Owlbert <does something>." is never narration
STAGE = re.compile(r"(?:(?<=^)|(?<=[.!?]\s))\(?\*?(?:Professor\s+)?Owlbert(?:\s+McFinnegan)?\s+(?:\w+ly\s+)?"
                   r"(?:pushes|adjusts|leans|points|taps|flaps|tilts|raises|looks|turns|smiles|nods|shakes|peers|"
                   r"holds|pulls|lifts|spreads|folds|hops|flies|waves|sighs|gestures|squints|glances|steps|walks|"
                   r"sits|stands|clears|scratches|ruffles|blinks)\b[^.!?]*[.!?]\)?\*?\s*", re.M)
DIRECTION = re.compile(r"\s*(?:\*[^*\n]{2,80}\*|\[(?:[^\]\n]{2,80})\])\s*")


def _site_name(m: re.Match) -> str:
    """infowars.com -> Infowars' website (a name a narrator would say)."""
    labels = [x for x in m.group(1).split(".") if x and x.lower() not in ("www", "m", "en")]
    name = labels[-1] if labels else ""
    if not name:
        return ""
    pretty = name if any(c.isupper() for c in name) else name.capitalize()
    return f"{pretty}'s website" if not pretty.endswith("s") else f"{pretty}' website"


def _clean(part: str) -> str:
    t = STAGE.sub("", part)
    t = DIRECTION.sub(" ", t)
    t = URL.sub("", t)
    t = FILE.sub("", t)
    t = DOMAIN.sub(_site_name, t)
    t = DOCKET.sub("", t)
    t = CASE_ID.sub("", t)
    t = BRACKET_REF.sub("", t)
    t = SOURCE_ID.sub("", t)
    t = re.sub(r"\(\s*\)|\[\s*\]", "", t)
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    t = re.sub(r"([,;:])\s*([.!?])", r"\2", t)
    t = re.sub(r"([.!?])(?:\s*\.)+", r"\1", t)          # a sentence that was only a reference
    t = re.sub(r"\b(the|a|an|at|on|in|from|to|by|of)\s+([.,;!?])", r"\2", t, flags=re.I)
    return re.sub(r"[ \t]{2,}", " ", t)


def speakable(text: str) -> str:
    """The narration as it can be said aloud. Verified quotes inside double quotes are kept exactly."""
    if not text:
        return text
    out, last = [], 0
    for m in QUOTED.finditer(text):
        out.append(_clean(text[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(_clean(text[last:]))
    return re.sub(r"[ \t]{2,}", " ", "".join(out)).strip()


def unspeakable(text: str) -> list[str]:
    """The bits speakable() would take out or reword."""
    found: list[str] = []
    bare = QUOTED.sub(" ", text or "")
    for rx in (URL, FILE, DOMAIN, CASE_ID, DOCKET, SOURCE_ID):
        found += [m.group(0) for m in rx.finditer(bare)]
    return list(dict.fromkeys(f.strip() for f in found if f.strip()))


KIND_WORDS = {"court": "court records", "court_record": "court records", "legal": "court records",
              "government": "a government report", "report": "a report", "news": "news reporting",
              "fact_check": "a fact-check", "academic": "a study", "study": "a study", "archive": "archive records",
              "transcript": "the show's own transcript", "video": "the broadcast itself", "book": "a book",
              "primary": "the original document", "testimony": "sworn testimony", "press": "a press report"}


def spoken_source(source: dict[str, Any]) -> str:
    """How a narrator names this source aloud: by kind, publisher and year - never a title that is a web
    address, a file name or a case number."""
    kind = str(source.get("source_type") or source.get("type") or "").lower().replace(" ", "_")
    words = KIND_WORDS.get(kind) or next((v for k, v in KIND_WORDS.items() if k in kind), "a record")
    pub = speakable(str(source.get("publisher") or "")).strip()
    if pub and (unspeakable(str(source.get("publisher") or "")) or len(pub.split()) > 6):
        pub = ""
    year = ""
    m = re.search(r"\b(19|20)\d{2}\b", str(source.get("date") or ""))
    if m:
        year = m.group(0)
    if pub and words.startswith(("a ", "an ")):
        words = f"a {year + ' ' if year else ''}{pub} {words.split()[-1]}"
    elif pub:
        words = f"{words} from {pub}{' (' + year + ')' if year else ''}"
    elif year:
        words = f"{words} from {year}"
    return words
