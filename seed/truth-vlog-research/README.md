# Investigator database

**Charter:** `docs/14-INVESTIGATOR-CHARTER.md`  
**Brand:** Followers or Facts · owl mascot  
**Foundation:** Knowledge Fight as research index only

## Quick start

1. Open the charter and keep the rules.
2. Search anything:

```bat
python scripts\research_search.py soros
```

Or double-click `research-search.cmd` and type a word.

3. **Project log (hand-off):** `../PROJECT-LOG.md` — new chats read this first.  
4. **2017 deep pass:** DONE → `research/years/2017/YEAR-SUMMARY.md`  
5. Next year only after David says so (or after a season map).

## Layout

```
research/
  README.md                 ← this file
  entities/                 people, orgs, countries
  claims/                   lies + who links to them
  arcs/                     long stories across years
  sources/                  primary URLs and docs
  graph/                    person–org–country relationships
  years/2017|2018|2019/     KF episode index per year
```

## Rebuild from old trackers

If you edit `tracker/*.csv` and want to re-seed (careful — overwrites research CSVs):

```bat
python scripts\build_research_db.py
```

After the deep pass starts, prefer editing files under `research/` directly. Do not wipe links you added by hand.

## Status meanings

| status | meaning |
|--------|---------|
| seed | Migrated / stub — needs deep pass |
| reviewed | Year pass looked at it |
| video-ready | Enough sources to script |
| careful | Harmful topic — extra ethics rules |

## Credit line (every video)

`Research trail: Knowledge Fight episode #___ · This presentation is our own.`
