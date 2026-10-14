"""Build the public results page (GitHub Pages) from the pipeline's output folder.

Usage:  python build_site.py [--out out] [--site site]

Reads out/ (written by run_weekly.py) and writes site/index.html plus a few CSVs. The charts are drawn here as plain inline SVG
(no plotting library, no images), so they work on phones, follow light/dark mode, have hover tooltips and a table view, and
each has a "Save as image" button that renders a PNG in the visitor's browser.
Only derived, episode-level numbers are published: never comment text, never usernames, never tagged_comments.csv or the alias
audit. The wording in the constants below (TITLE, INTRO, CAVEATS, ACCURACY, ...) is yours to edit.
"""
import argparse
import html
import json
import math
import os
import shutil
from datetime import date

import numpy as np
import pandas as pd

TITLE = "Pretty Tough: who do viewers talk about, the host or the guest?"
INTRO = ("A weekly check of the YouTube comments on each Pretty Tough episode (first 7 days after upload): do viewers name "
         "Maria Sharapova more often than the guest? Each comment is sorted by simple rules; no one reads individual comments here.")
CAVEATS = [
    "<b>Named is not the same as interested.</b> Many Maria comments are thanks addressed to the host. The 'only discussion' line "
    "in the robustness chart leaves those out.",
    "Only comments that name Maria, the guest, or both go into the gap. Requests for future guests, comments about the show, "
    "'she/her' comments with no name and everything else are counted separately.",
    "Tags come from keyword rules that were checked on small hand-labelled samples; they will be wrong some of the time. "
    "Guest nicknames and misspellings are added by hand, so a guest can be under-counted.",
    "These are the episodes in the playlist, not all podcasts. Guest fame and the guest's own audience change the picture.",
    "An episode with fewer than 10 comments naming Maria or the guest is drawn hollow and is left out of the averages.",
]
# Edit this when you re-check the rules on new labelled samples (keep the 'in-sample' warning while it was tuned on them).
ACCURACY = ("On comments I labelled by hand, the rules agreed with my label about 83% of the time. That figure is optimistic, "
            "because the rules were tuned on those same comments.")
MIN_RELIABLE = 10          # same cut-off as the pipeline (analyze_youtube.per_episode min_named)
DOWNLOADS = [("episode_summary.csv", "Per-episode summary"), ("guest_requests_table.csv", "Requested guests, by episode"),
             ("guest_requests.csv", "Requested guests, running totals"), ("cumulative.csv", "Cumulative result"),
             ("verdict.txt", "Verdict text")]
EXTRA_HTML = [("who_gets_talked_about", "Interactive version of the per-episode chart")]   # optional Plotly pages, if the run made them
COLS = [("guest", "Guest", "t"), ("published", "Published", "t"), ("n_comments", "Comments", "i"),
        ("maria_share_all", "Maria", "p"), ("guest_share_all", "Guest", "p"), ("both_share", "Both", "p"),
        ("gap_all", "Gap", "g"), ("gap_discussion", "Gap (discussion only)", "g"),
        ("comments_per_1k_views", "Comments / 1k views", "f"), ("keywords", "Keyword candidates", "k"),
        ("requested_top", "Most requested guests", "k")]
VARIANTS = [("gap_all", "Share of comments"), ("gap_likes", "Weighted by likes"), ("gap_focus", "Both by focus"),
            ("gap_discussion", "Only discussion"), ("gap_words", "Share of words"), ("gap_unnamed_worst", "Worst case")]
MIX = [("maria", "Maria", "share_maria"), ("guest", "Guest", "share_guest"), ("both", "Both", "share_both"),
       ("show", "Show", "share_show"), ("request", "Request", "share_request")]
YT_TERMS = "https://www.youtube.com/t/terms"
G_PRIVACY = "https://policies.google.com/privacy"
SOURCE_LINE = "Source: public YouTube comments on Pretty Tough"

# Colours: validated with the dataviz skill's validate_palette (light on #FFFFFF, dark on #161616). Change them only by re-running it.
STYLE = """
:root{--bg:#fff;--fg:#1d1d1f;--mut:#5f5f66;--line:#dcdcdc;--card:#f6f6f6;--grid:#e6e6e6;
--maria:#C8553D;--guest:#1B74B8;--both:#B8860B;--show:#2A9D6F;--request:#7B5EA7;--other:#C9C9C9}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--fg:#eee;--mut:#a8a8ae;--line:#333;--card:#202020;--grid:#2c2c2c;
--maria:#D6634A;--guest:#4A9BDD;--both:#B08410;--show:#2F9E72;--request:#9A78D0;--other:#5a5a5a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:760px;margin:0 auto;padding:24px 16px 64px}h1{font-size:1.6rem;line-height:1.25;margin:.2em 0}
h2{margin-top:2.4em;font-size:1.2rem}h3{font-size:1rem;margin:0 0 .2em}
.mut{color:var(--mut);font-size:.9rem}.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 16px}
.card ul{margin:.3em 0;padding-left:1.2em}a{color:var(--guest)}.scroll{overflow-x:auto}
.hero{display:flex;gap:16px;align-items:baseline;flex-wrap:wrap;margin:.4em 0}.hero b{font-size:2.2rem;line-height:1}
.dot{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:6px;vertical-align:baseline}
figure{margin:1.4em 0}figcaption{font-size:.9rem;color:var(--mut);margin-top:.3em}
.bar{display:flex;justify-content:space-between;align-items:baseline;gap:8px;flex-wrap:wrap}
button{font:inherit;font-size:.82rem;color:var(--fg);background:var(--card);border:1px solid var(--line);border-radius:6px;padding:3px 10px;cursor:pointer}
button:focus-visible,[data-tip]:focus-visible{outline:2px solid var(--guest);outline-offset:1px}
.ch{display:block;width:100%;height:auto;font:12px system-ui,-apple-system,Segoe UI,Roboto,sans-serif;overflow:visible}
.lay-n{display:none}.lay-n .ch{max-width:520px;margin:0 auto}.lay-w .ch{max-width:728px}
@media (max-width:699px){.lay-w{display:none}.lay-n{display:block}}
.ch text{fill:var(--fg)}.ch .mu{fill:var(--mut)}.ch .gl{stroke:var(--grid);stroke-width:1}.ch .zero{stroke:var(--mut);stroke-width:1}
.ch .ln{stroke-width:2;fill:none}.ch .dash{stroke:var(--mut);stroke-width:1;stroke-dasharray:4 3}
.ch .hit{fill:transparent}.ch [data-tip]:hover .hl,.ch [data-tip]:focus .hl{fill:var(--grid)}
.ch .hl{fill:transparent}
.m-maria{fill:var(--maria)}.m-guest{fill:var(--guest)}.m-both{fill:var(--both)}.m-show{fill:var(--show)}.m-request{fill:var(--request)}.m-other{fill:var(--other)}
.s-maria{stroke:var(--maria)}.s-guest{stroke:var(--guest)}.s-both{stroke:var(--both)}.s-show{stroke:var(--show)}.s-request{stroke:var(--request)}
.fade{fill-opacity:.5}.hollow{fill:var(--bg);stroke-width:2}.seg{stroke:var(--bg);stroke-width:2}.ring{stroke:var(--bg);stroke-width:2}
.band{fill:var(--maria);fill-opacity:.18}.faint{opacity:.55}
details{margin:.5em 0}summary{cursor:pointer;font-size:.9rem;color:var(--mut)}
table{border-collapse:collapse;width:100%;font-size:.86rem}th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}
th:first-child,td:first-child,td.k,th.k{text-align:left}th{position:sticky;top:0;background:var(--bg)}
td:first-child{position:sticky;left:0;background:var(--bg)}td.n{white-space:nowrap}.pos{color:var(--maria);font-weight:600}.neg{color:var(--guest);font-weight:600}
#tip{position:fixed;z-index:9;pointer-events:none;background:var(--fg);color:var(--bg);font-size:.82rem;line-height:1.35;padding:6px 9px;border-radius:6px;
max-width:260px;display:none}#tip b{display:block}
"""

