# Test run: one video from research to upload, with checkpoints

Written 2026-11-02 for v0.11.0. The goal is to find exactly where the story stops being the chosen story, where
it starts repeating itself, and where the pictures go dull. After each checkpoint, press **Send to Claude...**
(bottom of the left-hand list) and attach the zip it makes in the chat. The zip holds the production diary,
the script, the plans and the logs; no pictures, clips or sound, so it stays small. A screenshot of the page
helps too.

Every step now writes the **production diary** (`<episode>\diary\diary.md`). It says what the step made, its
checks, what it said while working, and a **story thread** score for every scene and every shot (0 means it has
drifted away from the chosen story). That's what lets us see where cohesion is lost.

## 0. Before you start

1. Run **Update Studio.cmd**. The title bar should say **0.11.0** or later.
2. Start a **new video** (Database page). Old videos keep their old scripts and pictures, so they won't show
   the changes. Pick a subject you know well, so you can tell when the story goes wrong.
3. Settings: leave the new defaults. If you saved settings before, the Studio updates the old repetition and
   guide settings by itself.

## 1. Research

1. Database → pick the subject → **OK — research this →** → **Start research**.
2. When it finishes, tick the evidence you want (or **Tick them for me**). **Deep dive on weak claims** if
   some claims are weak.
3. Look at: do the claims and sources make sense for the story you have in mind?
4. Approve.

Checkpoint A (optional): **Send to Claude...** if research looks thin or off-topic.

## 2. Stories

1. **Create 2 stories** (or **Scan data for stories** → **Create**).
2. Read both loglines. A good one says who wanted what, what stood in the way, and the question the video
   answers. Each beat should be a new step in the story, not the same fact twice.
3. **Use this story** on the better one (or **Rewrite with notes...**).

**Checkpoint B: Send to Claude...** This shows whether the story itself is good before any script is written.

## 3. Script

1. **Produce script**. It takes a while: the writer works scene by scene.
2. Read it out loud (or at least in your head, as Owlbert):
   - Does it sound like someone telling a story, or like a list of sources?
   - Does any line repeat an earlier one? ("No one stopped him" twice is a repeat.)
   - Does it read out anything like a web address, a file name or a case number? (It shouldn't now.)
3. If the checks at the top mention repeats, press **Fix repeats**.
4. Approve when you're happy (or after Checkpoint C).

**Checkpoint C: Send to Claude...** The most important one. The diary shows each scene's story thread score,
the phrases used three or more times, the scenes that say the same thing, and anything read aloud that
shouldn't be.

## 4. Storyboard

1. Optional: **Unreal guides...** → **Make guides with Unreal** (a few minutes; Unreal opens and closes by
   itself).
2. Pick a style. For this test, avoid the murky retro looks (Analog Camcorder Tape, Early Live-TV Kinescope):
   they're hard to make appealing. Something bright and illustrated tests the new picture work best.
3. **Make pictures**.
4. Look at: are the pictures bright and colourful, with one clear subject? Do they show what Owlbert is saying
   at that moment? No numbers or labels painted in, no stray owls?
5. **Crew & sets...** shows what each crew member did, the sets the production designer dressed (you can edit
   them), and every shot's card: the words it covers, the director's plan, and what was painted.
6. **Remake** any bad shot; approve.

**Checkpoint D: Send to Claude...** The diary has every shot with what it covers, what was painted, its story
thread score and the picture check's problems.

## 5. Video

1. **1. Write scene instructions**, then **2. Make the clips** (the slow part: leave it overnight for many
   clips).
2. **▶ Watch** a few. Look at: does the motion fit the moment? Does anything melt or morph?
3. Approve clips (or **Make again**).

**Checkpoint E: Send to Claude...** if clips look wrong, with a screenshot of a bad one.

## 6. Production

1. **1. Make speech track** → **2. Make music** → **3. Assemble timeline** → **4. Render final video**.
2. Watch the whole video once, start to finish. Note the time of anything that feels off (a picture that
   doesn't match the words, a long hold, a repeat).

**Checkpoint F: Send to Claude...** with your notes and their times ("2:14 the picture is a desk but he's talking
about a bill").

## 7. Publish

1. **Write it up**. Check the title, description and tags; **Save my edits**.
2. **Upload on YouTube** (opens YouTube in your browser) only when you're happy.

**Checkpoint G: Send to Claude...** if anything in the write-up is off.

## What I look for in what you send

- Where the story thread score drops: the step where the story was lost (story → script → pictures).
- Repeated phrases and scenes that say the same thing: the script writer and its checks.
- What each step said while working (the diary's "last lines"): AI answers that failed or were cut short.
- The crew log: what each crew member decided and why.

## Continuing the conversation with Claude

- Easiest: come back to this same chat in the Claude app. It keeps the whole history and the working copy of
  the Studio; when it gets very long it's summarized automatically, and the summary keeps the essentials.
- If you start a new chat (or this one is gone), say: "Continue developing Followers or Facts Studio
  (github.com/dnewman1969/followers-or-facts-studio). Read PROJECT-LOG.md and AGENTS.md first." The project log
  holds every change and decision, and the research reports are in the project's docs.
- Either way, attach the latest **Send to Claude** zip and say which checkpoint it's from.
