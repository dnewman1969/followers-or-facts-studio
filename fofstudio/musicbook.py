"""Music types, moods and the public-domain song list.

The music stage makes one piece of music ("cue") for each run of scenes that share a mood, as the
script's MUSIC lines say, with ACE-Step 1.5 (MIT: the music is ours to use on a monetized channel).
A cue's description = the genre's instruments + the mood + how energetic + the video's tempo and key,
so every cue in a video belongs together and the cross-fades sound like one score.

PUBLIC_DOMAIN lists famous pieces that are out of copyright in the US (as of 2026: songs published
in 1930 or earlier, recordings published in 1925 or earlier - every January 1 another year joins).
A song being free doesn't make a modern recording of it free: use the old recording itself, or make
our own recording from a public-domain MIDI or score file (see stages/music.py "own recording").
"""

from __future__ import annotations

from dataclasses import dataclass

# the year cut-offs, as of January 1 2026 (Duke Center for the Study of the Public Domain)
PD_SONGS_UP_TO = 1930
PD_RECORDINGS_UP_TO = 1925


@dataclass(frozen=True)
class Genre:
    key: str
    name: str
    tags: str            # instruments and feel, for ACE-Step
    bpm: int


GENRES: dict[str, Genre] = {g.key: g for g in [
    Genre("documentary", "Documentary (piano and strings)", "documentary underscore, felt piano, warm strings, soft pads", 84),
    Genre("orchestral", "Cinematic orchestra", "cinematic orchestral, string ostinato, french horns, soft timpani", 90),
    Genre("lofi", "Lo-fi hip hop", "lo-fi hip hop, mellow Rhodes piano, dusty vinyl crackle, muted boom-bap drums, warm bass", 78),
    Genre("jazz", "Cool jazz trio", "cool jazz trio, brushed drums, walking upright bass, piano comping, smoky", 112),
    Genre("noir", "Mystery noir", "noir jazz, muted trumpet, double bass, vibraphone, brushed snare", 76),
    Genre("ragtime", "Ragtime piano (1910s)", "ragtime, solo upright honky-tonk piano, syncopated stride left hand, 1910s", 100),
    Genre("twenties", "1920s hot jazz", "1920s hot jazz, dixieland, clarinet, trumpet, trombone, banjo, tuba, Charleston rhythm",
          150),
    Genre("swing", "Big band swing", "1940s big band swing, saxophone section, muted brass, upright bass, ride cymbal", 132),
    Genre("newsreel", "Old newsreel", "1940s newsreel, brass fanfare, snare drum, march, vintage mono radio", 110),
    Genre("synthwave", "Synthwave (80s)", "synthwave, retro 80s analog synth arpeggio, gated reverb drums, pulsing bass", 100),
    Genre("ambient", "Ambient electronic", "ambient electronic, evolving pads, soft pulses, glassy textures", 80),
    Genre("newsbed", "TV news bed", "news broadcast bed, driving synth pulse, ticking percussion, corporate", 118),
    Genre("folk", "Acoustic folk", "acoustic folk, fingerpicked guitar, upright bass, soft harmonica", 96),
    Genre("bluegrass", "Bluegrass", "bluegrass, banjo, fiddle, mandolin, upright bass", 120),
    Genre("blues", "Delta blues", "acoustic delta blues, slide guitar, foot stomps, harmonica", 80),
    Genre("funk", "Funk", "70s funk, clavinet, wah guitar, slap bass, tight drums", 104),
    Genre("bossa", "Bossa nova", "bossa nova, nylon guitar, soft shaker, upright bass, flute", 120),
    Genre("chamber", "Classical chamber", "classical chamber music, string quartet, harpsichord", 92),
    Genre("pizzicato", "Comedy pizzicato", "comedic playful pizzicato strings, bassoon, glockenspiel, cartoon, quirky", 110),
    Genre("spy", "60s spy", "1960s spy theme, surf guitar, bongos, brass stabs, organ", 112),
    Genre("western", "Spaghetti western", "spaghetti western, twangy guitar, whistling melody, trumpet, castanets", 96),
    Genre("chiptune", "Chiptune (8-bit)", "chiptune, 8-bit video game, square wave lead, arpeggios", 128),
    Genre("celtic", "Celtic", "celtic folk, tin whistle, fiddle, bodhran, harp", 104),
    Genre("tango", "Tango", "tango, bandoneon, violin, piano, staccato rhythm", 116),
    Genre("triphop", "Trip hop", "trip hop, dusty breakbeat, deep bass, moody piano, vinyl", 86),
]}

