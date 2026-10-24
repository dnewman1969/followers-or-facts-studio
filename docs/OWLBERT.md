# Professor Owlbert McFinnegan

Owlbert narrates every video and appears throughout it:

- **Intro bumper** (6 s): he slides in beside "Followers or Facts" and the episode title.
- **Presenter in the corner** while he talks: his beak moves with his words and he blinks.
  On the Production page the **V2 Owlbert** track shows when he's on screen. Drag or trim
  those bars, delete one, or use **Add Owlbert at playhead**.
- **Outro bumper** (8 s): "Follow the facts", with the note that every source is in the description.
- **Moves** (V3 Moves track on the Production page): he flies in, points at the evidence, pulls the
  trick out of his hat, gives the verdict a wing flourish, and flies off. See below.

## His moves

Owlbert is cut into parts (`fofstudio/rig.py`): body, two folded wings, cap, tassel. The program
also draws what the picture doesn't show: spread wings for flying, the top of his head under the
cap, the inside of the cap, and the props. He is never flipped left-to-right, so the tassel always
hangs on the viewer's right.

The script writer directs him: every scene has an **OWLBERT** section, one move per line, tied to
the words he's saying when it happens:

```
### OWLBERT
- hat_trick document at "the original agency caption"
- glasses at "It's dated May 2009"
```

| Move | Size | What he does | Where it belongs |
|---|---|---|---|
| fly_in | big | Flies in from the far side and lands in the corner | First scene only |
| fly_out | big | Crouches, spreads his wings and flies off | Last scene only |
| point | small | Looks at the picture and raises his wing at it | While evidence is on screen |
| glasses | small | Pushes up his spectacles | Before reading a quote closely |
| think | small | Wing to his chin, a slow rock | Before a question |
| hat_tip | small | Lifts his cap a little | Hello, or thanks to a source |
| solemn | small | Cap off and held to his chest | Harm to real people |
| surprised | big | A little jump | A number or contradiction (about the trick or the seller) |
| flourish | small | Spreads both wings with a hop | Intro title, toolkit |
| swoop | big | Loops across the screen | A big section change |
| hat_trick + document / card / bulb / magnifier | big | Cap off, turned over, pulls the thing out with sparkles while the picture dims | document: the source he's about to quote (shows its title and date); card: the trick's name (tell); bulb: the question (toolkit) |
| stamp | big | Brings his wing down as a red verdict stamp (FALSE, UNPROVEN...) lands | Verdict scene, on the verdict word |

The program checks every direction (`bits.plan_directed`) and drops any that break the rules from the
research: at most one big and two small moves a scene, small moves 4 s apart, never two at once, no
hat trick two scenes running (at most three a video), at most two swoops, one stamp; in a harm scene only
point, glasses or solemn; careful topics and humor 0 get nothing playful, and the hat shows a document,
never a joke card. Scripts without OWLBERT lines get moves picked by scene role, as before.

Each move has its own sound on **A3 Effects**: a whoosh and wing flutter for flying, a pop and sparkle
for the hat, a thud for the stamp.

On the Production page the moves are pink bars on **V3 Moves**: drag one to move it, press Delete
to remove it, or pick a move under the inspector and press **Add move** to put one at the playhead.
Settings → owl → `moves` switches them all off.

## How he talks

He's a cut-out puppet made from `brand/owlbert-profile.png`, not an AI video model, so he
always looks exactly like himself and it costs no GPU time. The program cuts his beak in two
and drops the lower half by different amounts for different mouth shapes, and draws eyelids
for blinks (`fofstudio/owl.py`).

The mouth shapes are timed by **Rhubarb Lip Sync** (MIT licence, free). `Update Studio.cmd`
and `setup.ps1` download it into `F:\AI\fof-data\models\rhubarb` and set
Settings → owl → `rhubarb`. If Rhubarb isn't there, he still talks, but his beak follows
how loud he is instead of the actual sounds, and the progress line says so.

AI lip-sync models (InfiniteTalk, Wan2.2-S2V and others) were looked at and left out: they
need far more than 12 GB, some have licences that rule out a monetized channel, and none
has been shown working on a beak.

## His voice

A blend of two free Kokoro voices, a touch slower, a semitone higher:

```
[owl]
voice = "bm_george:0.7,bm_fable:0.3"
speed = 0.93
pitch_semitones = 1.0
```

Change these in Settings and press **Make speech track** again. Only lines whose voice
settings or words changed are re-recorded. Try `bm_fable` alone, or `bm_lewis`, or move
the pitch between 0 and 2 to find his voice. Listen on a phone speaker too.

Want a voice of your own instead? Chatterbox (MIT) can clone a voice from a 5–20 second
clip, but only your own voice or a consenting person's, with a rights record. See
`fofstudio/engines/tts.py`.

## Coming later

- More props from the technique catalogue (a cherry for cherry picking, a mask for the fake expert),
  a thinking pose, and a verdict stamp.
- Hand-finished spread-wing drawings (Qwen-Image-Edit-2511, Apache-2.0) to replace the drawn ones.
- A character LoRA so Owlbert can appear inside the AI scenes themselves.
