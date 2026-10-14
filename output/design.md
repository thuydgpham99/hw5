# design.md — the Campus Customs Operations Desk

What I chose for the dashboard, and why. The brief was "a real desk people would want to sit
at", so the question I kept asking was not "how do I display this data" but **"what is this
person actually doing, and what do they need to see without being told?"**

The person at this desk does three things: they look at what came in, they watch the team
work it, and they sign off on money. So the screen is three columns, in that order.

---

## 1. Layout: the desk as a desk

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Campus Customs   ⏱ shop today 2026-08-31   gpt-6-luna        CHECKING       │
│                                                               $3,400.00      │
├───────────────┬──────────────────────────────────┬───────────────────────────┤
│  THE BOARD    │  THE FLOOR                       │  YOUR DESK                │
│               │  ┌────┬────┬────┬────┬────┐      │                           │
│  ticket 101   │  │ BO │ IN │ AC │ FA │ CS │      │   ╭───────────────────╮   │
│  ticket 102   │  └────┴────┴────┴────┴────┘      │   │  PAY VENDOR INV.  │   │
│  ticket 103   │                                  │   │     $840.00       │   │
│               │  Live feed │ Shift report        │   │  [Approve] [Deny] │   │
│               │  …the team working…              │   ╰───────────────────╯   │
└───────────────┴──────────────────────────────────┴───────────────────────────┘
      what          who is doing it, right now            what needs a human
    came in
```

**Three columns, left to right, in the order work actually moves.** Work arrives on the left,
gets done in the middle, and ends up needing a person on the right. Nobody has to be taught
the layout; it matches the sentence "a ticket came in, the team looked at it, now I have to
approve something."

**The cash number lives in the top bar, not in a column.** It is the one constraint every
decision on the screen collides with — there is no revenue in this shop, so the balance only
ever falls. Putting it in the persistent header means you cannot approve a payment without
the number you are spending from being in your eye line. Underneath it, a small bar shows
**committed vs. free**: the money that is already spoken for by pending requests, which is
the figure that actually tells you whether the next approval is safe.

**No modals anywhere.** A modal would hide either the agents' reasoning or the balance at the
exact moment you are deciding whether to spend. Everything stays on one surface.

---

## 2. How the agents read differently

This was the part worth getting right. An agent run produces three completely different kinds
of event, and if they all render as "chat messages" the screen becomes unreadable noise. So
each kind gets its own visual grammar:

| What happened | How it renders | Why |
|---|---|---|
| **An agent talks** | A soft, rounded card tinted with that agent's colour, in prose at normal reading size | Speech is the thing a human actually reads, so it gets the most comfortable typography on the screen |
| **An agent uses a tool** | A flat monospace strip on near-black, `tool_name` in blue, arguments dimmed | Machinery should look like machinery. You skim these; you do not read them |
| **A tool refuses** | The same strip, but the left edge and label turn red and say `refused` | **A guardrail firing is a feature, not an error.** When Bulldog Print Co is blocked by the unpaid invoice, that refusal is the most interesting event in the run |
| **An agent delegates** | A dashed row with both avatars and an arrow between them: `IN → AC` | The hand-off is the story of a multi-agent system. It deserves to be an object, not a log line |
| **Run milestones** | A thin centred rule with a short caption | Structure without clutter |

**Each agent has one hue, and that hue drives everything.** One CSS custom property
(`--h`) feeds the avatar, the name, the speech-card tint, the connector line, and the rail
card's top border. Boss is violet, inventory green, accounting amber, facilities blue,
customer service pink. After about ten seconds you stop reading names and start recognising
colours — you can see "accounting is talking again" from across the room.

**Delegation depth is physical.** A delegated agent's events are indented under the agent that
called them, with a vertical connector in the caller's colour. A chain like
`boss → inventory → accounting` literally staircases down the screen. Depth 2 sits further
right than depth 1, so the shape of the collaboration is visible without reading a word.

**The agent rail across the top of the middle column is the "who's on shift" strip.** Five
cards, one per agent, each with its role in plain language. While a ticket runs, the active
agent's card lifts: its border brightens to full colour, the background takes a tint, and a
small dot pulses. When the agent finishes, the card settles into a muted "used" state showing
how many tools it called. Agents never consulted stay grey and say `idle` — which makes the
**routing decision visible as an absence**. Seeing facilities sit grey through ticket 101 is
how you know the boss routed it correctly.

**Live feed vs. Shift report, as two tabs.** Watching and reviewing are different jobs. The
feed is chronological and auto-scrolls while work happens. The report is the summary you want
afterwards: the boss's verdict with its outcome badge, what was written to the shop, what is
waiting on you, the next step — then one card per agent saying what that agent did and the
tools it used as chips. The app flips to the report automatically when a run finishes, because
at that moment you have stopped watching and started reviewing.

---

## 3. Resolved tickets

A ticket card carries its state in three places at once, at three different glance distances:

1. **A coloured left edge** — grey when open, amber while the team is working it, green when
   it is done. Readable from peripheral vision.
2. **A status tag in the corner** — the literal status (`open`, `awaiting approval`, `blocked`,
   `resolved`), colour-matched. Amber for awaiting approval is deliberate: that state means
   *you* are the bottleneck.
3. **A rubber stamp.** A finished ticket gets `RESOLVED` stamped in the corner in green, rotated
   seven degrees like it was banged on with an actual stamp.

The stamp is the piece I most enjoyed. It is not information — the status tag already says
`resolved` — it is **reward**. Finishing something should feel like finishing something, and a
flat grey "resolved" label gives you nothing. The tilt is what sells it: perfectly aligned
would read as a UI element, slightly crooked reads as a thing a person did.

Resolved tickets stay in place rather than disappearing. There are only three, they are the
shop's whole day, and watching the board fill up with green stamps is the point.

---

## 4. Cash and approvals

**Approval requests are rendered as paper slips** — cream card stock on the dark desk, with a
perforated edge dotted along the top as if torn off a pad, the amount set large in monospace,
the agent's reason in the body, and the provenance line underneath (`requested by accounting ·
checking · invoice #501 · ticket 101`).

