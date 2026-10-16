"""Write a Substack-ready, per-episode "Maria vs the guest" report (Markdown) from the pipeline's output folder.

Usage:
  python episode_report.py                      # the most recent episode  -> out/reports/<date>_<guest>.md
  python episode_report.py --guest "Zoe"        # the episode whose guest name contains this text
  python episode_report.py --all                # every episode

Reads out/episode_summary.csv and out/run_info.json only (derived numbers, never comment text). Paste the Markdown into Substack
(or open it in a Markdown editor and copy). The wording is neutral on purpose; edit the opening line to add your own take.
"""
import argparse
import json
import os
import re

import numpy as np
import pandas as pd

import build_site as bs

SOURCE_ON_IMAGES = True   # a short "Source: ..." line at the foot of every PNG; set False if the post already credits YouTube once
SRC = bs.SOURCE_LINE if SOURCE_ON_IMAGES else ""
YT_TERMS = bs.YT_TERMS
G_PRIVACY = bs.G_PRIVACY


SQ = 6.0          # LinkedIn version: a 6 x 6 inch square at 180 dpi = 1080 x 1080 pixels


def wrap(t, n):
    """Wrap text for the square layout (explicit line breaks)."""
    import textwrap
    return "\n".join(textwrap.fill(p, n) for p in str(t).split("\n"))


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-") or "episode"


def pct(x, d=0):
    return "n/a" if pd.isna(x) else f"{x * 100:.{d}f}%"


def ordinal(n):
    n = int(n)
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def verdict_line(r):
    g, lo, hi = r["gap_pts"], r["lo_pts"], r["hi_pts"]
    if not r["reliable"]:
        return (f"Too few comments name Maria or {r['guest']} ({int(r['n_named'])}, and we need {bs.MIN_RELIABLE}) to say anything "
                "about this episode. It is shown but left out of the season averages.")
    who = "Maria" if g > 0 else r["guest"]
    other = r["guest"] if g > 0 else "Maria"
    if lo > 0 or hi < 0:
        return (f"Viewers named **{who}** more often than {other} in this episode: a gap of {abs(g):.1f} percentage points of all comments "
                f"(95% range {bs._pts(lo)} to {bs._pts(hi)}).")
    return (f"No clear winner. {who} was named {abs(g):.1f} points more often, but the 95% range ({bs._pts(lo)} to {bs._pts(hi)}) "
            "includes zero, so this episode alone does not show that either was named more.")


COL = {"maria": "#C8553D", "guest": "#1B74B8", "both": "#B8860B", "show": "#2A9D6F", "request": "#7B5EA7", "other": "#C9C9C9"}   # light palette, validated


