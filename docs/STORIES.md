# Story types and writers

## Scan data for stories (added 2026-10-30)

At the top of the **Stories** page, **Scan data for stories** has the local AI read all the ticked research
and list every video it could make, with how long each would be:

- **Info clip**: one striking, sourced fact or one claim taken apart, 30-90 seconds (a YouTube Short).
- **Short story**: one claim, person or thread told properly, about 2-10 minutes.
- **Long story**: several claims or the whole saga, 10 minutes or more (a big one can also be a book).

Each idea lists the claims and evidence it uses (only real IDs: an idea that uses nothing from the research
is dropped). The length is worked out from that material with the Script page's length formula, so a
"long story" with only a few minutes of material is listed as a short story (never padded). Pick an idea,
choose **Make it as** (2 stories, 2 info clips or 1 book) and the story type and writer, then **Create**.
Use one of the two stories (or clips) for the script as usual.

On the **Stories** page, next to the style and length:

- **Story type**: how the story is built (its beats in order). "Let the AI pick" gives the three
  story options three different types, so you can compare.
- **Writer**: the *writing style* of the script (sentence rhythm, how it opens, how it uses numbers
  and humor). It's not a speaking voice: Owlbert still sounds like Owlbert. "Let the AI pick" chooses
  one that suits each story type.

Every type keeps the debunking rules: open on a true fact, state the claim once with a warning, name
one trick, give one question to ask next time, end on the fact. Careful topics (real victims or deaths)
only offer the sober types (Fact Sandwich, Patient Zero, Follow the Money, Quick Hit, History Rhymes) and
hide the playful writers.

| Story type | In one line |
|---|---|
| The Fact Sandwich | The classic debunk; the safe default |
| Patient Zero | The biography of a rumor: where it started and how it spread |
| Who Started This? | A mystery: clues rule suspects out |
| Follow the Money | A scam exposé built on the money trail |
| Rise and Fall of a Grifter | The seller's life story |
| The Long Con | The scam told in the stages of a con trick |
| The Trial | The claim on trial; evidence decides, not airtime |
| Owlbert's Lab | Turn the claim into a test; what real experiments found |
| How the Trick Works | Teach the trick on something silly, then reveal the claim uses it |
| The Turn | A gentle twist of perspective, for honest mistakes |
| The Rabbit Hole and Back | A made-up composite believer goes in and comes back |
| Quick Hit | And-But-Therefore, for short videos |
| History Rhymes | An old hoax next to its modern version |

Writers: Night-Shift Detective, Investigator, Stargazer, Explainer, Campfire Teller, Gentle Satirist,
Case-File Podcaster, Advocate for the Evidence, Chronicler, Picture-Book Narrator, Play-by-Play Caller,
Field Naturalist, Porch Humorist (Twain-style), Socratic Professor (Owlbert's natural voice) and Wire
Bulletin (just the facts). They're described by their traits only: no living writer is named or copied.
The beat sheets are in `fofstudio/storytypes.py`; the writer styles in `fofstudio/data/writers.json`.

# Genre, director and length (Script page)

1. **Genre**: the kind of video. It changes the tone and pacing of the script, the look of the pictures
   (lighting, palette, framing) and, if the music is set to "to suit the style", the music too. 16 genres:
   Explainer Documentary (default), Nature Documentary, Detective Mystery, Film Noir, Thriller, Investigative
   News Magazine, Courtroom Drama, Heist/Caper, Spy, Science Fiction, Adventure Quest, Comedy/Satire,
   Mockumentary, Historical Epic, Fairy Tale/Fable, Animated Family Film. Careful topics only offer
   Explainer, News Magazine, Courtroom and Historical.
2. **Director**: the way it's shot: framing, camera moves, how long shots hold, transitions, music and silence.
   18 styles, each shown as "Suspense Engine (inspired by Hitchcock)", "Cold Symmetry (inspired by Kubrick)",
   "Contested Reenactment (inspired by Errol Morris)" and so on. The AI only ever gets the style's traits,
   never the director's name, and nothing in a video claims any connection to a real director. Playful
   styles aren't offered for careful topics.
3. **Scan the story**: the local AI reads the chosen story and the ticked evidence, judges how much
   explaining each claim needs, and the program works out the honest length (no padding): about 75 s per
   claim plus its sources, a minute per trick taught, time for the timeline and people, plus the opening,
   recap and sign-off. It shows the best length and a range, what to cut if you go shorter, what real material
   to add if you go longer, and says when a story suits a Short (3 minutes or less) or a series. If it's
   just under 8 minutes with real material to add, it mentions that YouTube's mid-video ads start at 8:00,
   but never stretches it for you.
4. Set the **length**, then **Produce script**.

# How big is the story? (Stories page)

Before the story writer starts, the local AI reads all the ticked evidence and judges how much explaining
each claim needs and how many timeline events, people and groups, and separate threads there are. The
program does the arithmetic (`stages/storysize.py`):

- **Video length**: the Script page's length formula, with no 20-minute cap.
- **Book pages**: 450 words per claim + 220 per source + 100 per quote + 120 per person or group + 100 per
  timeline event, at 300 words a page.
- **Short** if it's 3 minutes or less; **one video** up to 20 minutes with at most 6 claims and 2 threads;
  otherwise a **series** of about 15-minute parts; a **book** when there's enough for `[book] min_pages`
  pages (45 by default) and at least 3 claims or 15 sources.

The verdict shows above the three stories. A book-sized subject still gets its three video stories.

# The book (Stories page → Write the book)

The whole story with references, as a 6 × 9 inch PDF (`<episode>/book/book.pdf`): where it started, who
was involved, how it spread, what the record shows claim by claim, who profited, the damage, how the
deception worked, and the verdict. It uses only the evidence ticked on the Research page, so tick
everything the book should use (usually more than a video needs).

How "nothing made up" is enforced (plain text checks, `stages/book.py`):

- The chapter plan can only point at claim and evidence IDs that exist; every ticked item is used.
- Each chapter is written from its own material only: the ticked quotes and source write-ups, and passages
  from the saved copies of those sources. Every paragraph must cite what it relies on.
- The AI never types a quote: it names the quote's E-number and the program prints the verified,
  word-for-word text. Words the AI put in quotation marks must be found word for word in the sources.
- Every number and year must appear in the material that paragraph cites.
- It may only say someone lied or meant to deceive when the cited material (a court finding, an official
  record, their own words) says so; otherwise it sets out the claim and the record.
- A chapter that fails gets one rewrite with the problems listed; paragraphs that still fail are removed.
  Names that aren't in the material are flagged. Both are listed in `book/review.md` ("What to check").
- Careful topics: "courts only" claims use only court and government sources.

Until you press **Approve the book**, every page says DRAFT. The book is saved chapter by chapter, so a
stopped job carries on where it left off; "Write it again from the start" throws the chapters away.
Changing the ticked evidence also starts it again.

Before selling: read every page, and think about a legal read for anything that accuses named people.
In the US, text written by AI isn't protected by copyright on its own; your own editing, additions and
the selection and arrangement can be. If you register it, the Copyright Office asks you to say which parts
were AI-written. (Not legal advice.)
