# Editorial rules, and how the program enforces them

These come from truth-vlog's roadmap and investigator charter, plus the lessons in
Nimrod's Tower about trusting local AI. "Blocks" means you can't press Approve until
it's fixed.

| Rule | Enforced by |
|------|-------------|
| Knowledge Fight is a research index, never evidence. Credit it on every video. | Research and Script **block** a claim or scene backed only by `kf_index` sources. The credits card and description always carry the credit line with the KF episode numbers. |
| Every on-screen claim resolves to a primary source in the database. | Script **blocks** a scene that states facts without source IDs, or uses a source not linked to its claims, or a source ID that doesn't exist. |
| The AI never originates a citation or a quote. | Quotes are only kept if they appear word for word in a saved copy of the source. Script **blocks** any quoted text in narration that doesn't match a verified quote. Quote cards are drawn as text, never generated. |
| AI never makes evidence: no fake documents, quotes or footage of real events. | Image prompts always add "no text, no logos, no recognizable real people". Real documents only appear as "receipt" shots from screenshots you saved yourself. |
| Label AI imagery. | Every AI picture and clip is stamped "AI illustration". Uploads are marked as containing altered/synthetic content. |
| Never draw real people. | Storyboard **blocks** a picture prompt containing any name from the people table. |
| Victims: courts and documents only. | Sandy Hook arcs (and any arc whose notes say "courts only") get `courts_only`, `no_names`, `no_footage` rules. Research **blocks** such a claim without a court or government source; the rules are passed to the script writer and shown as warnings at every stage. |
| Say "unverified" or "contested" plainly. | Research warns; the script writer is told the verdict for each claim. |
| Never mock the believer; aim at the people who sold it. | In the script writer's instructions; you approve the script. |
| Every video answers: what was claimed, what the record says, who benefited, what it did to people. | Script **blocks** if any of the four isn't marked on a scene. |
| Plain 6th-grade language. | Script shows the reading level and warns above grade 8. |
| Corrections happen in public. | Description and pinned comment invite corrections. |
| Same-model self-critique isn't verification; a human approves. | Checks are plain text matching, not AI opinions. Nothing advances without your Approve. |
| Failures surface; nothing is silently swapped. | A failed job pauses the queue. No stock-photo or canned-audio fallbacks. Every approval and failure is kept in the stage history. |