# what each style's videos sound like unless you pick a genre
STYLE_GENRE = {"documentary": "documentary", "classroom": "folk", "cartoon": "pizzicato", "satire": "spy",
               "newscast": "newsbed", "truecrime": "ambient", "courtroom": "chamber", "noir": "noir",
               "comic": "orchestral", "papercut": "folk", "infomercial": "synthwave", "heist": "spy"}

# the mood words added to the genre (the script's MUSIC lines pick a mood for each scene)
MOOD_TAGS = {
    "curious": "curious, intriguing, light and inquisitive",
    "tense": "tense, suspense, minor key, low drone underneath, sparse",
    "investigative": "neutral, investigative, steady, sparse, no drums",
    "warm": "warm, gentle, measured, major key",
    "somber": "somber, slow, reflective, sustained, minor key, very sparse",
    "playful": "playful, bouncy, light, a wink",
    "encouraging": "encouraging, uplifting, steady, major key",
    "resolved": "resolved, calm, confident, gentle, major key",
    "theme": "friendly, bright, catchy theme, clean ending",
}
MINOR_MOODS = {"tense", "somber", "investigative", "curious"}
ENERGY_TAGS = {1: "very soft, minimal", 2: "soft, sparse arrangement", 3: "moderate", 4: "lively", 5: "energetic, full"}


def genre_for(style_key: str, chosen: str | None = None) -> Genre:
    if chosen and chosen in GENRES:
        return GENRES[chosen]
    return GENRES[STYLE_GENRE.get(style_key, "documentary")]


def cue_tags(genre: Genre, mood: str, energy: int, key_minor: str = "D minor", key_major: str = "F major") -> str:
    """The description ACE-Step gets for one cue. Every cue of a video uses the same tempo, and keys
    that are relatives (D minor / F major), so cues blend into each other."""
    key = key_minor if mood in MINOR_MOODS else key_major
    return ", ".join([genre.tags, MOOD_TAGS.get(mood, MOOD_TAGS["investigative"]), ENERGY_TAGS.get(energy, "moderate"),
                      f"{genre.bpm} bpm", key, "instrumental, no vocals, background music under narration, "
                      "leaves room for a voice"])


