"""Write a reading pack for ONE episode: a Markdown file of comments to skim before you write the "what the audience thought" section.

Usage:
  python reading_pack.py                      # the most recent episode whose comment text is still held
  python reading_pack.py --guest "Zoe"        # the episode whose guest name contains this text
  python reading_pack.py --n 10 --out reading_pack.md

What is in it: the week's numbers (tags, tone, keyword candidates, requested guests), then the most-liked comments, the most-replied-to,
the show/episode comments (most positive, most negative and a few from the middle), readable comments on the topic, comments about Maria,
about the guest and about both, and the longest comments. Each comment appears once. No usernames are stored, so there are none to show.

IMPORTANT: the file holds raw comment text. It is for your reading only: do not publish it, do not keep it past the 28 days YouTube
allows (the weekly text purge does not reach a file you saved), delete it after reading. The workflow uploads it as a one-day
download. Paraphrase themes in the post rather than quoting.
"""
import argparse
import json
import random
import re

import classify
import store

NOTES = """## Notes for you (paraphrase, do not quote)
- What did people praise? What did they criticise? Was it the guest, Maria, the questions or the topic?
- Was there a theme that came up in different words? (The keyword candidates above are a starting point, not an answer.)
- Anything that surprised you, or that the numbers cannot show?
- Two or three sentences is plenty. Say how many comments you read and that it is your reading, not a measurement.
"""


def clean(t, cap=600):
    t = re.sub(r"\s+", " ", str(t or "")).strip()
    return t if len(t) <= cap else t[:cap].rstrip() + " [...]"


def tone(c):
    if c is None:
        return "?"
    return "positive" if c >= 0.05 else "negative" if c <= -0.05 else "neutral"


def pick_episode(db, guest):
    rows = db.execute("""SELECT e.video_id, e.guest, e.guest_aliases, e.published, e.keywords, e.requested, e.n_comments,
                                (SELECT COUNT(*) FROM comments c WHERE c.video_id=e.video_id AND c.text IS NOT NULL) AS held
                         FROM episodes e WHERE e.status='done' ORDER BY e.published DESC""")
    rows = [r for r in rows if r["held"]]
    if guest:
        rows = [r for r in rows if guest.lower() in str(r["guest"]).lower()]
    return rows[0] if rows else None


def block(title, items, shown):
    """items: list of comment dicts. Marks them shown; returns the Markdown section ('' if empty)."""
    items = [x for x in items if x["comment_key"] not in shown]
    if not items:
        return ""
    for x in items:
        shown.add(x["comment_key"])
    out = [f"## {title}", ""]
    for x in items:
        meta = f"{x['likes']} like{'s' if x['likes'] != 1 else ''}"
        if x.get("replies"):
            meta += f", {x['replies']} repl{'ies' if x['replies'] != 1 else 'y'}"
        meta += f" · tagged {x['about']} · {tone(x['compound'])}"
        if x.get("about") == "Request":
            meta += f" · names read: {x.get('names') or 'none'}"
        out += [f"> {clean(x['text'])}", f"> *{meta}*", ""]
    return "\n".join(out) + "\n"


def names_reader(db, ep, rows):
    """Function text -> names the rules read from it (what the requested-guests chart would count), for Request comments."""
    ids = str(ep["guest_aliases"] if "guest_aliases" in ep.keys() else "")
    skip = {t for a in ids.split("|") for t in re.findall(r"\w+", classify._strip(a))}
    skip |= set(re.findall(r"\w+", classify._strip(str(ep["guest"]))))
    common = classify.common_words([r["text"] for r in rows if r["about"] != "Request"])
    return lambda t: classify._names_in(str(t), skip, common)