JS = r"""
(function(){
var tip=document.getElementById('tip');
function show(el,x,y){var p=el.getAttribute('data-tip').split('|');tip.innerHTML='<b></b>'+p.slice(1).map(function(){return '<span></span><br>'}).join('');
 tip.firstChild.textContent=p[0];var s=tip.querySelectorAll('span');for(var i=0;i<s.length;i++)s[i].textContent=p[i+1];
 tip.style.display='block';var r=tip.getBoundingClientRect();
 var left=Math.min(Math.max(8,x+12),window.innerWidth-r.width-8),top=y-r.height-12;if(top<8)top=y+16;tip.style.left=left+'px';tip.style.top=top+'px';}
function hide(){tip.style.display='none';}
document.addEventListener('pointermove',function(e){var t=e.target.closest&&e.target.closest('[data-tip]');if(t)show(t,e.clientX,e.clientY);else hide();});
document.addEventListener('pointerdown',function(e){var t=e.target.closest&&e.target.closest('[data-tip]');if(t)show(t,e.clientX,e.clientY);else hide();});
document.addEventListener('focusin',function(e){var t=e.target;if(t.getAttribute&&t.getAttribute('data-tip')){var b=t.getBoundingClientRect();show(t,b.left+b.width/2,b.top);}});
document.addEventListener('focusout',hide);
document.addEventListener('keydown',function(e){if(e.key==='Escape')hide();});
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;');}
function save(fig){
 var svgs=fig.querySelectorAll('svg'),svg=null;for(var i=0;i<svgs.length;i++){if(svgs[i].getBoundingClientRect().width>0){svg=svgs[i];break;}}
 if(!svg)return;
 var vb=svg.viewBox.baseVal,w=vb.width,h=vb.height,clone=svg.cloneNode(true);
 var src=svg.querySelectorAll('*'),dst=clone.querySelectorAll('*');
 var props=['fill','fill-opacity','stroke','stroke-width','stroke-opacity','stroke-dasharray','opacity','font-family','font-size','font-weight','text-anchor'];
 for(var j=0;j<src.length;j++){var cs=getComputedStyle(src[j]),st='';props.forEach(function(p){st+=p+':'+cs.getPropertyValue(p)+';';});dst[j].setAttribute('style',st);}
 clone.setAttribute('xmlns','http://www.w3.org/2000/svg');clone.setAttribute('x','0');clone.setAttribute('y','40');clone.setAttribute('width',w);clone.setAttribute('height',h);
 var bs=getComputedStyle(document.body),H=h+68,font=bs.fontFamily.replace(/"/g,"'");
 var out='<svg xmlns="http://www.w3.org/2000/svg" width="'+w*2+'" height="'+H*2+'" viewBox="0 0 '+w+' '+H+'"><rect width="'+w+'" height="'+H+'" fill="'+bs.backgroundColor+'"/>'
  +'<text x="12" y="26" font-family="'+font+'" font-size="15" font-weight="600" fill="'+bs.color+'">'+esc(fig.getAttribute('data-title'))+'</text>'
  +new XMLSerializer().serializeToString(clone)
  +'<text x="12" y="'+(H-12)+'" font-family="'+font+'" font-size="11" fill="'+bs.color+'" fill-opacity=".7">'+esc(fig.getAttribute('data-source'))+'</text></svg>';
 var img=new Image();img.onload=function(){var c=document.createElement('canvas');c.width=w*2;c.height=H*2;c.getContext('2d').drawImage(img,0,0,w*2,H*2);
  c.toBlob(function(b){var a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=(fig.id||'chart')+'.png';document.body.appendChild(a);a.click();a.remove();});};
 img.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(out);
}
document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('button[data-save]');if(b)save(b.closest('figure'));});
})();
"""


# ---------------------------------------------------------------- small helpers
def _read(out, name):
    p = os.path.join(out, name)
    return pd.read_csv(p) if os.path.exists(p) else None


def _e(s):
    return html.escape(str(s), quote=True)


def _fmt(v, kind):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if kind == "p":
        return f"{v:.1%}"
    if kind == "g":
        cls = "pos" if v > 0 else "neg" if v < 0 else ""
        return f'<span class="{cls}">{v * 100:+.1f} pts</span>'
    if kind == "f":
        return f"{v:.2f}"
    if kind == "i":
        return f"{int(v):,}"
    return html.escape(str(v))


def _day(s):
    try:
        return pd.to_datetime(s).strftime("%b %d").replace(" 0", " ")
    except Exception:
        return str(s)


def _trunc(s, k):
    s = str(s)
    return s if len(s) <= k else s[: k - 1] + "…"


def _pts(v, d=1):
    return f"{v:+.{d}f}"


