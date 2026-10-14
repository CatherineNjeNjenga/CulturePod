"""Remove the raw comment text from your hand-labelled sample CSVs, keeping your labels and what the rules said about each comment.

Why: YouTube's developer policies allow keeping public comment text for 30 days. The sample files written by sample_neither.py hold raw
comment text, so once you have labelled them (and any rule changes are done) the text should go.

Usage:
  python strip_samples.py comment_sample_v1.csv guest_sample_v1.csv ...            # writes <name>_stripped.csv next to each
  python strip_samples.py *.csv --delete-original                                 # also deletes each original after checking the copy
  python strip_samples.py x.csv --episodes episodes.csv --keep-notes

For every row the stripped file keeps: video_id, guest, likes, compound, your label / mode / notes, and from the text only derived values:
words, script (latin / cyrillic ...), a short fingerprint (text_id, lets you spot duplicate rows, cannot be turned back into the text),
and what today's rules say: rules_about, rules_mode, rules_focus, rules_version, plus agree (rules_about matches your label; "ok" counts
as a match). Label and mode cells are cut to the word before ':' ("ok: it's about the guest..." becomes "ok"). Your notes are cleared on any row where they quote the comment (a run of 5+ words or 25+ characters from it); use
--keep-notes to keep them anyway. After writing, the script scans the output for any piece of the original text and refuses to delete
the original if it finds one.

Because the text is gone, a stripped file cannot be re-run through changed rules: it shows how the rules did the day you stripped it.
For a fresh accuracy figure label a new sample with sample_neither.py.
"""
import argparse
import csv
import hashlib
import os
import re
import sys

import pandas as pd

import classify

QUOTE_WORDS = 5       # a run of this many consecutive words copied from the comment counts as quoting it
QUOTE_CHARS = 25      # ...or this many consecutive characters


def _norm(t):
    return re.sub(r"\s+", " ", str(t)).strip().lower()


def _runs(text, k):
    w = re.findall(r"\w+", _norm(text))
    return {" ".join(w[i:i + k]) for i in range(max(0, len(w) - k + 1))}


def quotes(text, other):
    """True when `other` (a note, or any output cell) contains a long run copied from `text`."""
    o, t = _norm(other), _norm(text)
    if not o or not t:
        return False
    if 12 <= len(t) <= QUOTE_CHARS and t in o:
        return True
    if any(t[i:i + QUOTE_CHARS] in o for i in range(0, max(1, len(t) - QUOTE_CHARS + 1))) and len(t) >= QUOTE_CHARS:
        return True
    ow = " ".join(re.findall(r"\w+", o))
    return any(r in ow for r in _runs(t, QUOTE_WORDS))


def episode_lookup(path):
    """{guest: aliases} and {video_id: aliases} from episodes.csv."""
    by_guest, by_id = {}, {}
    if path and os.path.exists(path):
        for r in classify._csv_rows(path):
            g, al = (r.get("guest") or "").strip(), (r.get("guest_aliases") or "").strip()
            m = re.search(r"[?&]v=([\w-]{6,})", r.get("video_url") or "")
            by_guest[g] = al
            if m:
                by_id[m.group(1)] = al
    return by_guest, by_id


