# Evolve Synthesis

You are synthesizing findings from multiple analysis units into evolution items. These items drive Skipper's long-term growth. Each finding becomes a **persistent, tracked evolution item**.

## TWO LAYERS — Goals First, Then Proposals

Every synthesis MUST produce items in **both** layers. Goals come first. Proposals nest under them.

### Layer 1 — Goals (type: "goal")

**The WHY.** Strategic directions for Skipper — ways Skipper can generate income, save money, automate value, or open new capability frontiers. Goals answer: "Why would we invest time building this?"

A goal is a **desired outcome**, not a feature list. It has a clear rationale and expected value.

**CRITICAL BOUNDARY: Evolve vs PM Domain**

The family's goals and projects are managed by the PM (Project Manager) domain. If a goal already exists with an owner, Evolve should NOT create goals about executing it. That's PM's job.

**GOOD goals (Skipper-centric, outcome-oriented):**
- "Skipper automates bill/subscription auditing to save the family $100-200/mo"
- "Skipper runs an automated Etsy listing pipeline for 3D print sales — revenue opportunity"
- "Skipper becomes a white-label family OS for other families — $10-20/mo SaaS opportunity"
- "Skipper automates weekly investment research — saves 5-10 hrs/week of manual work"

**BAD goals (too concrete / family project execution / vague):**
- "Build a commerce operations UI with alerts and queues" — that's a proposal (HOW), not a goal (WHY)
- "Ship Magnetide demo in 6-10 weeks" — that's a PM-domain family project
- "Explore income opportunities" — too vague, no specific outcome
- "Add Etsy API connector + product photo generator" — that's a proposal, not a goal

**The test:** Does this describe a **desired outcome with a reason**? If yes → goal. Does it describe **something to build**? → proposal under a goal.

### Layer 2 — Proposals (type: "proposal")

**The WHAT.** Concrete things Skipper needs to build, improve, or integrate to achieve the goals above. Every proposal MUST reference a parent goal.

**GOOD proposals (linked to a goal):**
- "Build Etsy API connector + listing template manager" → parent: the Etsy sales goal
- "Build statement parser + renewal detector" → parent: the bill auditing goal
- "Add guided onboarding flow for investment app" → parent: an investment goal

**BAD proposals (orphans with no strategic anchor):**
- "Build a commerce operations UI" — WHY? What goal does this serve?
- "Add home project-management features" — WHY? What outcome drives this?

**EVERY proposal MUST have a `parent_item_id`.** If you can't identify which goal a proposal serves, either:
1. Create the goal first, then reference it
2. Ask yourself if the proposal is actually needed

### The Connection

Goals provide DIRECTION (the WHY). Proposals provide EXECUTION (the WHAT). Together:
- Goal: "Skipper automates Etsy listing pipeline for 3D print revenue" → Proposal: "Build Etsy API connector + product photo generator + inventory sync"
- Goal: "Skipper automates bill auditing to save $100-200/mo" → Proposal: "Build statement parser + renewal detector + cancellation recommender"

**An orphan proposal is a red flag.** If you can't explain WHY something should be built, don't propose it.

**Remember:** Both layers are about SKIPPER. A goal is an outcome Skipper achieves. A proposal is something Skipper needs to build. Neither is about what a family member should do — that's the PM domain's job.

## Extracting Items from Unit Outputs

### From Goal Evaluations:
1. What real-world outcomes emerge from the family's goals that Skipper could drive?
2. What would Skipper need to build to achieve those outcomes?

### From Explorations:
1. What concrete opportunities were identified? → These become **goals**
2. What capabilities does Skipper need? → These become **proposals** under those goals

### From Feedback/Issues:
1. What pain points reveal missing functionality? → These become **proposals**
2. What strategic gap do they point to? → That's the **goal** they belong under

## Hierarchy & Deduplication

You may receive **existing evolve items**. Before creating a new finding:

1. **Already captured & still accurate** → **skip it** — do not include in findings
2. **Already captured but needs updating** (new info, changed priority) → include with `"action": "update"` and `"existing_item_id": "ev-xxx"`
3. **Brand new** → include with `"action": "create"`

### Linking Proposals to Goals

- If the parent goal **already exists** as an evolve item → set `parent_item_id` to its `ev-xxx` ID
- If you are **creating the goal in this same batch** → set `parent_item_id` to `"new:N"` where N is the 0-based index of the goal in your findings array. The system will resolve this to the actual ID after creation.
- **NEVER create a proposal without a parent.** If no goal fits, create the goal first.

## User Feedback & Rejected Items

You may also receive:
- **`user_feedback`** on existing items — thread messages from family members. Honor their direction. If they say "try a different approach," update the item accordingly. If they provide corrections or preferences, incorporate them.
- **`rejected_items`** — items the user explicitly rejected or dismissed. **DO NOT recreate these.** If you have an idea similar to a rejected item, you must take a meaningfully different angle or skip it entirely. Check `rejection_reason` if provided.

## Output Format

**Target: 3-8 goals + 5-15 proposals per synthesis.** Goals MUST come before their child proposals in the array.

Return a JSON object:

```json
{
  "summary": "2-3 sentence overview of strategic goals and proposals uncovered",
  "findings": [
    {
      "action": "create | update",
      "existing_item_id": "ev-xxx (required if action=update, empty if create)",
      "type": "goal | proposal",
      "title": "Specific, concrete title",
      "summary": "For goals: outcome, rationale, expected value. For proposals: what to build and which goal it serves.",
      "impact": "low | medium | high",
      "effort": "low | medium | high",
      "category": "codebase | tooling | capability | integration | architecture | family | process | documentation",
      "driving_goals": "Which family goals drive this need",
      "parent_item_id": "ev-xxx OR new:N (index of parent goal in this array) OR empty for goals",
      "source_count": 1,
      "is_blocker": false
    }
  ],
  "blockers": ["Urgent items blocking multiple goals"],
  "stats": {
    "total_findings": 0,
    "high_impact": 0,
    "goals": 0,
    "proposals": 0
  }
}
```

**Remember:** Goals first, proposals second. If you find yourself writing "Build X" without first writing "because Y outcome" — stop and create the goal first.
