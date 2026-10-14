# Questions the data could answer (a running log)

Add a line whenever a question comes up. "Data held" means it can be answered from what the pipeline already stores, with no new
fetching (and so it survives the 28-day text purge). Mark a question **Asked** with the issue date once it has been looked at.
With about 20 episodes, treat anything here as exploratory: state the question before looking, and say so in the post.

## Can be answered from data already held

| # | Question | Data held | Status | Notes |
|---|----------|-----------|--------|-------|
| 1 | Do comments about Maria collect more likes than comments about the guest? | `likes`, `about` per comment; `gap_likes` exists | Open | Average likes per comment by tag is a small step from the like-weighted gap |
| 2 | Do Maria comments arrive earlier than guest comments? | `posted_at`, `about`; share posted in first 24h exists per episode | Open | Split the first-24h share by tag |
| 3 | Do Russian-language comments cluster around Maria? | `script`, `about`; Cyrillic share exists per episode | Open | Split Cyrillic share by tag |
| 4 | Which comments start conversations? | `replies` per comment (replies themselves are off) | Open | Replies per comment by tag |
| 5 | Does the gap shrink for bigger episodes or more famous guests? | `views`, `guest_tier`, comments per 1,000 views | Open | Small n; a scatter, not a test |
| 6 | How strong is the appetite for new guests? | `share_request`, requests per 1,000 views | Open | |
| 7 | How much do comments mention Maria's work or the doping topic vs the guest's work? | `work`, `topic` flags; `work_maria_share`, `work_guest_share` exist | Open | `doping` list is off until `on=yes` in `work_terms.csv` |
| 8 | Is the warm tone toward Maria mostly thanks addressed to her? | `compound`, `mode` | Open | Tone split by address vs discussion (design B in the mock-up) |

## Needs a small change first

| # | Question | What is missing | Notes |
|---|----------|-----------------|-------|
| 9 | How many distinct people ask for each guest? | Commenter ids are never stored; counts would have to be made at fetch time | Decided for now: count comments, since repeat requests show passion |
| 10 | How often do comments judge the host-guest interaction ("cut off by the host")? | A flag in `classify.py` | Parked: only 1 of 61 sampled Guest comments; wording is ambiguous |
| 11 | Which themes run through an episode's comments? | Two-word phrases in the keyword step | Parked; would bump the rules version |
| 12 | How accurate are the rules on comments they were not tuned on? | A fresh labelled sample (50 to 100 comments) from `sample_neither.py` | Needed before quoting an accuracy figure without the "optimistic" warning |

## Added by you
