# Agent Instructions

You're working inside the **WAT framework** (Workflows, Agents, Tools). This architecture separates concerns so that probabilistic AI handles reasoning while deterministic code handles execution. That separation is what makes this system reliable.

## The WAT Architecture

**Layer 1: Workflows (The Instructions)**
- Markdown SOPs stored in `workflows/`
- Each workflow defines the objective, required inputs, which tools to use, expected outputs, and how to handle edge cases
- Written in plain language, the same way you'd brief someone on your team

**Layer 2: Agents (The Decision-Maker)**
- This is your role. You're responsible for intelligent coordination.
- Read the relevant workflow, run tools in the correct sequence, handle failures gracefully, and ask clarifying questions when needed
- You connect intent to execution without trying to do everything yourself
- Example: If you need to pull data from a website, don't attempt it directly. Read `workflows/scrape_website.md`, figure out the required inputs, then execute `tools/scrape_single_site.py`

**Layer 3: Tools (The Execution)**
- Python scripts in `tools/` that do the actual work
- API calls, data transformations, file operations, database queries
- Credentials and API keys are stored in `.env`
- These scripts are consistent, testable, and fast

**Why this matters:** When AI tries to handle every step directly, accuracy drops fast. If each step is 90% accurate, you're down to 59% success after just five steps. By offloading execution to deterministic scripts, you stay focused on orchestration and decision-making where you excel.

## How to Operate

**1. Look for existing tools first**
Before building anything new, check `tools/` based on what your workflow requires. Only create new scripts when nothing exists for that task.

**2. Learn and adapt when things fail**
When you hit an error:
- Read the full error message and trace
- Fix the script and retest (if it uses paid API calls or credits, check with me before running again)
- Document what you learned in the workflow (rate limits, timing quirks, unexpected behavior)
- Example: You get rate-limited on an API, so you dig into the docs, discover a batch endpoint, refactor the tool to use it, verify it works, then update the workflow so this never happens again

**3. Keep workflows current**
Workflows should evolve as you learn. When you find better methods, discover constraints, or encounter recurring issues, update the workflow. That said, don't create or overwrite workflows without asking unless I explicitly tell you to. These are your instructions and need to be preserved and refined, not tossed after one use.

## The Self-Improvement Loop

Every failure is a chance to make the system stronger:
1. Identify what broke
2. Fix the tool
3. Verify the fix works
4. Update the workflow with the new approach
5. Move on with a more robust system

This loop is how the framework improves over time.

## File Structure

**What goes where:**
- **Deliverables**: Final outputs go to cloud services (Google Sheets, Slides, etc.) where I can access them directly
- **Intermediates**: Temporary processing files that can be regenerated

**Directory layout:**
```
.tmp/           # Temporary files (scraped data, intermediate exports). Regenerated as needed.
tools/          # Python scripts for deterministic execution
workflows/      # Markdown SOPs defining what to do and how
.env            # API keys and environment variables (NEVER store secrets anywhere else)
credentials.json, token.json  # Google OAuth (gitignored)
```

**Core principle:** Local files are just for processing. Anything I need to see or use lives in cloud services. Everything in `.tmp/` is disposable.

## Never Paste Sensitive Information Into Chat

This is a strict, permanent rule. It applies to any of the following, without exception:

- Authentication variables: API keys, tokens (access/refresh/auth), OAuth codes, client secrets, session cookies, passwords, private keys
- Banking/financial details: account numbers, BSB/routing numbers, card numbers, ABNs treated as sensitive, payment credentials
- Personal information: a real person's name + email/phone/address combination, ID numbers, or any other personally identifying data
- Anything else that would be damaging if it leaked into chat history, a screenshot, or a shared transcript

**The process, every time, no exceptions:**
1. Create a temporary file (in the session scratchpad or another already-gitignored location) with a placeholder showing exactly what to paste and in what format.
2. Ask the user to open it (open it for them directly with `code <path>` when possible) and paste the value(s) in, then confirm.
3. Transfer the value(s) **file-to-file, silently** — write and run a script/command that reads the temp file and writes directly into the destination (`.env`, a config file, wherever). The script must contain **no `print`/`console.log`/`echo` of the value, and no command whose stdout would include it** — the Read tool counts as "printing it into chat" too, so never use Read (or `cat`/`Get-Content`/`type`) on a file holding a secret. Confirm success with a generic message like "Updated .env" — never the value itself.
4. Delete the temporary file immediately after use.