# Famous pieces out of copyright in the US. "recording" = an original recording that is free too.
PUBLIC_DOMAIN: list[dict[str, object]] = [
    {"title": "The Entertainer", "by": "Scott Joplin", "year": 1902, "genre": "ragtime"},
    {"title": "Maple Leaf Rag", "by": "Scott Joplin", "year": 1899, "genre": "ragtime"},
    {"title": "Rhapsody in Blue", "by": "George Gershwin", "year": 1924, "genre": "orchestral",
     "recording": "Gershwin's own 1924 recording with Paul Whiteman (free since 2025)"},
    {"title": "An American in Paris", "by": "George Gershwin", "year": 1929, "genre": "orchestral"},
    {"title": "Boléro", "by": "Maurice Ravel", "year": 1929, "genre": "orchestral"},
    {"title": "I Got Rhythm", "by": "George & Ira Gershwin", "year": 1930, "genre": "swing"},
    {"title": "Georgia on My Mind", "by": "Hoagy Carmichael & Stuart Gorrell", "year": 1930, "genre": "jazz"},
    {"title": "On the Sunny Side of the Street", "by": "Jimmy McHugh & Dorothy Fields", "year": 1930, "genre": "swing"},
    {"title": "Dream a Little Dream of Me", "by": "Andre, Schwandt & Kahn", "year": 1930, "genre": "jazz"},
    {"title": "Body and Soul", "by": "Johnny Green", "year": 1930, "genre": "jazz"},
    {"title": "Singin' in the Rain", "by": "Nacio Herb Brown & Arthur Freed", "year": 1929, "genre": "twenties"},
    {"title": "Ain't Misbehavin'", "by": "Fats Waller, Harry Brooks & Andy Razaf", "year": 1929, "genre": "twenties"},
    {"title": "Happy Days Are Here Again", "by": "Milton Ager & Jack Yellen", "year": 1929, "genre": "twenties"},
    {"title": "Tiptoe Through the Tulips", "by": "Joe Burke & Al Dubin", "year": 1929, "genre": "twenties"},
    {"title": "Mack the Knife (original German)", "by": "Kurt Weill & Bertolt Brecht", "year": 1928, "genre": "noir"},
    {"title": "When You're Smiling", "by": "Fisher, Goodwin & Shay", "year": 1928, "genre": "swing"},
    {"title": "Charleston", "by": "James P. Johnson", "year": 1923, "genre": "twenties",
     "recording": "James P. Johnson's 1923 recording (free since 2024)"},
    {"title": "Yes! We Have No Bananas", "by": "Frank Silver & Irving Cohn", "year": 1923, "genre": "twenties",
     "recording": "1923 recordings (free since 2024)"},
    {"title": "Sweet Georgia Brown", "by": "Bernie, Pinkard & Casey", "year": 1925, "genre": "twenties",
     "recording": "Ben Bernie's 1925 recording (free since 2026)"},
    {"title": "St. Louis Blues", "by": "W. C. Handy", "year": 1914, "genre": "blues",
     "recording": "Bessie Smith with Louis Armstrong, 1925 (free since 2026)"},
    {"title": "Fascinating Rhythm", "by": "George & Ira Gershwin", "year": 1924, "genre": "twenties",
     "recording": "Paul Whiteman's 1925 recording (free since 2026)"},
    {"title": "It Had to Be You", "by": "Isham Jones & Gus Kahn", "year": 1924, "genre": "swing",
     "recording": "Isham Jones and Marion Harris, 1924 (free since 2025)"},
    {"title": "In the Hall of the Mountain King", "by": "Edvard Grieg", "year": 1876, "genre": "orchestral"},
    {"title": "Gymnopédie No. 1", "by": "Erik Satie", "year": 1888, "genre": "documentary"},
    {"title": "Clair de Lune", "by": "Claude Debussy", "year": 1905, "genre": "documentary"},
    {"title": "Für Elise", "by": "Ludwig van Beethoven", "year": 1867, "genre": "chamber"},
    {"title": "The Four Seasons", "by": "Antonio Vivaldi", "year": 1725, "genre": "chamber"},
    {"title": "Eine kleine Nachtmusik", "by": "W. A. Mozart", "year": 1827, "genre": "chamber"},
    {"title": "Flight of the Bumblebee", "by": "Nikolai Rimsky-Korsakov", "year": 1900, "genre": "pizzicato"},
    {"title": "Funeral March of a Marionette", "by": "Charles Gounod", "year": 1872, "genre": "pizzicato"},
    {"title": "The Stars and Stripes Forever", "by": "John Philip Sousa", "year": 1897, "genre": "newsreel"},
    {"title": "Danse Macabre", "by": "Camille Saint-Saëns", "year": 1874, "genre": "noir"},
    {"title": "Ride of the Valkyries", "by": "Richard Wagner", "year": 1870, "genre": "orchestral"},
    {"title": "Swing Low, Sweet Chariot", "by": "traditional spiritual", "year": 1909, "genre": "blues"},
    {"title": "When the Saints Go Marching In", "by": "traditional", "year": 1896, "genre": "twenties"},
]

WHERE_TO_GET = [
    ("Musopen (public-domain recordings and scores; check each one's licence)", "https://musopen.org/"),
    ("Mutopia Project (free sheet music and MIDI: use Public Domain or CC BY files, not CC BY-SA)",
     "https://www.mutopiaproject.org/"),
    ("YouTube Audio Library (never claimed by Content ID)", "https://studio.youtube.com/"),
    ("Library of Congress National Jukebox (recordings before 1923)", "https://www.loc.gov/collections/national-jukebox/"),
    ("Free Music Archive (only CC BY, CC BY-SA or CC0 tracks)", "https://freemusicarchive.org/"),
    ("Incompetech, Kevin MacLeod (CC BY 4.0: needs a credit line)", "https://incompetech.com/"),
]

# licences the program refuses for a monetized video
BLOCKED_LICENCE_WORDS = ("non-commercial", "noncommercial", "cc by-nc", "cc-by-nc", "no derivatives", "cc by-nd",
                         "cc-by-nd", "download only")
