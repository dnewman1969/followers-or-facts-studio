# Music

## How it works now

The script writer gives every scene a **MUSIC** line, for example:

```
### MUSIC
mood: tense | energy: 3 | change: crossfade | drop before: "Here is exactly what he said"
```

- **mood** follows the scene's job, never the verdict: intro curious · claim tense · record
  investigative · benefit warm · harm somber (or silence) · tell playful · toolkit encouraging ·
  verdict resolved · outro theme.
- **energy** 1 (barely there) to 5 (big). Never above 3 under the evidence.
- **change**: `continue` (same music carries on), `crossfade` (new section), `sting` (a musical hit on
  the words in `sting at`, then new music), `hard_cut`, `silence`.
- **drop before**: the music stops just before these words so Owlbert's voice arrives alone, then comes
  back after the sentence. The verdict scene always has one: no music under the verdict.

You can edit these lines in script.md like anything else. The program checks them (no playful music over
harm or on careful topics, at most 6 stings, quoted words must really be in the narration) and fixes or
drops what breaks the rules.

**Make music** (Production page) then makes one piece for each change, with ACE-Step, in the genre you
pick in the box next to it (25 kinds: documentary, lo-fi, jazz, noir, ragtime, 1920s hot jazz, swing,
newsreel, synthwave, bluegrass, funk, bossa nova, spy, western, chiptune, celtic, tango and more), or
"to suit the style". Every piece in a video shares one tempo and related keys (D minor / F major) so the
cross-fades sound like one score. The outro theme is made once and reused in every video, for branding.
Pieces that didn't change are kept when you make music again.

On the timeline each piece is a separate bar on **A2 Music** (with its mood in the name) and the stings,
whooshes and pops are on **A3 Effects**. Drag, trim, delete or change the level of any of them.

## Your own tracks

Pick **Music: from my library folder** and the program picks a track for each mood from
`F:\AI\fof-data\music-library`. Rules:

- Every track needs a note next to it, `song.txt` or `song.license.json`, saying where it came from and its
  licence. Tracks marked non-commercial, no-derivatives or "download only" are refused.
- Put the mood in the file or folder name (`tense\`, `playful-pizzicato.mp3`...) so it matches the right scenes.

## Free and out-of-copyright music (US, as of 2026)

- **Songs** published in **1930 or earlier** are free to perform: "I Got Rhythm", "Georgia on My Mind",
  "Singin' in the Rain", "Boléro", "Rhapsody in Blue", "The Entertainer", Sousa marches, all the classical
  repertoire. The list the program knows is in `fofstudio/musicbook.py` (PUBLIC_DOMAIN).
- **Recordings** are a separate copyright. Only recordings published in **1925 or earlier** are free
  (Gershwin's own 1924 "Rhapsody in Blue", Bessie Smith's 1925 "St. Louis Blues"...). A modern recording
  of a free song is NOT free.
- Every January 1 another year joins (2027: 1931 songs, 1926 recordings).
- Where to get them: YouTube Audio Library (never claimed by Content ID), Musopen (check each recording),
  Library of Congress National Jukebox (before 1923), Free Music Archive (CC BY, CC BY-SA or CC0 only),
  Incompetech (CC BY 4.0, needs a credit line), Mutopia (sheet music and MIDI: Public Domain or CC BY files).
- **Content ID** still sometimes claims old recordings through registered remasters, and some Pixabay tracks
  are registered. Keep the licence note; it's your proof when you dispute a claim.

## Coming next

- Our own new recordings of public-domain pieces from public-domain MIDI files, played by FluidSynth
  (LGPL, run as a separate program) with a free SoundFont (FluidR3_GM or MuseScore_General, MIT).
- Snapping cue changes to the beat (librosa).