TITLES = {"dr", "dr.", "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "prof", "prof.", "sir", "dame", "coach"}


def first_name(guest):
    """First name of the guest, to match 'Maria' ('Alex Eala' -> 'Alex'; a leading title such as 'Dr.' is skipped)."""
    parts = str(guest or "").split()
    while len(parts) > 1 and parts[0].lower() in TITLES:
        parts = parts[1:]
    return parts[0] if parts else "the guest"


def draw_chart(e, i, path, sq=False):
    """PNG for Substack: a bar graph of what this episode's comments were about (share of all comments); 'everything else' is left off."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("(matplotlib not installed: no chart image. Run: pip install matplotlib)")
        return False
    r = e.iloc[i]
    ink, mut = "#1d1d1f", "#5f5f66"
    glab = f"Only {first_name(r.get('guest'))} named"
    names = {"maria": "Only Maria named", "guest": glab, "both": "Both named", "show": "About the show",
             "request": "Asking for a guest"}
    vals = [(k, names.get(k, nm), float(r.get(c) or 0) * 100) for k, nm, c in bs.MIX]
    rest = max(0.0, 100 - sum(v for _, _, v in vals))
    fig, ax = plt.subplots(figsize=(SQ, SQ) if sq else (8, 4.2), dpi=180 if sq else 200, facecolor="white")
    if sq:
        fig.subplots_adjust(left=0.33, right=0.93, top=0.73, bottom=0.17)
    else:
        fig.subplots_adjust(left=0.27, right=0.94, top=0.8, bottom=0.17)
    ys = list(range(len(vals)))[::-1]
    top = max([v for _, _, v in vals] + [1])
    for y, (k, nm, v) in zip(ys, vals):
        ax.barh(y, v, color=COL[k], height=0.62, zorder=2)
        ax.text(v + top * 0.015, y, f"{v:.0f}%" if v >= 1 else "<1%", va="center", fontsize=9.5, color=ink, fontweight="bold")
    ax.set_yticks(ys)
    ax.set_yticklabels([nm for _, nm, _ in vals], fontsize=9.5, color=ink)
    ax.set_xlim(0, top * 1.15)
    ax.grid(axis="x", color="#e6e6e6", lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color("#bbbbbb")
    ax.tick_params(axis="both", length=0, labelsize=8.5, colors=mut)
    ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(nbins=6, steps=[1, 2, 5, 10], integer=True))   # whole-percent ticks only (2.5 steps showed as 2%, 5%, 8%)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    ax.set_xlabel("Share of all comments", fontsize=8.5, color=mut)
    g = r["gap_pts"]
    head = (f"Pretty Tough with {r['guest']}: what viewers wrote about" if r["reliable"] else f"Pretty Tough with {r['guest']}: too few named comments")
    sub = f"{int(r['n_comments']):,} comments in the first 7 days."
    if r["reliable"]:
        sub += f" Gap (Maria minus guest): {bs._pts(g)} points."
    foot = f"Not shown: {rest:.0f}% of comments (thanks, reactions, topic talk, no name). {SRC}".strip()
    if sq:
        fig.text(0.05, 0.96, wrap(head, 36), fontsize=14, fontweight="bold", color=ink, va="top", linespacing=1.25)
        fig.text(0.05, 0.835, wrap(sub, 62), fontsize=9, color=mut, va="top")
        fig.text(0.05, 0.02, wrap(foot, 80), fontsize=7.2, color=mut)
    else:
        fig.text(0.04, 0.93, head, fontsize=13, fontweight="bold", color=ink)
        fig.text(0.04, 0.865, sub, fontsize=8.5, color=mut)
        fig.text(0.04, 0.02, foot, fontsize=7, color=mut)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return True

TONE_MIN = 10       # a person's tone bar is drawn only when at least this many comments name only them


def tone_ok(r):
    return all(c in r and pd.notna(r[c]) for c in ("tone_maria_pos", "tone_maria_neg", "tone_guest_pos", "tone_guest_neg")) and \
        max(r.get("tone_maria_n") or 0, r.get("tone_guest_n") or 0) >= TONE_MIN


def tone_hidden(r):
    """Names of the groups whose tone bar is left out for having fewer than TONE_MIN comments: [] , ['Maria'] or [first name]."""
    out = []
    if (r.get("tone_maria_n") or 0) < TONE_MIN:
        out.append("Maria")
    if (r.get("tone_guest_n") or 0) < TONE_MIN:
        out.append(first_name(r.get("guest")))
    return out


def draw_tone(e, i, path, sq=False):
    """PNG for Substack: positive comments go up, negative go down, for Maria and for the guest (neutral is not drawn)."""
    r = e.iloc[i]
    if not tone_ok(r):
        return False
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    ink, mut = "#1d1d1f", "#5f5f66"
    pos = [r["tone_maria_pos"] * 100, r["tone_guest_pos"] * 100]
    neg = [r["tone_maria_neg"] * 100, r["tone_guest_neg"] * 100]
    ns = [int(r["tone_maria_n"]), int(r["tone_guest_n"])]
    fig, ax = plt.subplots(figsize=(SQ, SQ) if sq else (7, 5.4), dpi=180 if sq else 200, facecolor="white")
    if sq:
        fig.subplots_adjust(left=0.14, right=0.95, top=0.69, bottom=0.17)
    else:
        fig.subplots_adjust(left=0.13, right=0.95, top=0.78, bottom=0.17)
    shown = [nn >= TONE_MIN for nn in ns]
    top = max(max([p_ for p_, ok in zip(pos, shown) if ok]), 10)
    low = max(max([n_ for n_, ok in zip(neg, shown) if ok]), 5)
    for x, p_, n_, c, nn in zip((0, 1), pos, neg, (COL["maria"], COL["guest"]), ns):
        if nn < TONE_MIN:                       # too few comments: no bar and no percentages, only a dashed box that says why
            from matplotlib.patches import Rectangle
            ax.add_patch(Rectangle((x - 0.28, -low * 1.3), 0.56, top * 0.95 + low * 1.3, fill=False, ls=(0, (4, 3)), ec="#9a9aa2", lw=1.2))
            ax.text(x, top * 0.5, "Too few\ncomments\nto show", ha="center", va="center", fontsize=11, color=mut, linespacing=1.4)
            who = "Maria" if x == 0 else first_name(r["guest"])
            ax.text(x, -low * 0.25, f"only {nn} comment{'s' if nn != 1 else ''}\nnamed {who} alone", ha="center", va="top", fontsize=8.5, color=mut, linespacing=1.3)
            continue
        ax.bar(x, p_, color=c, width=0.55)
        ax.bar(x, -n_, color=c, alpha=0.55, width=0.55)
        ax.text(x, p_ + top * 0.03, f"{p_:.0f}%", ha="center", fontsize=12, fontweight="bold", color=ink)
        ax.text(x, -n_ - top * 0.03, f"{n_:.0f}%", ha="center", va="top", fontsize=12, fontweight="bold", color=ink)
    ax.axhline(0, color=ink, lw=1)
    ax.set_xticks([0, 1])
    ax.set_xticklabels([f"Maria\n({ns[0]} comments)", f"{str(r['guest'])[:26]}\n({ns[1]} comments)"], fontsize=10, color=ink)
    ax.set_xlim(-0.6, 1.6)
    ax.set_ylim(-(low * 1.5 + top * 0.12), top * 1.18)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{abs(v):.0f}%"))
    ax.grid(axis="y", color="#e6e6e6", lw=0.8)
    ax.set_axisbelow(True)
    for sp in ("top", "right", "bottom"):
        ax.spines[sp].set_visible(False)
    ax.spines["left"].set_color("#bbbbbb")
    ax.tick_params(length=0, labelsize=8.5, colors=mut)
    ax.tick_params(axis="x", labelsize=10, labelcolor=ink, pad=8)
    ax.text(1.58, top * 1.1, "\u25B2 positive", ha="right", fontsize=9, color=mut)
    ax.text(1.58, -(low * 1.5 + top * 0.08), "\u25BC negative", ha="right", fontsize=9, color=mut)
    if sq:
        fig.text(0.05, 0.96, wrap(f"How the comments felt: {r['guest']} episode", 36), fontsize=14, fontweight="bold", color=ink, va="top", linespacing=1.25)
        fig.text(0.05, 0.835, wrap("Share of comments naming only that person that read positive (up) or negative (down). "
                                   "Neutral comments are not drawn, so up + down is less than 100%. A person's bar needs at least 10 comments.", 62), fontsize=9, color=mut, va="top")
        fig.text(0.05, 0.03, SRC, fontsize=7.2, color=mut)
    else:
        fig.text(0.04, 0.93, f"How the comments felt: {r['guest']} episode", fontsize=13, fontweight="bold", color=ink)
        fig.text(0.04, 0.875, "Share of comments naming only that person that read positive (up) or negative (down).", fontsize=8.5, color=mut)
        fig.text(0.04, 0.835, "Neutral comments are not drawn, so up + down is less than 100%. A person's bar needs at least 10 comments.", fontsize=8.5, color=mut)
        fig.text(0.04, 0.03, SRC, fontsize=7, color=mut)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return True


MIN_EARLIER = 3        # earlier comparable episodes needed before the likes line is written
SAME_BAND = 0.10       # within 10% of the earlier average counts as "about the same"

# (column, label, how it is written, is it a percentage share, needs comparable views)
ACTIVITY = [
    ("comments_per_1k_views", "Comments per 1,000 views", False, True),
    ("commenters_per_1k_views", "Different commenters per 1,000 views", False, True),
    ("likes_per_1k_views", "Likes per 1,000 views", False, True),
    ("reply_share", "Comments that drew a reply", True, False),
    ("first_day_share", "Comments posted in the first 24 hours", True, False),
]


def _fmt(v, share):
    if share:
        return f"{float(v) * 100:.0f}%"
    return f"{float(v):.0f}" if float(v) >= 10 else f"{float(v):.1f}"


def activity(e, i):
    """[(column, label, this value, earlier average or None, number of earlier episodes, word)] for the measures that exist.
    The word is 'above', 'about the same as' or 'below' the earlier average (within SAME_BAND = about the same); it is left empty
    when fewer than MIN_EARLIER earlier episodes have the measure."""
    r = e.iloc[i]
    out = []
    for col, label, share, _ in ACTIVITY:
        if col not in e or pd.isna(r.get(col)):
            continue
        prev = e[(e["published"] < r["published"]) & e[col].notna()]
        if len(prev) >= MIN_EARLIER and float(prev[col].mean()) > 0:
            avg = float(prev[col].mean())
            rel = (float(r[col]) - avg) / avg
            word = "about the same as" if abs(rel) <= SAME_BAND else "above" if rel > 0 else "below"
            out.append((col, label, float(r[col]), avg, len(prev), word, share))
        else:
            out.append((col, label, float(r[col]), None, len(prev), "", share))
    return out


def activity_block(e, i):
    """Markdown: a small table, 'Activity at a glance', this episode against the earlier average. '' when nothing is available."""
    rows = activity(e, i)
    if not rows:
        return ""
    L = ["## Activity at a glance", "| Measure | This episode | Earlier episodes (average) |", "|---|---|---|"]
    for col, label, v, avg, k, word, share in rows:
        L.append(f"| {label} | {_fmt(v, share)} | " + (f"{_fmt(avg, share)} ({k} episodes)" if avg is not None else "not enough earlier episodes yet") + " |")
    L.append("")
    L.append("*These count people who commented or liked, not everyone who watched; silent viewers are in the views. Per-1,000-views rows appear "
             "only when the views were read soon after upload, so they are fair to compare.*\n")
    return "\n".join(L)


def draft_sentences(e, i):
    """Markdown: ready-to-edit sentences for Substack and LinkedIn built from this episode's numbers."""
    r = e.iloc[i]
    F = first_name(r["guest"])
    rows = {x[0]: x for x in activity(e, i)}

    def tail(col, unit_phrase, avg_phrase="the {avg} average for the {k} earlier episodes"):
        if col not in rows:
            return None
        _, _, v, avg, k, word, share = rows[col]
        base = unit_phrase.format(v=_fmt(v, share))
        if avg is None:
            return base + "."
        return base + f", {word} " + avg_phrase.format(avg=_fmt(avg, share), k=k) + "."

    S = []
    s1 = tail("comments_per_1k_views", f"The {F} episode drew {{v}} comments for every 1,000 views")
    s2 = tail("commenters_per_1k_views", "{v} different people commented for every 1,000 views", "the earlier average of {avg}")
    s3 = tail("likes_per_1k_views", "It earned {v} likes for every 1,000 views")
    s4 = None
    if "reply_share" in rows:
        _, _, v, avg, k, word, share = rows["reply_share"]
        s4 = f"{_fmt(v, True)} of comments drew a reply"
        if avg is not None:
            more = {"above": "more conversations than usual", "below": "fewer conversations than usual"}.get(word, "about as many conversations as usual")
            s4 += f" (the earlier average is {_fmt(avg, True)}), so the episode started {more}."
        else:
            s4 += "."
    s5 = None
    if "first_day_share" in rows:
        _, _, v, avg, k, word, share = rows["first_day_share"]
        s5 = f"{_fmt(v, True)} of the comments arrived within the first 24 hours" + (f", {word} the usual {_fmt(avg, True)}." if avg is not None else ".")
    S = [x for x in (s1, s2, s3, s4, s5) if x]
    L = [f"# Draft sentences: {r['guest']} episode (not for publishing as it is; edit and copy what you want)", ""]
    L.append("**Substack** (pick the ones that fit; each stands alone)")
    L += [f"- {x}" for x in S] or ["- (no activity numbers are available for this episode yet)"]
    L.append("")
    li = f"In the first 7 days of comments on the {F} episode, {pct(r['maria_share_all'])} named Maria and {pct(r['guest_share_all'])} named {F}."
    if pd.notna(r.get("maria_address_share")):
        li += f" Much of the Maria talk was thanks addressed to her ({pct(r['maria_address_share'])} of those comments speak to her)."
    pick = next((x for x in (s3, s1, s2) if x), None)
    L.append("**LinkedIn** (short)")
    L.append(f"- {li}" + (f" {pick}" if pick else ""))
    L.append("")
    L.append("*Say \"among people who commented\", not \"viewers think\": the numbers cover the people who spoke up. One episode is one data "
             "point, so write \"so far\" rather than \"always\".*\n")
    return "\n".join(L)


def reception_line(e, i):
    """One sentence: views, likes per 1,000 views, and how that compares with earlier episodes. '' when it cannot be said fairly
    (views not comparable, no like count, or fewer than MIN_EARLIER earlier episodes with a comparable count)."""
    r = e.iloc[i]
    v, lk, views = r.get("likes_per_1k_views"), r.get("video_likes"), r.get("views")
    if "likes_per_1k_views" not in e or pd.isna(v) or pd.isna(views):
        return ""
    prev = e[(e["published"] < r["published"]) & e["likes_per_1k_views"].notna()]
    if len(prev) < MIN_EARLIER:
        return ""
    avg = float(prev["likes_per_1k_views"].mean())
    rel = (float(v) - avg) / avg if avg > 0 else 0.0
    verdict = ("about the same as" if abs(rel) <= SAME_BAND else "above" if rel > 0 else "below")
    return (f"The {first_name(r['guest'])} episode had {int(views):,} views and **{float(v):.0f} likes per 1,000 views**, {verdict} the "
            f"{avg:.0f} average for the {len(prev)} earlier episodes. "
            "This is a reaction to the episode as a whole, not to Maria or the guest. It counts silent viewers too, so read it as "
            "\"this many in every 1,000 views ended in a like\", and compare episodes with each other rather than reading the number alone.")


def parse_requests(txt):
    """'Serena Williams (12), Oprah (3)' -> [('Serena Williams', 12), ('Oprah', 3)]"""
    out = []
    for m in re.finditer(r"\s*([^,]+?)\s*\((\d+)\)\s*(?:,|$)", str(txt or "")):
        out.append((m.group(1).strip(), int(m.group(2))))
    return out


def request_rows(e, i, table, top=8):
    """[(name, this_episode, earlier)] ranked by the total up to and including this episode. Uses guest_requests_table.csv; an episode
    with no names of its own (no column there) still shows the running totals carried over from earlier episodes."""
    r = e.iloc[i]
    this = dict(parse_requests(r.get("requested_top")))
    if table is None or not len(table):
        return [(n, c, 0) for n, c in sorted(this.items(), key=lambda kv: -kv[1])]
    name_col = table.columns[0]
    order = list(e.sort_values("published")["guest"])
    upto = order[: order.index(r["guest"]) + 1]
    cols = [g for g in upto if g in table.columns]            # episodes published up to this one (later episodes are not counted)
    t = pd.DataFrame({"name": table[name_col].astype(str)})
    t["this"] = table[r["guest"]].fillna(0).astype(int) if r["guest"] in table.columns else 0
    t["total"] = table[cols].fillna(0).sum(axis=1).astype(int) if cols else 0
    t = t.sort_values(["total", "this"], ascending=False)
    keep = t.head(top)
    extra = t[(t["this"] > 0) & ~t["name"].isin(keep["name"])].head(3)    # this episode's names must show even if small so far
    rows = [(x["name"], int(x["this"]), int(x["total"]) - int(x["this"])) for _, x in pd.concat([keep, extra]).iterrows()]
    rows.sort(key=lambda t: -(t[1] + t[2]))
    return [x for x in rows if x[1] + x[2] > 0]


def requests_note(r):
    """'6 comments asked for a guest; 3 of them named someone.' (the chart counts names, so it can show fewer than the comments asking)."""
    t, n = r.get("requests_total"), r.get("requests_naming_someone")
    if pd.isna(t) or pd.isna(n) or int(t) == 0:
        return ""
    t, n = int(t), int(n)
    return (f"{t} comment{'s' if t != 1 else ''} under the {first_name(r['guest'])} episode asked for a guest; "
            f"{n} of them named someone, the rest asked in general terms or named no one we could read.")


def draw_requests(e, i, path, table=None, sq=False):
    """PNG for Substack: guests viewers asked for, all-time total per name (bar), with this episode's part highlighted."""
    r = e.iloc[i]
    rows = request_rows(e, i, table)
    if not rows:
        return False
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    ink, mut = "#1d1d1f", "#5f5f66"
    n = len(rows)
    h = SQ if sq else 2.3 + 0.45 * n
    fig, ax = plt.subplots(figsize=(SQ if sq else 8, h), dpi=180 if sq else 200, facecolor="white")
    if sq:
        fig.subplots_adjust(left=0.33, right=0.92, top=0.70, bottom=0.14)
    else:
        fig.subplots_adjust(left=0.27, right=0.93, top=1 - 1.25 / h, bottom=0.85 / h + 0.05)
    ys = list(range(n))[::-1]
    top = max(a + b for _, a, b in rows)
    LIGHT = "#CBBFE0"
    for y, (nm, a, b) in zip(ys, rows):
        ax.barh(y, a, color=COL["request"], height=0.62, zorder=2, edgecolor="white", linewidth=2, label="This episode" if (a and not any(x[1] for x in rows[:rows.index((nm, a, b))])) else None)
        ax.barh(y, b, left=a, color=LIGHT, height=0.62, zorder=2, edgecolor="white", linewidth=2, label="Earlier episodes" if y == ys[0] else None)
        lab = f"{a + b}" + (f"  ({a} this episode)" if a and b else "")
        ax.text(a + b + top * 0.015, y, lab, va="center", fontsize=9.5, color=ink, fontweight="bold")
    ax.set_yticks(ys)
    ax.set_yticklabels([nm[:28] for nm, _, _ in rows], fontsize=9.5, color=ink)
    ax.set_xlim(0, top * 1.35)
    ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True, nbins=5))
    if sq and n < 5:                      # keep bars the same thickness as a full chart: leave the empty rows at the bottom
        ax.set_ylim(-0.5 - (5 - n), n - 0.5)
    ax.grid(axis="x", color="#e6e6e6", lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color("#bbbbbb")
    ax.tick_params(axis="both", length=0, labelsize=8.5, colors=mut)
    ax.set_xlabel("Comments asking for this guest (all counted episodes so far)", fontsize=8.5, color=mut)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, frameon=False, fontsize=8.5, handlelength=1, labelcolor=ink)
    if not sq:
        fig.text(0.04, 1 - 0.38 / h, "Guests viewers ask for", fontsize=13, fontweight="bold", color=ink)
    none_new = not any(a for _, a, _ in rows)
    first = (f"No guest was named under the {r['guest']} episode; the bars carry over the totals from earlier episodes." if none_new else
             f"Dark part = comments under the {r['guest']} episode; light part = earlier counted episodes. ")
    if sq:
        fig.text(0.05, 0.96, "Guests viewers ask for", fontsize=14, fontweight="bold", color=ink, va="top")
        fig.text(0.05, 0.885, wrap("\n".join(x for x in (first.strip(), requests_note(r), "Names are read by simple rules, so counts are approximate.") if x), 66), fontsize=8.5, color=mut, va="top")
        fig.text(0.05, 0.03, SRC, fontsize=7.2, color=mut)
    else:
        fig.text(0.04, 1 - 0.58 / h, "\n".join(x for x in (first.strip(), requests_note(r), "Names are read by simple rules, so counts are approximate.") if x), fontsize=7.5, color=mut, va="top")
        fig.text(0.04, 0.2 / h, SRC, fontsize=7, color=mut)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return True