def nice_ticks(lo, hi, target=5):
    span = hi - lo
    raw = span / max(target, 1)
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    t0 = math.ceil(lo / step - 1e-9) * step
    out, v = [], t0
    while v <= hi + 1e-9:
        out.append(round(v, 10))
        v += step
    return out


def _tick_label(v):
    return f"{v:g}"


def boot_ci(x, n=4000, seed=12345):
    x = np.asarray(x, dtype=float)
    rng = np.random.default_rng(seed)
    means = rng.choice(x, size=(n, len(x)), replace=True).mean(axis=1)
    return np.percentile(means, [2.5, 97.5])


def sign_test(x):
    x = np.asarray(x, dtype=float)
    x = x[x != 0]
    n, k = len(x), int((x > 0).sum())
    if n == 0:
        return n, k, float("nan")
    hi = sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n
    lo = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return n, k, min(1.0, 2 * min(hi, lo))


# ---------------------------------------------------------------- data prep
def prepare(e):
    """Add per-episode interval columns (in percentage points) and make sure `reliable` exists."""
    e = e.copy()
    if "published" in e:
        e = e.sort_values("published").reset_index(drop=True)
    if "reliable" in e:
        e["reliable"] = e["reliable"].astype(str).str.lower().isin(["true", "1", "yes"])
    elif "n_named" in e:
        e["reliable"] = e["n_named"] >= MIN_RELIABLE
    else:
        e["reliable"] = True
    pm = e["only_maria_share"] if "only_maria_share" in e else e.get("share_maria")
    pg = e["only_guest_share"] if "only_guest_share" in e else e.get("share_guest")
    if pm is not None and pg is not None and "n_comments" in e:
        gap = pm - pg
        var = (pm + pg - gap ** 2).clip(lower=0) / e["n_comments"].clip(lower=1)    # multinomial: Var(pM - pG) = (pM + pG - (pM - pG)^2) / n
        e["gap_pts"] = e["gap_all"] * 100 if "gap_all" in e else gap * 100
        e["se_pts"] = np.sqrt(var) * 100
        e["lo_pts"], e["hi_pts"] = e["gap_pts"] - 1.96 * e["se_pts"], e["gap_pts"] + 1.96 * e["se_pts"]
    return e


def verdict_numbers(e):
    r = e[e["reliable"]]
    x = r["gap_all"].dropna().values if "gap_all" in r else np.array([])
    out = {"n": len(x), "n_all": len(e)}
    if len(x):
        lo, hi = boot_ci(x) if len(x) > 1 else (x[0], x[0])
        n, k, p = sign_test(x)
        out.update(mean=x.mean() * 100, lo=lo * 100, hi=hi * 100, k=k, kn=n, p=p)
    return out


def headline(v):
    """One plain-English sentence from the primary measure (gap_all over reliable episodes)."""
    if v["n"] < 3:
        return ("Too early to say.", f"Only {v['n']} episode{'s' if v['n'] != 1 else ''} so far "
                f"{'has' if v['n'] == 1 else 'have'} at least {MIN_RELIABLE} comments naming Maria or the guest; the test needs at least 3.", None)
    m, lo, hi = v["mean"], v["lo"], v["hi"]
    side = "Maria" if m > 0 else "the guest"
    if lo > 0 or hi < 0:
        txt = (f"Viewers name {'Maria' if lo > 0 else 'the guest'} more often. Across {v['n']} episodes, comments naming "
               f"{'Maria' if lo > 0 else 'the guest'} outnumber those naming {'the guest' if lo > 0 else 'Maria'} by "
               f"{abs(m):.1f} percentage points of all comments on average (95% range {_pts(lo)} to {_pts(hi)}).")
        return ("A clear difference so far.", txt, "maria" if lo > 0 else "guest")
    txt = (f"On average, comments naming {side} are {abs(m):.1f} points more common, but the 95% range ({_pts(lo)} to {_pts(hi)}) "
           f"includes zero, so the data do not yet show that either is named more. {v['n']} episodes so far.")
    return ("No clear difference so far.", txt, "maria" if m > 0 else "guest")


def robustness(e):
    r = e[e["reliable"]]
    rows = []
    for col, label in VARIANTS:
        if col not in r:
            continue
        x = r[col].dropna().values
        if len(x) < 2:
            continue
        lo, hi = boot_ci(x)
        n, k, p = sign_test(x)
        rows.append({"label": label, "mean": x.mean() * 100, "lo": lo * 100, "hi": hi * 100, "k": k, "n": n})
    return rows


def cumulative_rows(e, min_k=3):
    r = e[e["reliable"]].sort_values("published") if "published" in e else e[e["reliable"]]
    rows = []
    for k in range(min_k, len(r) + 1):
        x = r["gap_all"].iloc[:k].values
        lo, hi = boot_ci(x, n=2000)
        rows.append({"k": k, "guest": r["guest"].iloc[k - 1], "mean": x.mean() * 100, "lo": lo * 100, "hi": hi * 100})
    return rows


# ---------------------------------------------------------------- SVG building blocks
class Lay:
    """Two layouts per chart: wide (viewBox 728) and narrow (viewBox 400); CSS shows one, so text stays at a readable size."""

    def __init__(self, narrow):
        self.narrow = narrow
        self.W = 400 if narrow else 728
        self.left = 112 if narrow else 188
        self.right = 14 if narrow else 74
        self.row = 30 if narrow else 26
        self.lab = 16 if narrow else 28           # max label characters

    @property
    def plot_w(self):
        return self.W - self.left - self.right


def legend(items, W, x0=12, y0=10):
    """items: (kind, cls, text). Flowing legend that wraps at W. Returns (svg, height)."""
    x, y, parts = x0, y0, []
    for kind, cls, text in items:
        w = 18 + len(text) * 6.4 + 14
        if x + w > W and x > x0:
            x, y = x0, y + 20
        if kind == "dot":
            parts.append(f'<circle cx="{x + 6}" cy="{y}" r="5" class="m-{cls}"/>')
        elif kind == "hollow":
            parts.append(f'<circle cx="{x + 6}" cy="{y}" r="4.5" class="hollow s-{cls}"/>')
        elif kind == "box":
            parts.append(f'<rect x="{x}" y="{y - 5}" width="12" height="10" rx="2" class="m-{cls}"/>')
        elif kind == "line":
            parts.append(f'<line x1="{x}" x2="{x + 12}" y1="{y}" y2="{y}" class="ln s-{cls}"/>')
        parts.append(f'<text x="{x + 18}" y="{y + 4}">{_e(text)}</text>')
        x += w
    return "".join(parts), y + 14


