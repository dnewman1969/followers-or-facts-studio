# Professor Owlbert McFinnegan

Owlbert narrates every video and appears throughout it:

- **Intro bumper** (6 s): he slides in beside "Followers or Facts" and the episode title.
- **Presenter in the corner** while he talks: his beak moves with his words and he blinks.
  On the Production page the **V2 Owlbert** track shows when he's on screen. Drag or trim
  those bars, delete one, or use **Add Owlbert at playhead**.
- **Outro bumper** (8 s): "Follow the facts", with the note that every source is in the description.

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

- More poses (pointing, thinking) made with Qwen-Image-Edit (Apache-2.0) from the profile picture.
- A character LoRA so Owlbert can appear inside the AI scenes themselves.
