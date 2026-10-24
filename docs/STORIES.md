# Story types and writers

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