def x_axis(sx, ticks, y_top, y_bot, fmt=_tick_label):
    g = []
    for t in ticks:
        x = sx(t)
        g.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y_top}" y2="{y_bot}" class="gl"/>')
        g.append(f'<text x="{x:.1f}" y="{y_bot + 15}" text-anchor="middle" class="mu">{fmt(t)}</text>')
    return "".join(g)


def svg(w, h, body, label):
    return f'<svg class="ch" viewBox="0 0 {w} {h:.0f}" role="img" aria-label="{_e(label)}">{body}</svg>'


def both_layouts(fn, *a):
    return f'<div class="lay-w">{fn(False, *a)}</div><div class="lay-n">{fn(True, *a)}</div>'


def tip_attr(*lines):
    return _e("|".join(lines))


def _domain(vals, pad=0.08, zero=False, sym=False):
    lo, hi = min(vals), max(vals)
    if zero:
        lo = min(lo, 0)
        hi = max(hi, 0)
    if sym:
        m = max(abs(lo), abs(hi))
        lo, hi = -m, m
    span = (hi - lo) or 1
    lo, hi = lo - span * pad, hi + span * pad
    ticks = nice_ticks(lo, hi)
    return min(lo, ticks[0]), max(hi, ticks[-1]), ticks


# ---------------------------------------------------------------- charts
def chart_gap(narrow, e, v):
    L = Lay(narrow)
    d = e.dropna(subset=["gap_pts"]).reset_index(drop=True)
    lo, hi, ticks = _domain(list(d["lo_pts"]) + list(d["hi_pts"]) + [0], sym=True)
    sx = lambda val: L.left + (val - lo) / (hi - lo) * L.plot_w
    leg, lh = legend([("dot", "maria", "Maria named more"), ("dot", "guest", "Guest named more"),
                      ("hollow", "maria", f"Under {MIN_RELIABLE} named comments")], L.W)
    top = lh + 6
    bot = top + len(d) * L.row
    b = [leg, x_axis(sx, ticks, top, bot, lambda t: f"{t:+g}" if t else "0")]
    b.append(f'<line x1="{sx(0):.1f}" x2="{sx(0):.1f}" y1="{top}" y2="{bot}" class="zero"/>')
    if "mean" in v and v["n"] >= 3:
        mx = sx(v["mean"])
        b.append(f'<line x1="{mx:.1f}" x2="{mx:.1f}" y1="{top}" y2="{bot}" class="dash"/>')
    for i, r in enumerate(d.to_dict("records")):
        cy = top + i * L.row + L.row / 2
        side = "maria" if r["gap_pts"] >= 0 else "guest"
        rel = bool(r["reliable"])
        tip = tip_attr(f"{r['guest']} · {_day(r['published'])}",
                       f"Gap {_pts(r['gap_pts'])} pts (95% range {_pts(r['lo_pts'])} to {_pts(r['hi_pts'])})",
                       f"{int(r['n_comments']):,} comments, {int(r['n_named']) if 'n_named' in r and pd.notna(r['n_named']) else '?'} naming Maria or the guest"
                       + ("" if rel else ". Too few to count in the averages"))
        dot = (f'<circle cx="{sx(r["gap_pts"]):.1f}" cy="{cy:.1f}" r="5" class="{"m-" + side if rel else "hollow"} s-{side}"/>')
        b.append(f'<g data-tip="{tip}" tabindex="0" role="img" aria-label="{tip}" class="{"" if rel else "faint"}">'
                 f'<rect x="0" y="{cy - L.row / 2:.1f}" width="{L.W}" height="{L.row}" class="hl"/>'
                 f'<text x="{L.left - 10}" y="{cy + 4:.1f}" text-anchor="end">{_e(_trunc(r["guest"], L.lab))}</text>'
                 f'<line x1="{sx(r["lo_pts"]):.1f}" x2="{sx(r["hi_pts"]):.1f}" y1="{cy:.1f}" y2="{cy:.1f}" class="ln s-{side}"/>{dot}'
                 + (f'<text x="{L.W - 4}" y="{cy + 4:.1f}" text-anchor="end" class="mu">{_pts(r["gap_pts"])}</text>' if not narrow else "")
                 + "</g>")
    b.append(f'<text x="{L.left}" y="{bot + 34}" class="mu">← guest named more</text>'
             f'<text x="{L.left + L.plot_w}" y="{bot + 34}" text-anchor="end" class="mu">Maria named more →</text>')
    if "mean" in v and v["n"] >= 3:
        b.append(f'<text x="{L.left}" y="{bot + 52}" class="mu">Dashed line: average of the counted episodes. Points: percentage points of all comments.</text>' if not narrow else
                 f'<text x="{L.left - 90}" y="{bot + 52}" class="mu">Dashed line: average of counted episodes (points of all comments)</text>')
        h = bot + 62
    else:
        h = bot + 44
    return svg(L.W, h, "".join(b), "Gap between comments naming Maria and the guest, per episode")


def chart_robust(narrow, rows):
    L = Lay(narrow)
    L.left = 132 if narrow else 150
    L.right = 14 if narrow else 80
    lo, hi, ticks = _domain([r["lo"] for r in rows] + [r["hi"] for r in rows] + [0], sym=True)
    sx = lambda val: L.left + (val - lo) / (hi - lo) * L.plot_w
    top = 8
    bot = top + len(rows) * L.row
    b = [x_axis(sx, ticks, top, bot, lambda t: f"{t:+g}" if t else "0"),
         f'<line x1="{sx(0):.1f}" x2="{sx(0):.1f}" y1="{top}" y2="{bot}" class="zero"/>']
    for i, r in enumerate(rows):
        cy = top + i * L.row + L.row / 2
        side = "maria" if r["mean"] >= 0 else "guest"
        tip = tip_attr(r["label"], f"Average gap {_pts(r['mean'])} pts (95% range {_pts(r['lo'])} to {_pts(r['hi'])})",
                       f"Maria ahead in {r['k']} of {r['n']} episodes")
        b.append(f'<g data-tip="{tip}" tabindex="0" role="img" aria-label="{tip}">'
                 f'<rect x="0" y="{cy - L.row / 2:.1f}" width="{L.W}" height="{L.row}" class="hl"/>'
                 f'<text x="{L.left - 10}" y="{cy + 4:.1f}" text-anchor="end">{_e(_trunc(r["label"], 20))}</text>'
                 f'<line x1="{sx(r["lo"]):.1f}" x2="{sx(r["hi"]):.1f}" y1="{cy:.1f}" y2="{cy:.1f}" class="ln s-{side}"/>'
                 f'<circle cx="{sx(r["mean"]):.1f}" cy="{cy:.1f}" r="5" class="m-{side}"/>'
                 + (f'<text x="{L.W - 4}" y="{cy + 4:.1f}" text-anchor="end" class="mu">{r["k"]}/{r["n"]} eps</text>' if not narrow else "")
                 + "</g>")
    b.append(f'<text x="{L.left}" y="{bot + 34}" class="mu">← guest named more</text>'
             f'<text x="{L.left + L.plot_w}" y="{bot + 34}" text-anchor="end" class="mu">Maria named more →</text>')
    return svg(L.W, bot + 44, "".join(b), "Average gap under six different ways of measuring it")


