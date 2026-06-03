# AT0 — Social Drafting Kit (Claude Code)

Two reusable prompts + a tracker. No module to build — you run these in Claude Code, review, and post via Buffer.

**Voice rule for everything:** calm, concrete, human. No hype words ("revolutionary," "game-changing"). Lead with the benefit. Say "planned" when it's planned. Write **AT0**, say **"Auto."**

---

## Prompt 1 — draft a batch

> Paste into Claude Code (run it where it can read `docs/brand/` + `docs/marketing/`).

```
You are my social content drafter for AT0 ("Auto"). Draft a 2-week batch in my voice.

READ FIRST (my voice + plan):
- docs/brand/MESSAGING.md   (voice, tagline, pillars, naming rules)
- docs/brand/BRAND.md       (tone)
- docs/marketing/campaign-plan.md
- docs/marketing/why-at0.md

PRODUCE a 2-week batch across X, LinkedIn, Instagram:
- X: 4–5 posts/week + 1 thread/week
- LinkedIn: 1–2 posts/week
- Instagram: 1–2 captions/week

RULES:
- Voice: calm, concrete, no hype. Lead with the benefit. "planned" not overpromise.
- Rotate angles: neurodiversity (lead), privacy/ownership, the system, build-in-public.
- End with ONE ask when it fits: at-0.com.
- X ≤ 280 chars (show the count). LinkedIn longer + 3–5 hashtags. IG caption + hashtags as a first comment.
- Suggest which existing asset to attach (docs/marketing/cards, /carousel, /graphics) or when a real screenshot is better.
- Drafts only. No automated engagement.

OUTPUT:
1) A markdown table: date | platform | angle | asset | post (+char count for X).
2) Append the same rows to docs/marketing/content-calendar.csv with status=draft.
Do not invent product features or metrics. If unsure, ask me ONE question first.
```

## Prompt 2 — draft replies (engagement, human-approved)

```
Here are mentions/comments on my AT0 posts: [paste them].
For each, draft 1–2 short reply options in my voice (warm, concrete, no hype).
Never auto-send — I post manually. Flag anything I should NOT engage with.
```

---

## Weekly loop (15 min)

1. Run **Prompt 1** in Claude Code → get the batch + calendar update
2. Skim, tweak any that feel off-voice (you're the editor)
3. Paste into **Buffer** → schedule to X / LinkedIn / Instagram (attach the suggested asset)
4. When replies come in, run **Prompt 2** → approve → post yourself
5. Once a week, fill the `impressions`/`engagements` columns from each platform → see which **angle** converts

## Optional: make it a one-tap command

Claude Code supports project commands. Save **Prompt 1** as `.claude/commands/social-draft.md` and **Prompt 2** as `.claude/commands/social-reply.md` in your repo — then just run `/social-draft` and `/social-reply`.

## When you outgrow this

When posting is a habit and manual feels slow, build the **Herald** module (spec ready): Buffer publishing, draft-and-approve via your NATS gate, presence tracking, metrics digest. The drafting prompts above become Herald's drafting step.