They are the only light-coloured objects on the entire screen. That is on purpose and it is
the single strongest design decision here: **the things a human must act on look like physical
paper, and everything an agent produced is digital.** You cannot miss them, and the medium
itself tells you whose job this is. An agent can fill out the slip; only you can sign it.

Once decided, the slip loses its paper — it flips to the dark panel treatment and takes a
stamp: `PAID` in green, or `DENIED` in red, rotated like the ticket stamp, with the signer's
name in the footer. The paper is gone because the decision is no longer yours to make.

**The cash number reacts.** When a payment goes through, the balance flashes red and nudges
upward before settling back to white, the committed bar re-draws, and a green banner names the
amount and the new balance. The drop is animated rather than instant because **money leaving
should be felt, not just displayed.** This shop has no income; every approval is permanent.

The empty state on that column says it outright: *"Nothing needs your signature yet. Agents can
only ask — they can never pay."* It is the system's most important property, so it is written
where a person will read it rather than buried in a README.

---

## 5. The small creative choices

- **The shop clock pill.** `⏱ shop today 2026-08-31` sits next to the title in amber. The whole
  simulation hangs on `desk.date_today`, and an operator who forgets that will misread every
  due date on the screen. Pinning it to the header makes the fiction unambiguous.
- **The model pill.** `gpt-6-luna`, read live from `/health`. You always know what is driving
  the team.
- **Monospace for every number, sans-serif for every sentence.** Money, SKUs, dates, tool names
  and IDs are all things you compare; prose is something you read. Splitting the typefaces
  means a balance and a sentence never get confused for each other.
- **"Fresh start" rather than "Reset DB".** The button restores the original database, but what
  the person is doing is starting the day over.
- **Honest, specific empty states.** `"Pick a ticket from the board to put the team on it."`
  Each one says what to do next instead of apologising for having no data.
- **A footer that states the contract.** *"agents prepare, a human approves, only then does cash
  move."* The rule the whole system is built around, sitting quietly at the bottom of every
  screen.
- **The tab bar shows a live event count**, so you can tell the feed is moving even when you are
  reading the report.
- **Backend-offline is a state, not a crash.** If the API is unreachable the header shows a red
  `backend offline` pill and the error banner gives the exact command to start it.

---

## 6. What I deliberately did not do

- **No charts.** Three tickets and one bank account. A sparkline would be decoration pretending
  to be insight.
- **No auto-run.** The human picks the ticket and presses the button. An agent team that starts
  spending attention — and queueing money — on its own is a different and worse product.
- **No "approve all".** Each slip is signed individually. Batching approvals is exactly how a
  human-in-the-loop system quietly becomes a rubber stamp.
- **No raw JSON dumps in the feed.** Tool results are summarised to about 160 characters. The
  full payload is in `output/audit_trail.json`, which is the right place for forensics; the desk
  is for working.

---

## 7. Running it

```bash
cd backend && uvicorn main:app --reload --port 8000
cd frontend && npm run dev
```

The frontend reads its API base from `frontend/.env` (`VITE_API_BASE=http://localhost:8000`),
and the backend allows the Vite origin on 5173 — plus 5174/5175, since Vite silently falls back
when 5173 is taken.