def read_rows(path):
    """DataFrame of strings. A row with too many fields (an unquoted comma inside the text) has the extra fields folded back into
    `text`; a row with too few is padded. Returns (df, number of repaired rows)."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    head, body, fixed = rows[0], rows[1:], 0
    ti = head.index("text") if "text" in head else None
    out = []
    for r in body:
        if len(r) > len(head) and ti is not None:
            extra = len(r) - len(head)
            r = r[:ti] + [",".join(r[ti:ti + extra + 1])] + r[ti + extra + 1:]
            fixed += 1
        elif len(r) < len(head):
            r = r + [""] * (len(head) - len(r))
            fixed += 1
        out.append(r[:len(head)])
    return pd.DataFrame(out, columns=head, dtype=str), fixed


def strip_file(path, by_guest, by_id, keep_notes=False, tag=None):
    df, repaired = read_rows(path)
    if "text" not in df.columns:
        return None, f"{path}: no 'text' column (already stripped?), skipped"
    d = pd.DataFrame({"comment": df["text"], "video_id": df.get("video_id", ""), "guest": df.get("guest", "")})
    d["guest_aliases"] = [by_id.get(v) or by_guest.get(g) or "" for v, g in zip(d["video_id"], d["guest"])]
    missing = sorted({g for g, a in zip(d["guest"], d["guest_aliases"]) if not a})
    d["about"] = classify.classify(d)
    d["mode"] = classify.mode_all(d, d["about"])
    d["focus"] = classify.focus_all(d, d["about"])
    out = df.drop(columns=["text"]).copy()
    for c in ("your_label", "your_mode", "mode"):      # dropdown-style cells ("ok: it's about the guest...") can carry copied comment text: keep the word before ':'
        if c in out:
            out[c] = [re.split(r"[:\u2013\u2014]", v, maxsplit=1)[0].strip().lower() if ":" in v or "\u2013" in v or "\u2014" in v else v.strip().lower() for v in out[c]]
    out["text_id"] = [hashlib.sha256(_norm(t).encode("utf-8")).hexdigest()[:10] for t in df["text"]]
    out["words"] = [classify.n_words(t) for t in df["text"]]
    out["script"] = [classify.script_of(t) for t in df["text"]]
    out["rules_about"], out["rules_mode"], out["rules_focus"] = d["about"], d["mode"].fillna(""), d["focus"].fillna("")
    out["rules_version"] = classify.RULES_VERSION
    lab = out["your_label"].str.strip().str.lower() if "your_label" in out else pd.Series("", index=out.index)
    def verdict(l, a):
        if not l:
            return ""
        if l == "ok":                                   # "the tag was right": only comparable when we know which tag the sample was drawn from
            return "" if not tag else ("yes" if a.lower() == tag.lower() else "no")
        return "yes" if l == a.lower() else "no"
    out["agree"] = [verdict(l, a) for l, a in zip(lab, out["rules_about"])]
    cleared = 0
    if "notes" in out and not keep_notes:
        for i, (t, n) in enumerate(zip(df["text"], out["notes"])):
            if n and quotes(t, n):
                out.loc[i, "notes"] = "[removed: quoted the comment]"
                cleared += 1
    # final scan: no cell of the output may carry a long piece of any original comment
    for i, t in enumerate(df["text"]):
        for c in out.columns:
            if c not in ("text_id",) and quotes(t, out.loc[i, c]) and len(_norm(t)) >= 12:
                return None, f"{path}: row {i + 2}, column '{c}' still contains comment text; nothing written"
    info = {"repaired": repaired, "rows": len(out), "cleared_notes": cleared, "missing_aliases": missing,
            "agree": (out["agree"] == "yes").sum(), "labelled": (out["agree"] != "").sum()}
    return (out, info), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--episodes", default="episodes.csv", help="episodes.csv (for the guests' aliases); default ./episodes.csv")
    ap.add_argument("--keep-notes", action="store_true")
    ap.add_argument("--tag", default=None, help="the tag the sample was drawn from (Maria, Guest, Both, Pair, Neither...): rows you labelled 'ok' "
                    "then count as agreement when today's rules still give that tag. Use it with one sample type per run.")
    ap.add_argument("--delete-original", action="store_true")
    a = ap.parse_args()
    by_guest, by_id = episode_lookup(a.episodes)
    if not by_guest:
        print(f"Note: {a.episodes} not found or empty. Guest aliases are unknown, so rules_about may differ from what the pipeline said.")
    bad = 0
    for f in a.files:
        if f.endswith("_stripped.csv"):
            continue
        res, err = strip_file(f, by_guest, by_id, a.keep_notes, a.tag)
        if err:
            print(err)
            bad += 1
            continue
        out, info = res
        dest = re.sub(r"\.csv$", "", f) + "_stripped.csv"
        out.to_csv(dest, index=False, encoding="utf-8")
        chk = pd.read_csv(dest, dtype=str, keep_default_na=False)
        ok = len(chk) == info["rows"] and "text" not in chk.columns
        print(f"{f} -> {dest}: {info['rows']} rows; notes cleared on {info['cleared_notes']}; rules agree with your label on "
              f"{info['agree']}/{info['labelled']}" + (f"; repaired {info['repaired']} ragged row(s)" if info["repaired"] else "") + (f"; no aliases for: {', '.join(info['missing_aliases'])}" if info["missing_aliases"] else ""))
        if a.delete_original:
            if ok:
                os.remove(f)
                print(f"  deleted {f}")
            else:
                print(f"  kept {f}: the copy did not check out")
                bad += 1
    if not a.delete_original:
        print("\nOriginals are untouched. Delete them yourself (and any copies: Downloads, email, cloud folders), or re-run with --delete-original.")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