def chart_mix(narrow, e):
    L = Lay(narrow)
    d = e.reset_index(drop=True)
    items = [("box", k, name) for k, name, _ in MIX] + [("box", "other", "Everything else")]
    leg, lh = legend(items, L.W)
    top = lh + 6
    bot = top + len(d) * L.row
    sx = lambda val: L.left + val / 100 * L.plot_w
    b = [leg, x_axis(sx, [0, 25, 50, 75, 100], top, bot, lambda t: f"{t:g}%")]
    for i, r in enumerate(d.to_dict("records")):
        cy = top + i * L.row + L.row / 2
        vals = [(k, name, float(r.get(col) or 0) * 100) for k, name, col in MIX]
        vals.append(("other", "Everything else", max(0.0, 100 - sum(v[2] for v in vals))))
        tip = tip_attr(f"{r['guest']} · {_day(r['published'])}", *[f"{n}: {x:.0f}%" for _, n, x in vals])
        segs, x0 = [], 0.0
        for k, name, x in vals:
            if x > 0:
                segs.append(f'<rect x="{sx(x0):.1f}" y="{cy - 7:.1f}" width="{max(sx(x0 + x) - sx(x0), 0):.1f}" height="14" class="m-{k} seg"/>')
            x0 += x
        b.append(f'<g data-tip="{tip}" tabindex="0" role="img" aria-label="{tip}">'
                 f'<rect x="0" y="{cy - L.row / 2:.1f}" width="{L.W}" height="{L.row}" class="hl"/>'
                 f'<text x="{L.left - 10}" y="{cy + 4:.1f}" text-anchor="end">{_e(_trunc(r["guest"], L.lab))}</text>{"".join(segs)}</g>')
    return svg(L.W, bot + 24, "".join(b), "What each episode's comments are about, as a share of all comments")


def chart_tone(narrow, d):
    """Positive comments up (wide) or right (narrow), negative down or left, Maria and guest side by side per episode."""
    n = len(d)
    rows = d.to_dict("records")
    pmax = max(max(r["tone_maria_pos"], r["tone_guest_pos"]) for r in rows) * 100
    nmax = max(max(r["tone_maria_neg"], r["tone_guest_neg"]) for r in rows) * 100
    leg, lh = legend([("box", "maria", "Maria"), ("box", "guest", "Guest"), ("box", "other", "Lighter = negative")], 400 if narrow else 728)
    if not narrow:
        W, l, r_, top, plot_h, lab_h = 728, 46, 12, lh + 8, 250, 62
        lo, hi, ticks = _domain([-nmax, pmax], pad=0.06)
        sy = lambda v: top + (hi - v) / (hi - lo) * plot_h
        gw = (W - l - r_) / n
        b = [leg]
        for t in ticks:
            b.append(f'<line x1="{l}" x2="{W - r_}" y1="{sy(t):.1f}" y2="{sy(t):.1f}" class="gl"/>'
                     f'<text x="{l - 6}" y="{sy(t) + 4:.1f}" text-anchor="end" class="mu">{abs(t):g}%</text>')
        b.append(f'<line x1="{l}" x2="{W - r_}" y1="{sy(0):.1f}" y2="{sy(0):.1f}" class="zero"/>')
        bw = min(16, gw * 0.36)
        for i, r in enumerate(rows):
            cx = l + gw * (i + 0.5)
            tip = tip_attr(f"{r['guest']} \u00b7 {_day(r['published'])}",
                           f"Maria: {r['tone_maria_pos']:.0%} positive, {r['tone_maria_neg']:.0%} negative ({int(r['tone_maria_n'])} comments)",
                           f"Guest: {r['tone_guest_pos']:.0%} positive, {r['tone_guest_neg']:.0%} negative ({int(r['tone_guest_n'])} comments)")
            segs = []
            for k, (who, dx) in enumerate((("maria", -bw / 2 - 1), ("guest", bw / 2 + 1))):
                p_, n_ = r[f"tone_{who}_pos"] * 100, r[f"tone_{who}_neg"] * 100
                segs.append(f'<rect x="{cx + dx - bw / 2:.1f}" y="{sy(p_):.1f}" width="{bw:.1f}" height="{max(sy(0) - sy(p_), 0):.1f}" class="m-{who}"/>'
                            f'<rect x="{cx + dx - bw / 2:.1f}" y="{sy(0):.1f}" width="{bw:.1f}" height="{max(sy(-n_) - sy(0), 0):.1f}" class="m-{who} fade"/>')
            lx, ly = cx, top + plot_h + 14
            b.append(f'<g data-tip="{tip}" tabindex="0" role="img" aria-label="{tip}"><rect x="{cx - gw / 2:.1f}" y="{top}" width="{gw:.1f}" height="{plot_h + lab_h}" class="hl"/>'
                     f'{"".join(segs)}<text transform="translate({lx:.1f},{ly}) rotate(-38)" text-anchor="end" class="mu">{_e(_trunc(r["guest"], 12))}</text></g>')
        return svg(W, top + plot_h + lab_h, "".join(b), "Positive and negative comments per episode, Maria and guest")
    L = Lay(True)
    left, right, rh = 112, 12, 36
    lo, hi, ticks = _domain([-nmax, pmax], pad=0.06)
    sx = lambda v: left + (v - lo) / (hi - lo) * (L.W - left - right)
    top = lh + 6
    bot = top + n * rh
    b = [leg]
    for t in ticks:
        b.append(f'<line x1="{sx(t):.1f}" x2="{sx(t):.1f}" y1="{top}" y2="{bot}" class="gl"/><text x="{sx(t):.1f}" y="{bot + 15}" text-anchor="middle" class="mu">{abs(t):g}%</text>')
    b.append(f'<line x1="{sx(0):.1f}" x2="{sx(0):.1f}" y1="{top}" y2="{bot}" class="zero"/>')
    for i, r in enumerate(rows):
        cy = top + i * rh + rh / 2
        tip = tip_attr(f"{r['guest']} \u00b7 {_day(r['published'])}",
                       f"Maria: {r['tone_maria_pos']:.0%} positive, {r['tone_maria_neg']:.0%} negative ({int(r['tone_maria_n'])} comments)",
                       f"Guest: {r['tone_guest_pos']:.0%} positive, {r['tone_guest_neg']:.0%} negative ({int(r['tone_guest_n'])} comments)")
        segs = []
        for who, dy in (("maria", -7), ("guest", 3)):
            p_, n_ = r[f"tone_{who}_pos"] * 100, r[f"tone_{who}_neg"] * 100
            segs.append(f'<rect x="{sx(0):.1f}" y="{cy + dy:.1f}" width="{max(sx(p_) - sx(0), 0):.1f}" height="8" class="m-{who}"/>'
                        f'<rect x="{sx(-n_):.1f}" y="{cy + dy:.1f}" width="{max(sx(0) - sx(-n_), 0):.1f}" height="8" class="m-{who} fade"/>')
        b.append(f'<g data-tip="{tip}" tabindex="0" role="img" aria-label="{tip}"><rect x="0" y="{cy - rh / 2:.1f}" width="{L.W}" height="{rh}" class="hl"/>'
                 f'<text x="{left - 10}" y="{cy + 4:.1f}" text-anchor="end">{_e(_trunc(r["guest"], 14))}</text>{"".join(segs)}</g>')
    b.append(f'<text x="{left}" y="{bot + 34}" class="mu">\u2190 negative</text><text x="{L.W - right}" y="{bot + 34}" text-anchor="end" class="mu">positive \u2192</text>')
    return svg(L.W, bot + 44, "".join(b), "Positive and negative comments per episode, Maria and guest")