def build(db, ep, n, seed):
    rows = [dict(r) for r in db.execute(
        """SELECT comment_key, text, likes, replies, compound, about, mode, words FROM comments
           WHERE video_id=? AND text IS NOT NULL AND is_reply=0""", (ep["video_id"],))]
    rows = [r for r in rows if r["about"] not in ("Noise", "Reaction")]
    read = names_reader(db, ep, rows)
    for r in rows:
        r["names"] = ", ".join(read(r["text"])) if r["about"] == "Request" else None
    for r in rows:
        r["likes"], r["replies"], r["words"] = r["likes"] or 0, r["replies"] or 0, r["words"] or len(str(r["text"]).split())
    rng = random.Random(seed)
    shown = set()

    def sample(pool, k):
        pool = [x for x in pool if x["comment_key"] not in shown]
        return rng.sample(pool, min(k, len(pool)))

    out = [f"# Reading pack: {ep['guest']} ({ep['published']})", "",
           "> **Raw comment text. For your reading only: do not publish, delete after reading.**", ""]
    tags = {}
    for r in rows:
        tags[r["about"]] = tags.get(r["about"], 0) + 1
    out.append(f"{len(rows)} comments with text held (replies, links-only and emoji-only comments left out). Tags: "
               + ", ".join(f"{k} {v}" for k, v in sorted(tags.items(), key=lambda kv: -kv[1])) + ".")
    for who in ("Maria", "Guest"):
        c = [r["compound"] for r in rows if r["about"] == who and r["compound"] is not None]
        if len(c) >= 10:
            out.append(f"- Tone of comments naming only {'Maria' if who == 'Maria' else 'the guest'}: "
                       f"{sum(x >= 0.05 for x in c) / len(c):.0%} positive, {sum(x <= -0.05 for x in c) / len(c):.0%} negative ({len(c)} comments).")
    try:
        kw = json.loads(ep["keywords"]) if ep["keywords"] else []
    except Exception:
        kw = []
    if kw:
        out.append("- Keyword candidates: " + ", ".join(f"{k['w']} ({k['n']})" for k in kw[:8]) + ".")
    try:
        rq = classify.clean_requested(json.loads(ep["requested"])) if ep["requested"] else None
    except Exception:
        rq = None
    if rq and rq.get("names"):
        out.append("- Guests asked for: " + ", ".join(f"{x['name']} ({x['n']})" for x in rq["names"][:6]) + ".")
    out.append("")
    body = []
    body.append(block(f"Most liked", sorted(rows, key=lambda r: -r["likes"])[:n], shown))
    body.append(block("Most replied to", sorted([r for r in rows if r["replies"]], key=lambda r: -r["replies"])[:max(3, n // 2)], shown))
    show = [r for r in rows if r["about"] == "Show" and r["compound"] is not None]
    k = max(2, n // 3)
    top = sorted(show, key=lambda r: -r["compound"])[:k]
    low = sorted(show, key=lambda r: r["compound"])[:k]
    shown_show = {x["comment_key"] for x in top + low}
    body.append(block("About the show or episode: most positive, most negative, and a few from the middle",
                      top + low + sample([r for r in show if r["comment_key"] not in shown_show], k), shown))
    body.append(block("Asking for a guest (read these to see who was named and who was missed)", [r for r in rows if r["about"] == "Request"][:max(n, 12)], shown))
    body.append(block("Comments about the topic (5+ words, no name)", sample([r for r in rows if r["about"] == "Topic"], n), shown))
    body.append(block("About Maria only", sample([r for r in rows if r["about"] == "Maria"], n), shown))
    body.append(block("About the guest only", sample([r for r in rows if r["about"] == "Guest"], n), shown))
    body.append(block("Naming both Maria and the guest", sample([r for r in rows if r["about"] == "Both"], max(3, n // 2)), shown))
    body.append(block("Longest comments", sorted(rows, key=lambda r: -r["words"])[:max(3, n // 3)], shown))
    out += [b for b in body if b]
    out.append(NOTES)
    return "\n".join(out), len(shown)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--guest", default=None)
    ap.add_argument("--n", type=int, default=12, help="comments per section")
    ap.add_argument("--out", default="reading_pack.md")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    db = store.connect()
    ep = pick_episode(db, a.guest)
    if not ep:
        raise SystemExit("No episode with comment text still held" + (f" for guest matching '{a.guest}'" if a.guest else "") +
                         ". Text is deleted after 28 days.")
    text, n = build(db, ep, a.n, a.seed)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Wrote {a.out}: {n} comments from the {ep['guest']} episode (text not shown in the log). Read it, then delete it.")


if __name__ == "__main__":
    main()
