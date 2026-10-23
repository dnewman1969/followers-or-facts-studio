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

| Move | When the planner uses it | What he does |
|---|---|---|
| Fly in | Start of the first scene | Flies in from the far side, flaps, flares his wings and lands in the corner |
| Point at the evidence | Claim, record, harm and benefit scenes (at most every 25 s) | Looks toward the picture and raises his wing at it |
| Hat trick | The "tell" scene (the trick's name on a card) and the "toolkit" scene (a light bulb) | Waves his wing, his cap pops off, turns over, and the card rises out of it with sparkles; the picture dims while it's held up |
| Wing flourish | The verdict | Spreads both wings and gives a little hop |
| Fly off | End of the last scene | Crouches, spreads his wings and flies off the near edge |

Rules (`fofstudio/bits.py`): at most one big move a scene, big moves at least 20 s apart, at most
two hat tricks a video, never two moves at once. Careful topics (deaths, victims, court-only
stories) get no hat trick and no flourish. Humor 0 drops the flourish. His beak keeps moving with
his words while he flies, and he hides from the corner while a move plays.

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
