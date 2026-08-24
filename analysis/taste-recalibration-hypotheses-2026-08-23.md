> **STATUS (2026-08-23, same day): RETRACTED AS TASTE CLAIMS — RETAINED AS PREDICTION PRIORS.**
> Anping rejected the framing, and he was right: these are patterns in outcomes,
> measured over the world he happened to watch — properties of the *prediction
> problem*, not of him. Series decay is television getting worse, honestly scored
> (Better Call Saul: equal-or-better is what happens when quality holds). His
> profile's first principle (唯一主轴是质量) already said this; this document
> re-committed category attribution at the statistical layer.
> The NUMBERS remain valid and in use as engine priors (cells, base rates,
> decay-risk flags). The INTERPRETATIONS as statements about his taste are
> withdrawn. TASTE.md was not modified and hypothesis-ratification interviews
> are discontinued — calibration now runs through the verdict loop (see spec
> Part B amendment of this date).

# TASTE.md recalibration — hypotheses for judgement (cutoff 2026-08-23)

**Method.** Population-scale pass over every rated film/TV work in media.db, not a
sample. Cohort: `works.kind` in (film, tv, show, drama), `records.status` in
(watched, watching), rating present; one row per work, source precedence
manual > douban > letterboxd > plex. **n = 1,609 rated works** (552 commented,
1,057 silent). Stars are 0-5 (media.db stores 0-10; halved).

**Limitations, stated up front.** Runtime is absent from `works.meta` for all
films, so H4 (拖沓/太长) could not be tested and is not addressed below — a
documented negative, not a pass. Language is inferred from original-title script
(kana → Japanese, CJK → Chinese, Latin → other), which misfiles Korean titles
written in Latin script and any Chinese work stored only under an English title.
Season decay is measured on the 54 shows with ≥3 rated seasons. Nothing here is
a causal claim; these are patterns in outcomes, and several have a selection
explanation that only you can settle.

---

## The structural finding, before any individual hypothesis

**Your taste profile was calibrated on a biased third of your own history.**
TASTE.md records its basis as 491 条短评全量精读 — the calibration read your
*comments*. Comments exist for **552 of 1,609 works (34%)**, and that subset is
measurably not representative: commented works average **3.58** against **3.71**
for silent ones, and 1-2★ ratings are **14.3%** of commented works versus
**7.2%** of silent ones. You write when annoyed.

The silent two-thirds are not a different kind of viewing — the film/TV mix is
nearly identical (71/29 commented, 68/32 silent), so this is the same viewing,
simply unwritten. The gap is concentrated in television: silent TV averages
**4.07** against **3.78** for commented TV, while films are level (3.54 vs 3.50).

This is the same sampling bias you identified in the recommender, one layer
deeper. The hypotheses below are drawn from the full 1,609.

---

## Hypotheses — please judge each 准 / 部分准 / 不准

**N1. Long-running series decay is your strongest single pattern, and the
profile understates it.** Of 54 shows where you rated ≥3 seasons, **34 declined,
14 held flat, 6 improved**; mean change first-to-last **−0.75★**. The falls are
steep, not gentle: 黑袍纠察队 5.0→1.0, 真相捕捉 5.0→2.0, 神烦警探 5.0→2.0,
亿万 4.5→2.0, 初来乍到 5.0→3.0. TASTE.md currently grades this 部分准 (H13).
The data says it is close to a rule.

**N2. Michael Bay belongs on the veto list.** 迈克尔·贝 n=7, mean **2.57** —
lower than any name currently on it. Also clustered low: 刘镇伟 2.75 (n=4),
彭浩翔 2.80 (n=5), 徐克 2.83 (n=6), 王晶 3.00 (n=5) — a Hong Kong commercial
cinema cluster the profile never names.

**N3. The director whitelist is incomplete in a specific direction: animation
houses.** 尼克·帕克/Aardman n=5 mean **4.80**; 汉纳-巴伯拉 n=8 mean **4.62**;
今敏 n=4 4.50; 宫崎骏 n=9 4.17; 塞思·麦克法兰 n=10 4.10. TASTE.md names 今敏 but
not the studio-scale pattern, and explicitly refuses "animation is a pillar" as
a label. Question: is the animation hit-rate a genuine taste axis, or the same
strict-prefiltering you gave as the explanation for documentaries (H12)?

**N4. Language correlates with your ratings across all time, contradicting H15 —
but the effect nearly disappears in the recent era.** All-time: Japanese-language
n=85 mean **4.02** (33% five-star), Latin-script n=1,169 **3.74** (18%),
Chinese-language n=355 **3.35** (14%). That is a 0.67★ spread. But restricted to
works you marked 2021 or later: Chinese **3.65**, Latin **3.79** — a 0.14★ gap,
with Japanese too small to read (n=15). So H15 ("倒是没觉得和国家有关系") holds
for current you and fails for historical you. My reading is that this is a
selection artifact of the 2011-2015 catch-up era rather than a taste axis, and
the HK cluster in N2 is part of it. Your call.

**N5. 2015 was your worst year and 2024 your best.** Mean by marking year:
2015 **3.08** (4% five-star, n=49), rising to 2024 **4.01** (31% five-star,
n=90). TASTE.md's three-era story (H22) is directionally right but the trough is
sharper and more recent-recovery pronounced than recorded. Practical
consequence: 2011-2015 ratings should be discounted more heavily than the
current "老分做候选参考" note implies.

**N6. Television is where you are generous and film is where you are strict.**
TV/show n=498 mean **3.98**, 74% at ≥4★, 31% at a full 5. Film n=1,110 mean
**3.53**, 54% at ≥4★, 12% at 5. Recent film (2020-26) is harshest: n=105 mean
**3.37**, 44% ≥4★, only **4%** five-star. This is already wired into the
recommender's gate; it is not yet stated anywhere in TASTE.md.

---

## What I recommend

Judge N1 through N6, and I will rewrite TASTE.md with two structural changes
beyond the content: per-entry confidence grades (calibrated / provisional /
hypothesized), which the critic needs and the profile currently lacks, and an
explicit note that the profile's evidence base is the full 1,609 rather than the
commented subset.

The one change I would make regardless of your verdicts is **N1**: a
recommendation of a long-running series is, on your own record, a losing bet
about two times out of three, and the recommender should carry that as a stated
risk rather than a footnote.