def chart_per1k(narrow, e):
    L = Lay(narrow)
    d = e.reset_index(drop=True)
    lo, hi, ticks = _domain(list(d["maria_per_1k_views"]) + list(d["guest_per_1k_views"]), zero=True, pad=0.05)
    lo = 0
    sx = lambda val: L.left + (val - lo) / (hi - lo) * L.plot_w
    leg, lh = legend([("dot", "maria", "Maria named"), ("dot", "guest", "Guest named")], L.W)
    top = lh + 6
    bot = top + len(d) * L.row
    b = [leg, x_axis(sx, [t for t in ticks if t >= 0], top, bot)]
    for i, r in enumerate(d.to_dict("records")):
        cy = top + i * L.row + L.row / 2
        m, g = r["maria_per_1k_views"], r["guest_per_1k_views"]
        tip = tip_attr(f"{r['guest']} · {_day(r['published'])}", f"Naming Maria: {m:.2f} per 1,000 views",
                       f"Naming the guest: {g:.2f} per 1,000 views", f"{int(r['views']):,} views" if pd.notna(r.get("views")) else "")
        b.append(f'<g data-tip="{tip}" tabindex="0" role="img" aria-label="{tip}">'
                 f'<rect x="0" y="{cy - L.row / 2:.1f}" width="{L.W}" height="{L.row}" class="hl"/>'
                 f'<text x="{L.left - 10}" y="{cy + 4:.1f}" text-anchor="end">{_e(_trunc(r["guest"], L.lab))}</text>'
                 f'<line x1="{sx(m):.1f}" x2="{sx(g):.1f}" y1="{cy:.1f}" y2="{cy:.1f}" class="ln" style="stroke:var(--mut)"/>'
                 f'<circle cx="{sx(g):.1f}" cy="{cy:.1f}" r="5" class="m-guest ring"/><circle cx="{sx(m):.1f}" cy="{cy:.1f}" r="5" class="m-maria ring"/></g>')
    b.append(f'<text x="{L.left}" y="{bot + 34}" class="mu">Comments per 1,000 views</text>')
    return svg(L.W, bot + 44, "".join(b), "Comments naming Maria and the guest per 1,000 views, per episode")


def chart_cum(narrow, rows):
    W, H = (400, 250) if narrow else (728, 280)
    l, r_, t, bm = (44, 14, 14, 54) if narrow else (52, 24, 14, 54)
    lo, hi, ticks = _domain([x["lo"] for x in rows] + [x["hi"] for x in rows] + [0], pad=0.1)
    ks = [x["k"] for x in rows]
    k0, k1 = min(ks), max(ks)
    sx = lambda k: l + ((k - k0) / (k1 - k0) if k1 > k0 else 0.5) * (W - l - r_)
    sy = lambda val: t + (hi - val) / (hi - lo) * (H - t - bm)
    b = []
    for tk in ticks:
        b.append(f'<line x1="{l}" x2="{W - r_}" y1="{sy(tk):.1f}" y2="{sy(tk):.1f}" class="gl"/>'
                 f'<text x="{l - 6}" y="{sy(tk) + 4:.1f}" text-anchor="end" class="mu">{tk:+g}</text>' if tk else
                 f'<text x="{l - 6}" y="{sy(tk) + 4:.1f}" text-anchor="end" class="mu">0</text>')
    b.append(f'<line x1="{l}" x2="{W - r_}" y1="{sy(0):.1f}" y2="{sy(0):.1f}" class="zero"/>')
    step = 1 if len(ks) <= 12 else math.ceil(len(ks) / 10)
    for k in ks[::step]:
        b.append(f'<text x="{sx(k):.1f}" y="{H - bm + 16}" text-anchor="middle" class="mu">{k}</text>')
    up = " ".join(f"{sx(x['k']):.1f},{sy(x['hi']):.1f}" for x in rows)
    dn = " ".join(f"{sx(x['k']):.1f},{sy(x['lo']):.1f}" for x in reversed(rows))
    b.append(f'<polygon points="{up} {dn}" class="band"/>')
    line = " ".join(f"{sx(x['k']):.1f},{sy(x['mean']):.1f}" for x in rows)
    b.append(f'<polyline points="{line}" class="ln s-maria"/>')
    for x in rows:
        tip = tip_attr(f"After {x['k']} episodes (latest: {x['guest']})", f"Average gap {_pts(x['mean'])} pts",
                       f"95% range {_pts(x['lo'])} to {_pts(x['hi'])}")
        b.append(f'<g data-tip="{tip}" tabindex="0" role="img" aria-label="{tip}"><rect x="{sx(x["k"]) - 12:.1f}" y="{t}" width="24" height="{H - t - bm}" class="hit"/>'
                 f'<circle cx="{sx(x["k"]):.1f}" cy="{sy(x["mean"]):.1f}" r="4" class="m-maria ring"/></g>')
    last = rows[-1]
    b.append(f'<text x="{W - r_}" y="{max(t + 10, sy(last["hi"]) - 6):.1f}" text-anchor="end" class="mu">95% range</text>')
    b.append(f'<text x="{(l + W - r_) / 2:.1f}" y="{H - 14}" text-anchor="middle" class="mu">Episodes counted so far (oldest first)</text>')
    return svg(W, H, "".join(b), "Average gap as episodes accumulate, with 95% range")