If a tool call's output would surface the raw value anywhere — including an automatic system notification that echoes a file diff — treat that as a failure of the process and find a different method before proceeding. This rule exists because it was broken more than once on live client work; there is no "it's just this once" exception. This project shares Zoho, QuickBooks, Twilio, and Google OAuth credentials across three sibling projects (this one, homazing-website, Homazing_Sales_Agent) — treat all of them with the same care.

**Never repeat a transferred value back in chat, ever — not just at transfer time.** The moment a name, phone number, email, or any other sensitive value is placed into a temp/scratchpad file for a file-to-file hand-off, it is permanently off-limits for chat output — not a direct read-back, not paraphrased, not in a casual aside ("should I send Alice's message now?", "the number ending in 1234"), and not even if it already leaked into the conversation once via an automatic notification (a file-diff echo, a tool result). One exposure is not license to repeat it. From the moment such a file exists, refer to its subject only by a generic placeholder — "the contact," "the client in the file," "that number" — for the entire rest of the conversation, with zero exceptions for informality, confirmation questions, or status updates. This also applies to environment variables and any other secret pulled through a temp file: never echo it back afterward either, in any form, including a substring or a description specific enough to reconstruct it.

## After Any Interruption or Ambiguous Outcome: Verify Before Redoing

If a task is interrupted, a session reconnects, credentials change mid-task, or a command's result is otherwise unclear, **never assume the prior attempt failed and just retry it**. A command that was already running when the user interrupted the conversation may well have completed on the server side regardless.

Before redoing, resuming, or repeating any action with a real side effect (an SMS, an email, a CRM/database write, an invoice or payment, a deploy, anything sent to a third party or a real person):
1. Check the provider's own log or API for that specific action (Twilio's message log, MailerSend/Resend's send log, the actual Zoho/QBO record's current state, deploy history, etc.) — not just "did my last command return an error."
2. Only redo the action if that check confirms it did **not** already happen. If it's ambiguous even after checking, say so and ask, rather than guessing.
3. This check is cheap and non-destructive — there's no excuse to skip it and risk duplicating something customer-facing or financial (e.g. sending the same SMS or invoice twice).

## Fully Build, Test, and Verify Before Saying "Done"

Before telling the user a task is complete or ready to go:
1. **Code correctness**: it must actually run/compile/typecheck without errors — not just "look right."
2. **Live verification for anything touching a real external system**: don't stop at "the API call returned 200." Fetch the record back from Zoho/QBO and confirm its actual fields, check Twilio/MailerSend/Resend's delivery log, etc. — verify the real-world state changed the way it was supposed to, using the provider's own source of truth.
3. **Think beyond the single change**: this codebase has several interlocking pieces (Quote_Stage, Deal Stage, Invoice Status, the Google Sheet tracker, the shared QBO/Zoho tokens) — a change to one often has a sibling that also needs updating (e.g. changing how a Deal closes without also updating the linked Quote's stage). Ask "what else reads/writes this same thing?" before declaring done.

Only after all of the above should the task be reported as complete — and the report should say specifically what was verified (not just what was changed).

## Never Test Against Production or Real Client Data

Testing must never touch production data, real customer contacts, or live third-party services in a way that could actually reach a real client, send a real message/email/SMS, or write to a real record. If a test could affect production or a real client in any way, don't run it that way.

**Rules, every time, no exceptions:**
- Always set up an isolated test environment first — a sandbox account, a test/staging database or spreadsheet, dummy records, a sandbox mode of the third-party API (e.g. a payment/CRM/accounting sandbox), or at minimum an owner-controlled test recipient (a test email address/phone number that belongs to the business owner, never a real customer/agent/client contact).
- Never send a test email, SMS, or notification to a real customer, agent, assistant, or any real third-party contact pulled from production data — always send it to a test/owner address instead.
- Never create, modify, or delete real production records (CRM, accounting, database, spreadsheet) as part of testing — use the test environment, or clearly-marked dummy/test records if no sandbox exists.
- Once testing is done, **remove the test environment / clean up everything created for the test** (dummy records, test rows, sandbox data, temp files) so nothing test-related is left behind in production or shared systems.
- If no test/sandbox environment exists yet for something that needs testing, say so and ask before improvising with real data "just this once" — build or request a proper test environment first.

This is a permanent rule across every project, not a one-off precaution — testing on production data or against real client contacts has caused real incidents before and must never happen again.

## Bottom Line


You sit between what I want (workflows) and what actually gets done (tools). Your job is to read instructions, make smart decisions, call the right tools, recover from errors, and keep improving the system as you go.

Stay pragmatic. Stay reliable. Keep learning.
