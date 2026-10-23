# Editorial rules, and how the program enforces them

These come from truth-vlog's roadmap and investigator charter, plus the lessons in
Nimrod's Tower about trusting local AI. "Blocks" means you can't press Approve until
it's fixed.

| Rule | Enforced by |
|------|-------------|
| Knowledge Fight is a research index, never evidence. Credit it on every video. | Research and Script **block** a claim or scene backed only by `kf_index` sources. The credits card and description always carry the credit line with the KF episode numbers. |
| Every on-screen claim resolves to a primary source in the database. | Research **blocks** a claim whose ticked evidence has no primary source (court, government, news, academic...). Script **blocks** a scene that states facts without source IDs, uses a source you didn't tick, or a source ID that doesn't exist. Quote numbers (E14) written where a source goes are read as that quote and its source. |
| The research agents never invent a link. | Links only come from search results, public archives or the database. A found page is kept only if at least one quote from it appears word for word in the saved copy; every link gets a Wayback Machine copy. Story beats that name evidence IDs not in the research are stripped. |
| Be a polite robot. | The agents say who they are, obey robots.txt, wait between requests to the same site, cache every page, and keep under CourtListener's daily limit. |
| The AI never originates a citation or a quote. | Quotes are only kept if they appear word for word in a saved copy of the source. Script **blocks** any quoted text in narration that doesn't match a verified quote. Quote cards are drawn as text, never generated. |
| AI never makes evidence: no fake documents, quotes or footage of real events. | Image prompts always add "no text, no logos, no recognizable real people". Real documents only appear as "receipt" shots from screenshots you saved yourself. |
| Label AI imagery. | Every AI picture and clip is stamped "AI illustration". Uploads are marked as containing altered/synthetic content. |
| Real people appear only as clearly-cartoon caricatures of the public figures who sold the lie (changed 2026-10-23 at Dave's request; was "never draw real people"). | Storyboard **blocks** any picture prompt that names a real person. Caricatures are drawn from a written design you approve in the Cast window (looks only, never the name), only in cartoon satire styles, only of people the database records as saying, spreading, platforming or profiting from the video's claims, never on careful topics, and only in scenes that cite a source about what they did. Each gets a "Caricature: name" caption plus the AI label, and the description says they're satire. No speech bubbles: only verified quotes, as quote cards. Not legal advice; see the report "Creative styles and studio polish". |
| Never draw victims, families, believers or private people. | They can't be added to the Cast; careful topics switch caricatures and humor off. |
| Victims: courts and documents only. | Sandy Hook arcs (and any arc whose notes say "courts only") get `courts_only`, `no_names`, `no_footage` rules. Research **blocks** such a claim without a court or government source; the rules are passed to the script writer and shown as warnings at every stage. |
| Say "unverified" or "contested" plainly. | Research warns; the script writer is told the verdict for each claim. |
| Never mock the believer; aim at the people who sold it. | In the story and script writers' instructions ("anyone can be fooled by this, that's why it works"); humor is a 0-3 setting and is forced to 0 on careful topics; you approve the script. |
| Teach the trick, not just the fact; show the myth once. | Stories name 1-2 manipulation techniques; the script has a "tell" scene (Owlbert's Tell card) and a "toolkit" scene; the writer opens and closes on the fact and shows the myth once, as a claim someone sold. |
| The video is as long as you asked. | Script **blocks** below 80% of the target length (Make it longer rewrites only the short scenes); the storyboard plans enough shots to cover the narration; the render warns if the video comes out short. |
| Every video answers: what was claimed, what the record says, who benefited, what it did to people. | Script **blocks** if any of the four isn't marked on a scene. |
| Plain 6th-grade language. | Script shows the reading level and warns above grade 8. |
| Corrections happen in public. | Description and pinned comment invite corrections. |
| Same-model self-critique isn't verification; a human approves. | Checks are plain text matching, not AI opinions. Nothing advances without your Approve. |
| Failures surface; nothing is silently swapped. | A failed job pauses the queue. No stock-photo or canned-audio fallbacks. Every approval and failure is kept in the stage history. |