# ---------------------------------------------------------------- HTML pieces
def figure(fid, title, inner, caption, table_html):
    return (f'<figure id="{fid}" data-title="{_e(title)}" data-source="{_e(SOURCE_LINE)}">'
            f'<div class="bar"><h3>{html.escape(title)}</h3><button type="button" data-save>Save as image</button></div>'
            f'{inner}<figcaption>{caption}</figcaption>'
            f'<details><summary>View as table</summary><div class="scroll">{table_html}</div></details></figure>')


def simple_table(head, rows):
    h = "".join(f"<th>{html.escape(x)}</th>" for x in head)
    b = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>"


def episode_table(e):
    e = e.sort_values("published") if "published" in e else e
    cols = [c for c in COLS if c[0] in e.columns]
    head = "".join(f'<th class="{"k" if k == "k" else ""}">{html.escape(n)}</th>' for _, n, k in cols)
    rows = []
    for r in e.to_dict("records"):
        rows.append("<tr>" + "".join(f'<td class="{"k" if k == "k" else "n"}">{_fmt(r.get(c), k)}</td>' for c, _, k in cols) + "</tr>")
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def requests_table(w, top=15):
    w = w.head(top)
    first, rest = w.columns[0], list(w.columns[1:])
    head = "<th>Requested guest</th>" + "".join(f"<th>{html.escape('All episodes' if c == 'total' else str(c))}</th>" for c in rest)
    body = "".join("<tr><td>" + html.escape(str(r[first])) + "</td>" + "".join(f"<td>{int(r[c])}</td>" for c in rest) + "</tr>"
                   for r in w.to_dict("records"))
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def method_note(info, updated):
    rv = info.get("rules_versions") or []
    ver = f" Tagging rules version: {html.escape(', '.join(rv))}." if rv else ""
    return (
        "<h2>Data and method</h2><div class='card'><ul>"
        f"<li><b>Source.</b> Public comments on the Pretty Tough videos, read through the YouTube API Services. Data from YouTube; see "
        f"<a href='{YT_TERMS}' rel='noopener'>YouTube's Terms of Service</a> and the <a href='{G_PRIVACY}' rel='noopener'>Google Privacy Policy</a>.</li>"
        "<li><b>Scope.</b> Top-level comments only (replies are not collected), from the first 7 days after each upload. "
        "Raw comment text is deleted after 28 days; only counts and shares are kept.</li>"
        "<li><b>No comment text and no usernames</b> appear anywhere on this page or in the downloads.</li>"
        f"<li><b>How accurate is the tagging?</b> {html.escape(ACCURACY)}{ver}</li>"
        f"<li><b>Data as of</b> {html.escape(updated)}.</li>"
        "<li><b>Independence.</b> This is an independent hobby project. It is not affiliated with or endorsed by Maria Sharapova, "
        "the Pretty Tough podcast or YouTube.</li></ul></div>")