def report(e, i, info, image=None, req_image=None, tone_image=None):
    r = e.iloc[i]
    rel = e[e["reliable"]]
    prev = rel[pd.to_datetime(rel["published"]) < pd.to_datetime(r["published"])]
    L = []
    L.append(f"# Pretty Tough with {r['guest']}: Maria or the guest?")
    L.append(f"*Episode published {bs._day(r['published'])}. Comments from the first 7 days: {int(r['n_comments']):,}.*\n")
    L.append(verdict_line(r) + "\n")
    if image:
        L.append(f"![What viewers wrote about in the {r['guest']} episode]({image})\n")
    L.append("## The numbers")
    L.append("| | Maria | " + str(r["guest"]) + " |\n|---|---|---|")
    L.append(f"| Named in (share of all comments) | {pct(r['maria_share_all'], 1)} | {pct(r['guest_share_all'], 1)} |")
    if pd.notna(r.get("both_share")):
        L.append(f"| of which named together | {pct(r['both_share'], 1)} | {pct(r['both_share'], 1)} |")
    if "gap_discussion" in r and pd.notna(r["gap_discussion"]):
        L.append(f"| Gap counting only comments that *discuss* rather than address (pts) | {bs._pts(r['gap_discussion'] * 100)} | |")
    if r.get("views_comparable") in (True, "True", "true", 1) and pd.notna(r.get("maria_per_1k_views")):
        L.append(f"| Comments per 1,000 views | {r['maria_per_1k_views']:.2f} | {r['guest_per_1k_views']:.2f} |")
    L.append("")
    if "maria_address_share" in r and pd.notna(r.get("maria_address_share")):
        L.append(f"Of the comments naming Maria, {pct(r['maria_address_share'])} speak *to* her (thanks, praise) rather than *about* her; "
                 f"for {r['guest']} it is {pct(r.get('guest_address_share'))}.\n")
    L.append("## Compared with the other episodes")
    if r["reliable"] and len(rel) >= 3:
        rank = int((rel["gap_pts"] > r["gap_pts"]).sum()) + 1
        L.append(f"- Gap rank: {ordinal(rank)} of {len(rel)} counted episodes (1st = Maria furthest ahead).")
        if len(prev) >= 2:
            L.append(f"- The average gap in the {len(prev)} earlier counted episodes was {bs._pts(prev['gap_pts'].mean())} points; this one is "
                     f"{bs._pts(r['gap_pts'])}.")
        v = bs.verdict_numbers(e)
        L.append(f"- Season so far ({v['n']} counted episodes): average gap {bs._pts(v['mean'])} points "
                 f"(95% range {bs._pts(v['lo'])} to {bs._pts(v['hi'])}); Maria ahead in {v['k']} of {v['kn']}.")
    else:
        L.append("- Not enough data for a comparison yet.")
    L.append("")
    rename = {"Maria": "only Maria named", "Guest": f"only {first_name(r['guest'])} named", "Both": "both named"}
    mix = [(rename.get(n, n), r.get(c)) for _, n, c in bs.MIX if c in r and pd.notna(r.get(c))]
    if mix:
        other = max(0.0, 1 - sum(v for _, v in mix))
        L.append("## What else people wrote about")
        L.append(", ".join(f"{n} {pct(v)}" for n, v in mix) + f", everything else {pct(other)}. "
                 "(Show = about the episode or show; Request = asking for a future guest; everything else is thanks, reactions, topic talk "
                 "and she/her comments with no name.)\n")
    if tone_image:
        L.append("## How the comments felt")
        L.append(f"![Positive and negative comments in the {r['guest']} episode]({tone_image})\n")
        L.append("*Tone is an automatic score (VADER), not a reading of each comment: it misses sarcasm and context. Much of the positive "
                 "tone toward Maria is thanks addressed to her, so read it as warmth, not as who is more interesting.*\n")
        hid = tone_hidden(r)
        if hid:
            cnt = {"Maria": int(r.get("tone_maria_n") or 0)}
            cnt[first_name(r["guest"])] = int(r.get("tone_guest_n") or 0)
            L.append("*" + " and ".join(f"{h}'s bar is left out: only {cnt[h]} comment{'s' if cnt[h] != 1 else ''} named only {h}" for h in hid)
                     + f"; a percentage from fewer than {TONE_MIN} comments would say too little.*\n")
    rec = reception_line(e, i)
    if rec:
        L.append("## How the whole episode was received")
        L.append(rec + "\n")
    ab = activity_block(e, i)
    if ab:
        L.append(ab)
    kw = str(r.get("keywords") or "").strip()
    if kw and kw.lower() != "nan":
        L.append(f"**Words that stood out in this episode's comments:** {kw}\n")
    rq = str(r.get("requested_top") or "").strip()
    has_rq = bool(rq) and rq.lower() != "nan"
    if has_rq or req_image:
        L.append("## Who viewers want next")
        if req_image:
            L.append(f"![Guests viewers asked for after the {r['guest']} episode]({req_image})\n")
        note = requests_note(r)
        if note:
            L.append(f"*{note}*\n")
        if has_rq:
            L.append(f"**Guests viewers asked for:** {rq}\n")
        else:
            L.append(f"*No guest was named in the comments on this episode. The chart shows the running totals from earlier episodes.*\n")
    L.append("## How to read this")
    L.append("- 'Named' is not 'interested': many Maria comments are thanks addressed to the host.")
    L.append("- Only comments that name Maria, the guest, or both go into the gap; a comment naming both counts for both and cancels out.")
    L.append("- One episode is one data point; the 95% range shows how much a number this size can wobble. Watch the season trend, not one week.")
    L.append(f"- {bs.ACCURACY}")
    rv = info.get("rules_versions") or []
    L.append("\n---")
    L.append("*Method: public top-level comments on the video, first 7 days after upload, read through the YouTube API Services; sorted by "
             "keyword rules" + (f" (version {', '.join(rv)})" if rv else "") + f". Raw text is deleted after 28 days; only counts are kept. "
             f"Data from YouTube ([Terms of Service]({YT_TERMS}), [Google Privacy Policy]({G_PRIVACY})). "
             "Independent project, not affiliated with Maria Sharapova, Pretty Tough or YouTube.*")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--guest", default=None, help="part of the guest name")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--formats", choices=["substack", "linkedin", "both"], default="both",
                    help="substack = Markdown report + wide charts; linkedin = square 1080 x 1080 charts only; both (default)")
    a = ap.parse_args()
    p = os.path.join(a.out, "episode_summary.csv")
    if not os.path.exists(p):
        raise SystemExit(f"{p} not found: run the pipeline first.")
    e = bs.prepare(pd.read_csv(p))
    e = e[e["gap_pts"].notna()].reset_index(drop=True)
    if e.empty:
        raise SystemExit("No episodes with comment counts yet.")
    info = {}
    ip = os.path.join(a.out, "run_info.json")
    if os.path.exists(ip):
        info = json.load(open(ip, encoding="utf-8"))
    if a.all:
        idx = list(range(len(e)))
    elif a.guest:
        idx = [i for i, g in enumerate(e["guest"]) if a.guest.lower() in str(g).lower()]
        if not idx:
            raise SystemExit(f"No episode with a guest matching '{a.guest}'.")
    else:
        idx = [len(e) - 1]
    tp = os.path.join(a.out, "guest_requests_table.csv")
    table = pd.read_csv(tp) if os.path.exists(tp) else None
    d = os.path.join(a.out, "reports")
    os.makedirs(d, exist_ok=True)
    for i in idx:
        base = os.path.join(d, f"{e.loc[i, 'published']}_{slug(e.loc[i, 'guest'])}")
        base_name = os.path.basename(base)
        md = None
        if a.formats in ("substack", "both"):
            img = base_name + ".png" if draw_chart(e, i, base + ".png") else None
            timg = base_name + "_tone.png" if draw_tone(e, i, base + "_tone.png") else None
            rimg = base_name + "_requests.png" if draw_requests(e, i, base + "_requests.png", table) else None
            md = report(e, i, info, img, rimg, timg)
            path = base + ".md"
            open(path, "w", encoding="utf-8").write(md)
            print("Wrote", path)
        with open(base + "_sentences.md", "w", encoding="utf-8") as f:       # separate file, so it is never pasted by accident with the report
            f.write(draft_sentences(e, i))
        print("Wrote", base + "_sentences.md")
        if a.formats in ("linkedin", "both"):
            ok = [draw_chart(e, i, base + "_linkedin.png", sq=True),
                  draw_tone(e, i, base + "_tone_linkedin.png", sq=True),
                  draw_requests(e, i, base + "_requests_linkedin.png", table, sq=True)]
            print(f"Wrote {sum(map(bool, ok))} LinkedIn image(s) for {e.loc[i, 'guest']}")
    if len(idx) == 1 and md:
        print("\n" + md)


if __name__ == "__main__":
    main()
