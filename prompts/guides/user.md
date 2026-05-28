# SkipperBot User Guide

Welcome! I'm Skipper — your personal AI assistant. I live in Discord and I'm always
listening. Just talk to me naturally. Here's everything I can do and how to ask for it.

---

## Memory

I remember things from our conversations automatically, but you can also tell me
things explicitly.

- "Remember that Bob's favorite color is blue"
- "Remember the wifi password is Sunshine42"
- "What do you know about Bob?"
- "What do you remember about the kitchen project?"
- "Forget that — the password changed"

I also learn on my own. After every conversation, I extract key facts and save them.
Next time we talk, I'll recall relevant context automatically.

---

## Reminders

I can remind you (or anyone in the family) about anything — one-time, recurring, or
persistent daily nags.

**One-time reminders:**
- "Remind me at 3pm to call the vet"
- "Remind me tomorrow morning to check the mail"
- "Don't forget to pick up groceries at 5"

**Recurring reminders:**
- "Remind me every Monday at 9am to check email"
- "Every weekday at 7am, remind me to take my vitamins"
- "Remind me on the 1st and 15th of every month to pay bills"

**For events (I'll remind you early):**
- "I have a doctor's appointment Monday at 3:30pm" → I'll remind you at 3:00pm
- "Bob has soccer practice at 5pm tomorrow" → I'll remind you at 4:30pm

**Managing reminders:**
- "What reminders do I have?"
- "Cancel that reminder"
- "Change that reminder to 10am"

### Nags

If you don't give me a specific time or date, I'll set up a **nag** — a gentle
daily nudge at a random time until you tell me to stop. Perfect for things
without a hard deadline.

- "Don't let me forget to do my taxes" → nag (no time = nag)
- "Nag me to clean the garage" → nag
- "Don't let me forget to return those library books" → nag
- "Bug me every morning to check on the garden" → morning nag
- "Nag me in the evening to review my notes" → evening nag
- "I need to remember to call the dentist" → nag (no time = nag)

### Snooze

When a reminder fires and you're busy, just tell me to come back later:

- "Come back in an hour"
- "Remind me again in 30 minutes"
- "Snooze that for 2 hours"
- "I'm busy, follow up later"
- "Put it off for an hour"
- "Yeah yeah, try again in 45 minutes"

I'll create a one-time follow-up with the same message. You can snooze the follow-up
too — no limit.

---

## Goals, Projects & Tasks

I track goals, projects, and tasks in a hierarchy. Think of it as your family
productivity system.

**Creating things:**
- "Create a goal to renovate the kitchen"
- "Add a project under that goal for cabinet installation"
- "Add a task to measure the countertops"
- "Create a subtask under that to buy a tape measure"

**Checking progress:**
- "What are my goals?"
- "Show me the kitchen renovation project"
- "What tasks do I have?"
- "What's Bob working on?"

**Updating status:**
- "Mark that task as done"
- "Set the countertop task to in progress"
- "Block that task — we're waiting on materials"

**Notes on any item:**
- "Add a note to the kitchen project: contractor said 3 weeks lead time"
- "Show me the notes on that task"

**Due dates:**
- "Set a due date of March 15th on that project"
- "Remind me 3 days before the septic deadline"

**Auto-nag on projects:**
- "Turn on nagging for the kitchen project" → I'll nag about the next task daily
- "Stop nagging me about that project"

---

## Lists & Trello

I manage lists — shopping lists, to-do lists, checklists — with optional Trello sync.

**Basic lists:**
- "Create a shopping list"
- "Add milk to the shopping list"
- "Show me the shopping list"
- "Remove milk from the shopping list"

**Trello integration:**
- "Connect the Trello board 'Home Projects'"
- "Show me the Trello board"
- "Add a card to the 'To Do' list: Fix the fence"
- "Move 'Fix the fence' to 'In Progress'"
- "Archive that card"

**Card details (read & write):**
- "Show me the details on the 'Fix login bug' card"
- "What's the description on that card?"
- "Update the description on 'Fix the fence' to say it needs new pickets"
- "Rename that card to 'Replace fence pickets'"
- "Set a due date on that card for March 15"
- "Add a checklist called 'Steps' with: buy wood, remove old fence, install new"
- "What checklists are on that card?"
- "Add a comment: talked to the neighbor, they'll split the cost"
- "Label that card as 'Urgent' in red"
- "What labels are on the card?"
- "Remove the 'Low Priority' label"

**Item history (sticky items):**
- "Enable item tracking on the Vegetable Aisle list"
- "We need more lettuce" → I'll check where lettuce was last seen and add it to the right board/list
- "Put dog food back on the list" → I'll look up where dog food was before and re-add it there
- "Where did I have light bulbs?" → I'll check item history and tell you which board/list

Enable tracking per-list with `set_item_tracking`. Once enabled, items are remembered
across sessions — once something's been on a tracked list, I'll know where to put it next time.

**Trello-linked project tasks:**
- "Link the Project-Alpha project to the 'project-alpha' Trello board"
- "Create a Trello task under Project-Alpha called 'Quest System'"
- "Adopt the 'NPC Dialogue' card from Trello into the Project-Alpha project"
- "Show me the Project-Alpha project" → tasks grouped by Trello list with live data
- "Show me T3" → live card details with description, checklists, labels, due date
- "Check off item 1 on T1" → checks the first checklist item on the Trello card
- "Uncheck item 3 on T1" → unchecks the third checklist item
- "Mark the first criterion done on Quest System"
- "Mark T3 done" → card moves to Done list on Trello
- "Assign T3 to Dave" → card moves to Dave's Trello list
- "Delete T5" → archives the card on Trello

---

## Documents

I create and manage markdown documents — research notes, reference pages, curated
write-ups.

- "Create a document called 'Vacation Planning'"
- "Add to that document: we're looking at beach rentals in June"
- "Show me the vacation planning doc"
- "Search my documents for 'kitchen'"
- "List all my documents"
- "Delete that document"

**Enhancing documents (AI-powered editing):**
- "Flesh out the introduction"
- "Add more detail about costs"
- "This doc needs a section about risks"
- "Make the whole doc more detailed"
- "Polish up that document"
- "Beef up the planning section"

I'll read the document, figure out which sections need work, and rewrite just
those sections — the rest stays untouched.

---

## Research

I can do background web research for you. I'll search the web, read multiple sources,
and write up a comprehensive document with my findings.

- "Research the best riding lawn mowers under $3000"
- "Look into solar panel installation costs in Texas"
- "Find out about youth soccer leagues in our area"
- "Investigate options for home security systems"

I'll queue it up and deliver the full write-up to you when it's done (usually a few
minutes).

**Checking on research:**
- "How's that research going?"
- "Check on the lawn mower research"
- "Cancel that research"
- "List my research jobs"

**Refining results:**
- "Add more detail about the pricing section"
- "Expand on the installation requirements"
- "The research needs more info about warranties"
- "Revise the research to include electric models"

---

## Knowledge Base

I can read and learn from web pages so I can reference them later in conversation.

- "Learn from this URL: https://example.com/important-article"
- "Read this site and follow the links" → I'll crawl the whole documentation site
- "What do you know about [topic]?" → I'll search my knowledge base automatically

---

## Notifications & Messaging

**Discord DMs:**
- "Tell Bob that dinner is at 6"
- "Send Alice a message about the meeting"

**Push notifications (Alice):**
- "Send me a push notification about this"

**Notification history:**
- "What notifications went out today?"
- "Show me recent notifications"

---

## Document Printing

I can print any of your documents to the physical printer.

- "Print that document"
- "Print the vacation planning doc"
- "Print 3 copies of that"

---

## Weather

- "What's the weather?" or "What's the weather in 75001?"
- "What's the chance of rain overnight?"
- "Will it rain over the next week?"

---

## Web & Search

- "Search the web for best pizza places nearby"
- "Fetch this URL: https://example.com"
- "Ping google.com"

---

## Files & System

- "Show me the files in /home/alice"
- "Read that config file"
- "Search for files named *.py"
- "Validate that JSON file"
- "Show me the crontab"

---

## Git

- "What's the git status?"
- "Show me the last 5 commits"
- "Show me the diff"
- "Pull the latest changes"

---

## Project Manager

I act as your proactive PM — every morning at 10 AM, I review all your goals,
projects, and tasks and DM you about anything that needs attention.

**What I check for automatically:**
- Missing due dates on tasks or projects
- Overdue items
- Tasks with no one assigned
- Work that's been stale (no progress updates in 3+ days)
- Blocked tasks with no explanation
- Unclear scope or definition of done (via AI evaluation)
- Projects at risk of slipping

**When I find something, I'll DM you with specific questions like:**
- "Task 'Fix the fence' needs a due date. When can you get this done?"
- "Task 'Paint the bedroom' hasn't had updates in 5 days. How's it going?"
- "Project 'Kitchen Reno' was due Jan 15 and is overdue. What's the revised timeline?"

**Just reply naturally and I'll handle it:**
- "March 15" → I'll set the due date
- "It's blocked, waiting on parts" → I'll update the status and add the note
- "Done actually" → I'll mark it complete

I won't spam you — I wait 3 days before asking about the same issue again, and
I cap at 5 items per message.

---

## Jobs

I run background jobs for research, printing, PM checks, and scheduled tasks.

- "What jobs are running?"
- "Check on that job"
- "Cancel that job"

---

## Linking & Cross-referencing

I can connect any entities together — link a reminder to a task, a document to a
project, etc.

- "Link that reminder to the kitchen project"
- "What's linked to this task?"
- "Unlink those two items"

---

## Tips for Talking to Me

1. **Be natural** — I understand conversational language. You don't need special
   commands or syntax.

2. **Be specific about time** — "Remind me at 3pm" sets a timed reminder.
   No time given? I'll create a daily nag instead of guessing.

3. **Reference recent context** — "Cancel that reminder" or "add a note to that"
   works because I remember what we just talked about.

4. **Ask me anything** — If I can't do something, I'll tell you. If I need more
   info, I'll ask.

5. **I learn from you** — The more we talk, the better I get at anticipating what
   you need. I remember preferences, patterns, and context.

6. **Family-aware** — I know the family members and can manage reminders, tasks,
   and messages for everyone.

7. **Ask for help** — "What can you do?" or "How do I use you?" will bring up
   this guide anytime.