# ---------------------------------------------------------------- page
def build(out, site):
    os.makedirs(site, exist_ok=True)
    info = {}
    if os.path.exists(os.path.join(out, "run_info.json")):
        info = json.load(open(os.path.join(out, "run_info.json"), encoding="utf-8"))
    updated = info.get("run_date") or date.today().isoformat()
    e = _read(out, "episode_summary.csv")
    parts = [f"<h1>{html.escape(TITLE)}</h1>", f"<p>{html.escape(INTRO)}</p>"]
    charts = 0
    if e is not None and len(e) and "gap_all" in e:
        e = prepare(e)
        v = verdict_numbers(e)
        head, txt, side = headline(v)
        dot = f'<span class="dot" style="background:var(--{side})"></span>' if side and "clear difference so far" in head and not head.startswith("No") else ""
        hero = f"<b>{dot}{_pts(v['mean'])} pts</b>" if v["n"] >= 3 else ""
        parts.append(f"<div class='card'><h3>{html.escape(head)}</h3><div class='hero'>{hero}<span>{html.escape(txt)}</span></div>"
                     + (f"<p class='mut'>Maria ahead in {v['k']} of {v['kn']} episodes (sign test p = {v['p']:.2f}). " if v["n"] >= 3 else "<p class='mut'>")
                     + f"Gap = comments naming Maria minus comments naming the guest, as a share of all comments (percentage points). "
                       f"Last updated {html.escape(updated)}.</p></div>")
        if info.get("rules_versions") and len(info["rules_versions"]) > 1:
            parts.append("<p class='mut'>Note: some episodes were tagged under older rules (" + html.escape(", ".join(info["rules_versions"])) +
                         "), so compare them with care.</p>")
        parts.append("<details><summary>How to read this</summary><div class='card'><ul>" + "".join(f"<li>{c}</li>" for c in CAVEATS) + "</ul></div></details>")
        parts.append("<h2>Episode by episode</h2>")
        if e["gap_pts"].notna().any():
            d = e.dropna(subset=["gap_pts"])
            tbl = simple_table(["Guest", "Published", "Gap (pts)", "95% range", "Comments", "Counted"],
                               [[r["guest"], r["published"], _pts(r["gap_pts"]), f"{_pts(r['lo_pts'])} to {_pts(r['hi_pts'])}", f"{int(r['n_comments']):,}",
                                 "yes" if r["reliable"] else "no"] for r in d.to_dict("records")])
            parts.append(figure("gap_by_episode", "Gap in each episode", both_layouts(chart_gap, d, v),
                                "Each dot is one episode; the line is its 95% range, which is wide when few comments name either. "
                                "Hollow dots have too few named comments and are not counted in the average.", tbl))
            charts += 1
        rb = robustness(e)
        if len(rb) >= 2:
            parts.append("<h2>Does the answer depend on how it is measured?</h2>")
            tbl = simple_table(["Measure", "Average gap (pts)", "95% range", "Maria ahead in"],
                               [[r["label"], _pts(r["mean"]), f"{_pts(r['lo'])} to {_pts(r['hi'])}", f"{r['k']} of {r['n']}"] for r in rb])
            parts.append(figure("robustness", "The same test, six ways", both_layouts(chart_robust, rb),
                                "The first row is the main measure. If the dots agree, the result does not hinge on one choice. 'Both by focus' assigns "
                                "comments naming both to whoever they are mostly about; 'Only discussion' leaves out thanks addressed to Maria; "
                                "'Worst case' gives every no-name 'she/her' comment to the guest.", tbl))
            charts += 1
        if all(c in e.columns for _, _, c in MIX):
            parts.append("<h2>What the comments are about</h2>")
            tbl = simple_table(["Guest", "Published"] + [n for _, n, _ in MIX],
                               [[r["guest"], r["published"]] + [f"{(r.get(c) or 0):.0%}" for _, _, c in MIX] for r in e.to_dict("records")])
            parts.append(figure("mix", "What each episode's comments are about", both_layouts(chart_mix, e),
                                "Share of all comments. Request = asking for a future guest. Everything else includes thanks, reactions, "
                                "comments on the topic, and she/her comments with no name.", tbl))
            charts += 1
        tcols = ["tone_maria_pos", "tone_maria_neg", "tone_guest_pos", "tone_guest_neg", "tone_maria_n", "tone_guest_n"]
        if all(c in e.columns for c in tcols):
            t = e.dropna(subset=tcols)
            t = t[(t["tone_maria_n"] >= 10) & (t["tone_guest_n"] >= 10)]
            if len(t):
                tbl = simple_table(["Guest", "Published", "Maria positive", "Maria negative", "Maria comments", "Guest positive", "Guest negative", "Guest comments"],
                                   [[r["guest"], r["published"], f"{r['tone_maria_pos']:.0%}", f"{r['tone_maria_neg']:.0%}", int(r["tone_maria_n"]),
                                     f"{r['tone_guest_pos']:.0%}", f"{r['tone_guest_neg']:.0%}", int(r["tone_guest_n"])] for r in t.to_dict("records")])
                parts.append("<h2>How the comments felt</h2>")
                parts.append(figure("tone", "Positive and negative comments, Maria and guest", both_layouts(chart_tone, t),
                                    "Share of comments naming only that person that read positive (above the line, or to the right on a phone) or negative (below, or to the left). "
                                    "Neutral comments are not drawn. Tone is an automatic score (VADER) that misses sarcasm and context, and much of the positive tone toward "
                                    "Maria is thanks addressed to her: read it as warmth, not as who is more interesting. Episodes with under 10 comments for either side are left out.", tbl))
                charts += 1
        if "views_comparable" in e and "maria_per_1k_views" in e:
            c = e[e["views_comparable"].astype(str).str.lower().isin(["true", "1"]) & e["maria_per_1k_views"].notna()]
            if len(c):
                tbl = simple_table(["Guest", "Maria per 1k views", "Guest per 1k views"],
                                   [[r["guest"], f"{r['maria_per_1k_views']:.2f}", f"{r['guest_per_1k_views']:.2f}"] for r in c.to_dict("records")])
                parts.append("<h2>Adjusted for audience size</h2>")
                parts.append(figure("per_1k", "Comments naming each, per 1,000 views", both_layouts(chart_per1k, c),
                                    "A comment naming both counts for both. Only episodes whose view count was read soon enough after upload are shown.", tbl))
                charts += 1
        cum = cumulative_rows(e) if v["n"] >= 3 else []
        if cum:
            tbl = simple_table(["Episodes", "Latest guest", "Average gap (pts)", "95% range"],
                               [[x["k"], x["guest"], _pts(x["mean"]), f"{_pts(x['lo'])} to {_pts(x['hi'])}"] for x in cum])
            parts.append("<h2>How the answer has settled</h2>")
            parts.append(figure("cumulative", "The average gap as episodes accumulate", both_layouts(chart_cum, cum),
                                "A band that narrows and stays on one side of zero is what a real difference looks like; one that keeps "
                                "crossing zero means no clear difference yet.", tbl))
            charts += 1
        parts.append("<h2>All episodes</h2>" + episode_table(e) +
                     "<p class='mut'>Gap = share of all comments naming Maria minus the guest (percentage points); positive means Maria ahead. "
                     "Keyword candidates and requested guests come from the comment text while it was available.</p>")
    else:
        parts.append("<div class='card'>No episode results yet.</div>")
    w = _read(out, "guest_requests_table.csv")
    if w is not None and len(w):
        parts.append("<h2>Guests viewers ask for</h2>" + requests_table(w) +
                     "<p class='mut'>Names are typed by viewers and read by simple rules, so treat the counts as approximate.</p>")
    links = [(f, d) for f, d in DOWNLOADS if os.path.exists(os.path.join(out, f))]
    for f, _ in links:
        shutil.copy(os.path.join(out, f), os.path.join(site, f))
    extra = []
    for name, label in EXTRA_HTML:
        if os.path.exists(os.path.join(out, name + ".html")):
            shutil.copy(os.path.join(out, name + ".html"), os.path.join(site, name + ".html"))
            extra.append((name + ".html", label))
    if links or extra:
        parts.append("<h2>Data</h2><ul>" + "".join(f'<li><a href="{f}">{html.escape(d)}</a> <span class="mut">({f})</span></li>' for f, d in links + extra) + "</ul>")
    parts.append(method_note(info, updated))
    page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="color-scheme" content="light dark"><title>Pretty Tough comments</title><style>{STYLE}</style></head>'
            f'<body><main>{"".join(parts)}</main><div id="tip" role="tooltip"></div><script>{JS}</script></body></html>')
    open(os.path.join(site, "index.html"), "w", encoding="utf-8").write(page)
    open(os.path.join(site, ".nojekyll"), "w").close()
    print(f"Built {site}/index.html ({charts} chart(s), {0 if e is None else len(e)} episode row(s))")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--site", default="site")
    a = ap.parse_args()
    build(a.out, a.site)
