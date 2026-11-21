"""
build_data.py
---------------------------------------------------------------------
Turns your CSV files into the three small data files the website reads:

    institution_extra.json   top 5 authors + venues for each map institution
    authors.json             one entry per author (affiliations, points, rank, papers)
    papers.json              one entry per paper (title, year, venue, DOI)

HOW TO RUN (Windows):
    1. Put this file in the SAME folder as the four CSV files below.
    2. Open it in IDLE and press F5.
    3. Upload the three new .json files to GitHub (next to index.html).
Run it again whenever one of the CSV files changes.

It only uses Python's built-in tools: nothing to install.
"""

import csv
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

FOLDER = Path(__file__).parent

# ---- Input files (must sit next to this script) ----
AFFILIATIONS_CSV = "author_affiliations_merged.csv"  # author;affiliation
PAPERS_CSV = "dblp_results_merged.csv"               # venue,title,authors,year,doi
POINTS_CSV = "merged_authors.csv"                    # author;first;middle;last;points
MAP_CSV = "MAP_DATA.csv"                             # institution;country;papers;lat;lon

# ---- Settings ----
TOP_AUTHORS_PER_INSTITUTION = 5

# Full names shown next to each venue code in the sidebar. Edit freely.
VENUE_NAMES = {
    "IJHCI": "Int. Journal of Human-Computer Interaction",
    "IEEE TAffC": "IEEE Transactions on Affective Computing",
    "ICMI": "Int. Conference on Multimodal Interaction",
    "CHB": "Computers in Human Behavior",
    "ACII": "Affective Computing and Intelligent Interaction",
    "CUI": "Conversational User Interfaces",
    "IVA": "Intelligent Virtual Agents",
    "IJHCS": "Int. Journal of Human-Computer Studies",
    "TiiS": "ACM Transactions on Interactive Intelligent Systems",
    "JMUI": "Journal on Multimodal User Interfaces",
}


# =====================================================================
# Reading and name helpers
# =====================================================================

def read_csv(file_name, delimiter):
    """Reads a CSV file into a list of rows. Tries UTF-8 first, then Windows-1252
    (the points file was saved in that older encoding)."""
    raw = (FOLDER / file_name).read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    return list(csv.DictReader(text.splitlines(), delimiter=delimiter))


def normalize_name(name):
    """Makes names comparable across files: no accents, no capital letters,
    no DBLP number ("Bin Hu 0001" -> "bin hu"), unified hyphens/apostrophes."""
    name = re.sub(r"\s+\d{4}$", "", name.strip())
    name = re.sub(r"[‐-―’']", " ", name)
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.replace("ı", "i").replace("ł", "l").replace("ø", "o").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def first_last_key(name):
    """'Jonathan S. Gratch' and 'Jonathan Gratch' both become 'jonathan gratch'."""
    words = normalize_name(name).split()
    return f"{words[0]} {words[-1]}" if len(words) > 1 else None


# =====================================================================
# Papers and authors
# =====================================================================

def load_papers():
    """Returns the paper list and, for every author name, the paper numbers they are on."""
    papers = []
    author_papers = defaultdict(list)
    for number, row in enumerate(read_csv(PAPERS_CSV, ",")):
        names = [n.strip() for n in row["authors"].split(";") if n.strip()]
        papers.append({
            "title": row["title"].strip(),
            "year": int(row["year"]),
            "venue": row["venue"].strip(),
            "doi": row["doi"].strip(),
            "authors": names,
        })
        for name in names:
            author_papers[name].append(number)
    return papers, author_papers


def find_dblp_name(points_name, dblp_names):
    """Finds the DBLP spelling of a name from the points file. That file has a
    damaged letter in one name ('?gata'), so a '?' is treated as 'any letter'.
    Returns None if there is not exactly one match."""
    if points_name in dblp_names:
        return points_name
    pattern = re.compile("^" + "".join("." if c == "?" else re.escape(c) for c in points_name) + "$")
    matches = [n for n in dblp_names if pattern.match(n)]
    return matches[0] if len(matches) == 1 else None


def load_points(dblp_names):
    """Returns {dblp author name: {first, middle, last, points, rank}}."""
    scores = {}
    for row in read_csv(POINTS_CSV, ";"):
        name = find_dblp_name(row["author"], dblp_names)
        if name is None:
            print(f"  WARNING: '{row['author']}' (points file) not found in the papers file")
            continue
        scores[name] = {
            "first": int(row["first authorship"]),
            "middle": int(row["middle authorship"]),
            "last": int(row["last authorship"]),
            "points": int(row["points"]),
        }

    # Rank = 1 + number of authors with MORE points (equal points share a rank).
    all_points = [s["points"] for s in scores.values()]
    for s in scores.values():
        s["rank"] = 1 + sum(1 for p in all_points if p > s["points"])
    return scores


# =====================================================================
# Affiliations
# =====================================================================

