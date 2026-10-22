"""Import the truth-vlog research CSVs into SQLite, fixing the known problems.

Known problems handled here (found in the October 2026 audit):
  * seven arcs.csv rows are shifted one column (a date sits in `status`)
  * Michael Flynn has two person IDs (P-MICHAEL-FLYNN and P-MIKE-FLYNN)
  * claim-links.csv has exact duplicate rows
  * `kf_eps` and video-ID fields are free text ("266+ KF refs", "037+050+063")
Every fix is listed in the returned report, never applied silently.

Re-running the import replaces the research tables but never touches
projects, jobs, stage history or fetched source copies.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from .. import db
from ..config import REPO, settings
from ..util import split_list, utc_now

SEED = REPO / "seed" / "truth-vlog-research"

ALIASES = {
    "P-MIKE-FLYNN": ("P-MICHAEL-FLYNN", "same person entered twice (2015 and 2020 entries)"),
}

ARC_STATUSES = {"active", "backlog", "ongoing", "planned", "produced"}
CLAIM_STATUS_MAP = {"video-ready": "video_ready", "video_ready": "video_ready",
                    "seed": "seed", "researched": "researched", "needs_primary": "needs_primary"}
FALSITY = {"false", "misleading", "contested", "partially_true_wrapped", "unverified"}
SOURCE_TYPES = {"court", "wire", "gov", "journalism", "archive_audio", "academic",
                "museum", "kf_index", "other"}

# Topics where victims or bereaved families are involved. truth-vlog's rule:
# courts and documents only, no names of private people, no imagery of the event.
SEED_RESTRICTIONS = [
    ("arc", "A-SANDY-HOOK", "courts_only", "Victims' families: courts and documents only."),
    ("arc", "A-SANDY-HOOK", "no_names", "Never name the children or families."),
    ("arc", "A-SANDY-HOOK", "no_footage", "No imagery of the school or the day."),
    ("arc", "A-SANDY-HOOK-SR", "courts_only", "Victims' families: courts and documents only."),
    ("arc", "A-SANDY-HOOK-SR", "no_names", "Never name the children or families."),
    ("arc", "A-SANDY-HOOK-SR", "no_footage", "No imagery of the school or the day."),
    ("arc", "A-PIZZAGATE", "courts_only", "Real-world harassment; court documents."),
    ("arc", "A-SETH-RICH", "courts_only", "Family harassment; court documents."),
    ("arc", "A-SETH-RICH", "no_person_imagery", "Do not depict the victim."),
    ("arc", "A-LAS-VEGAS-FF", "no_footage", "Mass shooting: no imagery of the event."),
    ("arc", "A-LAS-VEGAS-FF", "no_names", "Never name victims."),
]


def research_dir(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit)
    configured = Path(settings()["paths"]["truth_vlog_research"])
    if (configured / "claims" / "claims.csv").exists():
        return configured
    return SEED


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [{k: (v or "").strip() for k, v in row.items() if k is not None}
                for row in csv.DictReader(fh)]


def _canonical(entity_id: str) -> str:
    return ALIASES.get(entity_id, (entity_id, ""))[0]


def _fix_arc(row: dict[str, str], fixes: list[str]) -> dict[str, str]:
    row = dict(row)
    if re.fullmatch(r"\d{4}(-\d{2})?", row.get("status", "")):
        stray = row.get("harm_documented", "")
        notes = row.get("notes", "")
        harm, _, rest = notes.partition(" | ")
        row["first_known_origin"] = f"{row['status']} ({row.get('first_known_origin', '')})".strip()
        row["status"] = "backlog"
        row["harm_documented"] = harm.strip()
        extra = f"[import: row was shifted one column; stray value '{stray}' moved here]"
        row["notes"] = " | ".join(p for p in (rest.strip(), extra) if p)
        fixes.append(f"arcs.csv {row['arc_id']}: un-shifted columns (date was in status)")
    elif row.get("status") not in ARC_STATUSES:
        fixes.append(f"arcs.csv {row['arc_id']}: unknown status '{row.get('status')}' -> backlog")
        row["status"] = "backlog"
    return row


def import_research(source: str | Path | None = None, path: Path | None = None) -> dict[str, Any]:
    src = research_dir(source)
    if not (src / "claims" / "claims.csv").exists():
        raise FileNotFoundError(f"No research database found at {src} (expected claims/claims.csv).")

    db.init(path)
    fixes: list[str] = []
    warnings: list[str] = []
    counts: dict[str, int] = {}

    people = _read(src / "entities" / "people.csv")
    orgs = _read(src / "entities" / "organizations.csv")
    countries = _read(src / "entities" / "countries.csv")
    arcs = [_fix_arc(r, fixes) for r in _read(src / "arcs" / "arcs.csv")]
    claims = _read(src / "claims" / "claims.csv")
    links = _read(src / "claims" / "claim-links.csv")
    sources = _read(src / "sources" / "sources.csv")
    claim_sources = _read(src / "sources" / "claim-sources.csv")
    relationships = _read(src / "graph" / "relationships.csv")

    with db.transaction(path) as con:
        for table in ("relationship_source", "relationship", "kf_episode_link", "kf_episode",
                      "research_note", "claim_entity", "claim_source", "entity_alias",
                      "legacy_video_tracker"):
            con.execute(f"DELETE FROM {table}")
        # Claims, sources and arcs are upserted so project links survive a re-import.

        # ---- people, merging aliases into their canonical row
        merged: dict[str, dict[str, str]] = {}
        for row in people:
            pid = row["person_id"]
            canon = _canonical(pid)
            if canon != pid:
                fixes.append(f"people.csv {pid}: merged into {canon} ({ALIASES[pid][1]})")
                con.execute("INSERT OR REPLACE INTO entity_alias VALUES (?,?,?)",
                            (pid, canon, ALIASES[pid][1]))
            base = merged.setdefault(canon, {**row, "person_id": canon})
            if base is not row and canon != pid:
                for key, value in row.items():
                    if key == "person_id" or not value:
                        continue
                    if not base.get(key):
                        base[key] = value
                    elif value not in base[key] and key in ("notes", "aka", "role_types",
                                                           "motive_notes", "orgs"):
                        base[key] = f"{base[key]}; {value}"
        con.execute("DELETE FROM person")
        for row in merged.values():
            con.execute(
                "INSERT INTO person VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (row["person_id"], row["name"], row.get("aka"), row.get("role_types"),
                 row.get("orgs"), row.get("first_kf_ep"), row.get("first_seen_year"),
                 row.get("motive_notes"), row.get("status"), row.get("wiki_or_bio_url"),
                 row.get("notes")))
        counts["people"] = len(merged)

        con.execute("DELETE FROM organization")
        for row in orgs:
            con.execute("INSERT OR REPLACE INTO organization VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        tuple(row.get(k) for k in ("org_id", "name", "type", "founded", "country",
                              "role", "tactics", "funding_notes", "first_kf_ep", "status", "notes")))
        counts["organizations"] = len(orgs)

        con.execute("DELETE FROM country")
        for row in countries:
            con.execute("INSERT OR REPLACE INTO country VALUES (?,?,?,?,?,?)",
                        tuple(row.get(k) for k in ("country_id", "name", "influence_type",
                              "documented_vectors", "key_cases", "notes")))
        counts["countries"] = len(countries)

        # ---- arcs
        arc_ids = set()
        for row in arcs:
            arc_ids.add(row["arc_id"])
            con.execute(
                """INSERT INTO arc VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(arc_id) DO UPDATE SET title=excluded.title,
                   first_known_origin=excluded.first_known_origin, status=excluded.status,
                   kf_eps_text=excluded.kf_eps_text, legacy_video_ids=excluded.legacy_video_ids,
                   harm_documented=excluded.harm_documented, notes=excluded.notes""",
                (row["arc_id"], row["title"], row.get("first_known_origin"), row["status"],
                 row.get("kf_eps"), row.get("our_video_ids"), row.get("harm_documented"),
                 row.get("notes")))
        counts["arcs"] = len(arcs)

        # ---- claims
        claim_ids = set()
        for row in claims:
            cid = row["claim_id"]
            arc_id = row.get("arc_id") or None
            if arc_id and arc_id not in arc_ids:
                warnings.append(f"claims.csv {cid}: arc {arc_id} does not exist; left unlinked")
                arc_id = None
            status = CLAIM_STATUS_MAP.get(row.get("status", ""), "seed")
            if status != row.get("status"):
                fixes.append(f"claims.csv {cid}: status '{row.get('status')}' -> {status}")
            falsity = row.get("falsity_status") or "unverified"
            if falsity not in FALSITY:
                warnings.append(f"claims.csv {cid}: unknown falsity '{falsity}' -> unverified")
                falsity = "unverified"
            claim_ids.add(cid)
            con.execute(
                """INSERT INTO claim VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(claim_id) DO UPDATE SET short_title=excluded.short_title,
                   claim_summary=excluded.claim_summary, first_known_year=excluded.first_known_year,
                   peak_years=excluded.peak_years, kf_eps_text=excluded.kf_eps_text,
                   arc_id=excluded.arc_id, falsity_status=excluded.falsity_status,
                   harm_summary=excluded.harm_summary, who_benefited=excluded.who_benefited,
                   society_effect=excluded.society_effect,
                   legacy_video_id=excluded.legacy_video_id, status=excluded.status""",
                (cid, row["short_title"], row.get("claim_summary"), row.get("first_known_year"),
                 row.get("peak_years"), row.get("kf_eps"), arc_id, falsity,
                 row.get("harm_summary"), row.get("who_benefited"), row.get("society_effect"),
                 row.get("our_video_id"), status))
        counts["claims"] = len(claims)

        dupes = 0
        for row in links:
            if row["claim_id"] not in claim_ids:
                warnings.append(f"claim-links.csv: unknown claim {row['claim_id']}")
                continue
            entity_id = _canonical(row["entity_id"])
            n = con.execute("INSERT OR IGNORE INTO claim_entity VALUES (?,?,?,?)",
                            (row["claim_id"], row["entity_type"], entity_id,
                             row.get("link_role", ""))).rowcount
            dupes += 1 - n
        if dupes:
            fixes.append(f"claim-links.csv: dropped {dupes} duplicate rows")
        counts["claim_links"] = len(links) - dupes

        # ---- sources (keep fetched-copy columns on re-import)
        source_ids = set()
        for row in sources:
            stype = row.get("source_type") or "other"
            if stype not in SOURCE_TYPES:
                warnings.append(f"sources.csv {row['source_id']}: unknown type '{stype}' -> other")
                stype = "other"
            source_ids.add(row["source_id"])
            con.execute(
                """INSERT INTO source(source_id,title,publisher,date,url,source_type,reliability,notes)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(source_id) DO UPDATE SET title=excluded.title,
                   publisher=excluded.publisher, date=excluded.date, url=excluded.url,
                   source_type=excluded.source_type, reliability=excluded.reliability,
                   notes=excluded.notes""",
                (row["source_id"], row["title"], row.get("publisher"), row.get("date"),
                 row.get("url"), stype, row.get("reliability"), row.get("notes")))
        counts["sources"] = len(sources)

        cited = 0
        for row in claim_sources:
            if row["claim_id"] not in claim_ids or row["source_id"] not in source_ids:
                warnings.append(f"claim-sources.csv: {row['claim_id']} -> {row['source_id']} "
                                "points at a missing row; skipped")
                continue
            cited += con.execute("INSERT OR IGNORE INTO claim_source VALUES (?,?,?,?)",
                                 (row["claim_id"], row["source_id"],
                                  row.get("supports_field", ""), row.get("notes"))).rowcount
        counts["claim_sources"] = cited

        for row in relationships:
            cur = con.execute(
                "INSERT INTO relationship(from_type,from_id,to_type,to_id,relation,start_year,"
                "end_year,notes) VALUES (?,?,?,?,?,?,?,?)",
                (row.get("from_type"), _canonical(row.get("from_id", "")), row.get("to_type"),
                 _canonical(row.get("to_id", "")), row.get("relation"), row.get("start_year"),
                 row.get("end_year"), row.get("notes")))
            for sid in split_list(row.get("source_ids")):
                con.execute("INSERT OR IGNORE INTO relationship_source VALUES (?,?)",
                            (cur.lastrowid, sid))
        counts["relationships"] = len(relationships)

        # ---- Knowledge Fight year indexes and notes
        episodes = 0
        for index in sorted((src / "years").glob("*/kf-episode-index.csv")):
            year = int(index.parent.name) if index.parent.name.isdigit() else None
            for row in _read(index):
                kf_ep = row["kf_ep"]
                num = re.match(r"\d+", kf_ep)
                notes = row.get("notes", "")
                con.execute(
                    "INSERT OR REPLACE INTO kf_episode VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (kf_ep, int(num.group()) if num else None, year, row.get("air_date"),
                     row.get("title"), row.get("topics"), row.get("priority"),
                     row.get("deep_pass"), notes, int("CAREFUL" in notes.upper())))
                for field, etype in (("claim_ids", "claim"), ("person_ids", "person"),
                                     ("org_ids", "org"), ("country_ids", "country")):
                    for eid in split_list(row.get(field)):
                        con.execute("INSERT OR IGNORE INTO kf_episode_link VALUES (?,?,?)",
                                    (kf_ep, etype, _canonical(eid)))
                episodes += 1
            for note in sorted(index.parent.glob("**/*.md")):
                con.execute("INSERT INTO research_note(year,path,body_md) VALUES (?,?,?)",
                            (year, str(note.relative_to(src)).replace("\\", "/"),
                             note.read_text(encoding="utf-8", errors="replace")))
        counts["kf_episodes"] = episodes

        for subject_type, subject_id, rule, note in SEED_RESTRICTIONS:
            if subject_id in arc_ids:
                con.execute("INSERT OR IGNORE INTO content_restriction VALUES (?,?,?,?)",
                            (subject_type, subject_id, rule, note))
        # Every Sandy Hook arc, and any arc whose notes say "courts only", gets the
        # victims rule automatically so a new arc can't slip past it.
        for row in arcs:
            text = f"{row['arc_id']} {row['title']} {row.get('notes', '')}".lower()
            if "sandy" in text or row["arc_id"].startswith("A-SH-") or re.search(
                    r"courts?(/docs)?(/documents)? only|courts and documents only", text):
                for rule in ("courts_only", "no_names", "no_footage"):
                    con.execute("INSERT OR IGNORE INTO content_restriction VALUES (?,?,?,?)",
                                ("arc", row["arc_id"], rule,
                                 "Victims involved: courts and documents only (auto from arc notes)."))

        tracker = src.parent / "tracker" / "VIDEO_TRACKER.csv"
        for row in _read(tracker):
            con.execute("INSERT INTO legacy_video_tracker VALUES (?)", (json.dumps(row),))

        con.execute("INSERT OR REPLACE INTO meta VALUES ('research_imported_at', ?)", (utc_now(),))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('research_source', ?)", (str(src),))

    return {"source": str(src), "counts": counts, "fixes": fixes, "warnings": warnings}


EXPORTS = {
    "entities/people.csv": ("SELECT person_id,name,aka,role_types,orgs_text AS orgs,first_kf_ep,"
                            "first_seen_year,motive_notes,status,wiki_or_bio_url,notes FROM person "
                            "ORDER BY person_id"),
    "arcs/arcs.csv": ("SELECT arc_id,title,first_known_origin,status,kf_eps_text AS kf_eps,"
                      "legacy_video_ids AS our_video_ids,harm_documented,notes FROM arc ORDER BY arc_id"),
    "claims/claims.csv": ("SELECT claim_id,short_title,claim_summary,first_known_year,peak_years,"
                          "kf_eps_text AS kf_eps,arc_id,falsity_status,harm_summary,who_benefited,"
                          "society_effect,legacy_video_id AS our_video_id,status FROM claim "
                          "ORDER BY claim_id"),
    "claims/claim-links.csv": "SELECT * FROM claim_entity ORDER BY claim_id,entity_type,entity_id",
    "sources/sources.csv": ("SELECT source_id,title,publisher,date,url,source_type,reliability,notes "
                            "FROM source ORDER BY source_id"),
    "sources/claim-sources.csv": "SELECT * FROM claim_source ORDER BY claim_id,source_id",
}


def export_csv(out_dir: Path, path: Path | None = None) -> list[Path]:
    """Write the core tables back out in truth-vlog's CSV layout."""
    written = []
    for rel, sql in EXPORTS.items():
        data = db.rows(sql, path=path)
        target = Path(out_dir) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="") as fh:
            if data:
                writer = csv.DictWriter(fh, fieldnames=list(data[0].keys()))
                writer.writeheader()
                writer.writerows(data)
        written.append(target)
    return written