def load_affiliation_index():
    """Groups the affiliations file by normalized author name."""
    by_name = defaultdict(list)  # normalized name -> list of affiliation lists
    for row in read_csv(AFFILIATIONS_CSV, ";"):
        institutions = [i.strip() for i in row["affiliation"].split("|") if i.strip()]
        by_name[normalize_name(row["author"])].append(institutions)
    by_key = defaultdict(set)    # 'first last' -> normalized full names
    for full_name in by_name:
        words = full_name.split()
        if len(words) > 1:
            by_key[f"{words[0]} {words[-1]}"].add(full_name)
    return by_name, by_key


def match_affiliations(dblp_names):
    """Finds the institutions of every author. Returns
    {name: (list of institutions, uncertain)}. 'uncertain' = several different
    people share the name, so the list may mix people."""
    by_name, by_key = load_affiliation_index()
    variants = defaultdict(set)  # how many DBLP spellings share one normalized name
    key_owners = defaultdict(set)
    for name in dblp_names:
        variants[normalize_name(name)].add(name)
        key_owners[first_last_key(name)].add(normalize_name(name))

    result = {}
    exact = fallback = 0
    for name in dblp_names:
        norm = normalize_name(name)
        rows = by_name.get(norm)
        uncertain = False
        if rows:
            exact += 1
            uncertain = len(rows) > 1 or len(variants[norm]) > 1
        else:
            # Fallback: ignore middle names ('Jonathan Gratch' = 'Jonathan S. Gratch'),
            # but only when that 'first last' pair is unambiguous in BOTH files.
            candidates = by_key.get(first_last_key(name) or "", set())
            if len(candidates) == 1 and len(key_owners[first_last_key(name)]) == 1:
                rows = by_name[next(iter(candidates))]
                fallback += 1
        institutions = []
        for row in rows or []:
            institutions += [i for i in row if i not in institutions]
        result[name] = (institutions, uncertain)
    print(f"  affiliations: {exact} exact matches + {fallback} first/last-name matches "
          f"out of {len(dblp_names)} authors")
    return result


# =====================================================================
# Building the output files
# =====================================================================

def build_authors(author_papers, affiliations, scores):
    """One entry per author."""
    authors = []
    for name in sorted(author_papers, key=str.casefold):
        institutions, uncertain = affiliations[name]
        entry = {"name": name, "affiliations": institutions, "papers": author_papers[name]}
        if uncertain:
            entry["uncertain"] = True
        if name in scores:
            entry.update(scores[name])
        authors.append(entry)
    return authors


def build_institution_extra(papers, authors, affiliations, scores):
    """For every institution drawn on the map: its top authors and its venues."""
    drawn = [row["institution"] for row in read_csv(MAP_CSV, ";")
             if row["latitude"].strip() and row["longitude"].strip()]
    institutions = {name: {"venues": defaultdict(int), "topAuthors": []} for name in drawn}

    # Papers per venue: a paper counts for an institution if any of its authors is there.
    for paper in papers:
        paper_institutions = set()
        for name in paper["authors"]:
            paper_institutions.update(affiliations[name][0])
        for institution in paper_institutions & institutions.keys():
            institutions[institution]["venues"][paper["venue"]] += 1

    # Top authors: ranked authors that list the institution, best points first.
    candidates = defaultdict(list)
    for author in authors:
        if "points" not in author:
            continue
        for institution in author["affiliations"]:
            if institution in institutions:
                candidates[institution].append(author)
    for institution, people in candidates.items():
        people.sort(key=lambda a: (-a["points"], a["name"]))
        institutions[institution]["topAuthors"] = [
            {"name": a["name"], "points": a["points"], "uncertain": a.get("uncertain", False)}
            for a in people[:TOP_AUTHORS_PER_INSTITUTION]
        ]
    return institutions


def build_venue_list(papers):
    """Venue codes with their full names and paper counts, biggest first."""
    counts = defaultdict(int)
    for paper in papers:
        counts[paper["venue"]] += 1
    return [{"code": code, "name": VENUE_NAMES.get(code, code), "papers": n}
            for code, n in sorted(counts.items(), key=lambda item: -item[1])]


def write_json(file_name, data):
    """Saves data as compact JSON (UTF-8)."""
    path = FOLDER / file_name
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  wrote {file_name} ({path.stat().st_size / 1024:.0f} KB)")


def main():
    print("Reading files...")
    papers, author_papers = load_papers()
    scores = load_points(set(author_papers))
    affiliations = match_affiliations(author_papers.keys())
    print(f"  {len(papers)} papers, {len(author_papers)} authors, {len(scores)} with points")

    print("Building data...")
    authors = build_authors(author_papers, affiliations, scores)
    institutions = build_institution_extra(papers, authors, affiliations, scores)

    print("Writing files...")
    write_json("papers.json", [{k: p[k] for k in ("title", "year", "venue", "doi")} for p in papers])
    write_json("authors.json", {"rankedCount": len(scores), "authors": authors})
    write_json("institution_extra.json", {"venues": build_venue_list(papers), "institutions": institutions})
    print("Done. Upload the three .json files to GitHub.")


if __name__ == "__main__":
    main()
