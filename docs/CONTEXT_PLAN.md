# Context Plan

What the partner knows when it speaks, what's wrong with that now, and what we'll change. Written 2026-11-08 against `main` plus the uncommitted thinking and reply-length changes.

- **Read first:** [CLAUDE.md](../CLAUDE.md) and [DECISIONS.md](DECISIONS.md).
- **Needs agreement from all four tracks:** the [rule change](#rule-change). Everything else stays inside the tracks named on each work package.

## Summary

- **The partner can't see its own last line.** Every model call is a new, one-message request. Its only record of the conversation is a `TURNS` list inside a 1,200-character block, and the cap cuts that list to one line: the player's current words, which the model already has.
- **The 1,200-character cap was sized for Gemini Flash-Lite** ([context.py:51](../brain/memory/context.py#L51)). Every role now runs on Haiku 5.5 or Sonnet 5.5, so cost is no longer a reason to keep it. Haiku 5.5 reads up to 1M tokens at $0.10 per million.
- **We still keep a budget, for two reasons.** A player turn's model call already takes 1.16 s at the median with thinking on, before speech. And accuracy drops as context fills with material that doesn't matter (see [Research](#research)). The new budget is counted in tokens, set per layer, logged, and about 15 times larger than today's.
- **The change:** recent conversation goes in as real messages; memory goes in a cached block; live state and the player's words go last; and a background Sonnet pass keeps a rolling summary plus the partner's own notes.

## What's wrong now

Measured read-only from `data/brain.sqlite3` by running stored sessions back through the real `gather_context` and `render_context`.

| Finding | Evidence |
|---|---|
| The partner's last line never reaches the model | Session 14 (Minecraft, 31 turns): at all 14 player turns, `TURNS` kept one line, the player's own words. This used the facts and note the session ended with, so turns before the first note had more room |
| It asks the same question twice | Session 14 ends with the partner asking "building, exploring, redstone, or fighting?" a second time, and the player saying "You just asked me that." The model got only that last line |
| Half the facts are hidden | 16 current facts, 13 of them from the player. The context shows at most 8, ordered by source and then newest ([gather.py:72](../brain/memory/gather.py#L72)), not by what's being discussed |
| What tools found is gone next turn | Every turn starts a new tool chat ([turn.py](../brain/agent/turn.py)) |
| The deep model gets the same 1,200 characters | `think_hard` builds its prompt from the same block ([handlers.py:285](../brain/agent/handlers.py#L285)) |
| Tips repeat | The tip prompt says not to repeat a recent tip, but past tips aren't in the context |
| No game history | `NOW` is a snapshot that clears after 5 s. No session in the database has a game event logged yet, only turns |

Three causes add up:

1. [claude.py:120](../brain/llm/claude.py#L120) sends one user message per call, with no earlier turns.
2. The partner's own lines appear only inside the system prompt, which calls them "reference data… not part of the conversation" ([context.py:13](../brain/memory/context.py#L13)).
3. Trimming drops turns before facts ([context.py:176](../brain/memory/context.py#L176)). Memory subscribes to the bus before the director ([app.py:94](../brain/app.py#L94), [app.py:179](../brain/app.py#L179)) and its database runs on one thread, so the newest stored line is always the player's current words.

## Sizes

| What | Size |
|---|---|
| Persona and rules prompt | about 330 tokens |
| Tool guidance | about 700 tokens |
| Tool declarations | not measured yet; C2 counts them |
| Session 14's whole conversation | 31 turns in 4.2 minutes, about 700 tokens: roughly 165 tokens a minute of steady chat |
| Average session note | about 90 tokens |

Thirty minutes of steady chat comes to about 5,000 tokens. Size isn't the problem. The problem is what we choose to send and where it sits.

## Research

| Source | Finding | What we take from it |
|---|---|---|
| Anthropic, *Effective context engineering for AI agents* (Sep 2025) | Context is "a finite resource with diminishing marginal returns": aim for the smallest set of high-signal tokens. It recommends loading some context up front and fetching the rest with tools ("just in time"), summarizing old conversation, keeping structured notes outside the context, and clearing old tool results | Load a small memory block and the recent conversation up front. Keep wiki, closer looks and recall as tools. Summarize older turns. Keep tool results as one-line notes |
| Chroma, *Context Rot* (Jul 2025), 18 models including Claude | Accuracy drops as input grows, even on simple tasks. Related but wrong passages hurt more than unrelated ones. On LongMemEval, focused prompts of about 300 tokens beat full ones of about 113k for every model; Claude had the largest gap, mostly from declining to answer | Don't drop the budget altogether. Always send the player's facts, but send observed and wiki facts and recall only when they match the question |
| Liu et al., *Lost in the Middle* (TACL 2024) | Models use information at the start and end of a long context best. Chroma saw no clear position effect in its tests, so this is cheap insurance, not a law | Fixed rules first. Live state and the player's words last |
| Park et al., *Generative Agents* (2023) | Retrieve memories by recency, importance and relevance. A periodic "reflection" step writes higher-level conclusions back into memory | Rank facts and recall on all three. A background pass writes the partner's working notes |
| Wang et al., *Recursively Summarizing* (2023) | Folding each new stretch of dialogue into a running summary keeps long conversations consistent, and adds to what long context gives | A rolling summary of turns older than the verbatim window |
| Maharana et al., *LoCoMo* (ACL 2024) | Long context and retrieval help but stay far below people, and are worst at reasoning about time | Put an age on everything: "2 min ago", "said 10 min ago" |
| Chhikara et al., *Mem0* (2025, from the vendor) | Retrieving selected memories instead of sending the whole history cut p95 latency by 91% and tokens by over 90% on LoCoMo | Across sessions, retrieve. Never send an earlier session's raw turns |
| Pipecat, *Context summarization* docs | Voice agents keep recent messages and summarize older ones, by default once context passes 8,000 tokens, optionally on a cheaper model | The same pattern in our own code, since we keep the LLM out of the Pipecat pipeline |
| Anthropic, prompt caching | Up to 85% lower latency on long prompts: a 100k-token book went from 11.5 s to 2.4 s. Haiku 5.5 caches prefixes from 512 tokens; an entry lives 5 minutes and each read renews it | Cache the fixed prefix and the conversation. Our prompts are short, so expect much less than 85%, and measure it |

## Decisions

These are proposals until the tracks agree. Each one is small enough to reverse.

1. **One conversation for the whole partner.** Player turns, event reactions, tips and `think_hard` read the same log. Today each one builds its own block with its own search query.
2. **Real messages.** Recent player lines go in as `user` messages and partner lines as `assistant` messages. Game events become short notes in the user turn, such as `(game, 40 s ago) danger started: Blue Slime`. Tool results become one-line notes on the partner's turn, such as `[looked closer: holding a Copper Pickaxe]`. Each call rebuilds this from our own log as plain text, without earlier turns' thinking.
3. **Four layers in a fixed order, cached:**

   | Layer | Holds | Changes | Cache |
   |---|---|---|---|
   | 1. Rules | Persona, rules, tool guidance, tools | When personality, hints or the tool set change | Breakpoint |
   | 2. Memory | Game brief, every player fact, the best-matching observed and wiki facts, last session's note, rolling summary, partner's notes | A few times a session | Breakpoint |
   | 3. Conversation | Last turns word for word, with event and tool notes | Grows at the end | Breakpoint on the last earlier turn |
   | 4. Live | `NOW` with ages, the last 2 minutes of game events, partner state, `ASKED`, recall for this question, open wiki page, then the player's words | Every call | None |

4. **A token budget per layer, logged on every call.** Starting values: conversation word for word up to 3,000 tokens (about 20 minutes of steady chat), older turns summarized; memory up to 1,500; live up to 800. That is about 5,000 tokens in all, against about 300 now. Raise a layer only when an eval shows it helps.
5. **A fast talker and a slow reflector, never one after the other.** Haiku answers. Sonnet runs in the background and rewrites the rolling summary and the partner's notes. `think_hard` gets layers 2 and 3.
6. **Code keeps the partner's own state, without a model.** It tracks the last question and whether it was answered, the last three tips, the last tool result, and anything the partner promised to watch.
7. **Vision stays out of the talker.** Screen reports keep reading one frame with no history, because the two-report check needs independent reads. Vision tools return text, which is logged as tool notes (decision 2).
8. **Thinking stays on at low effort.** Caching wins back part of its cost. Streaming a tool turn's first sentence to TTS is the next lever for latency (tool turns aren't streamed today), but it's separate work.

## Work packages

| WP | What | Track | Size | Needs first |
|---|---|---|---|---|
| C1 | Stop the cap from cutting the conversation | 4 | about 1 h | Nothing |
| C2 | Prompt caching and token logging | Shared (`brain/llm/`) | 1-2 h | Nothing |
| C3 | Conversation as messages | 4 builds the list; shared and 3 send it | 3-4 h | C1, C2 |
| C4 | Tool and event notes in the log | Shared (`brain/agent/`), 4 | 1-2 h | C3 |
| C5 | Partner state | 3 | about 1 h | C3 |
| C6 | Game timeline and recent sights | 2, 4 | 1-2 h | C3 |
| C7 | Rolling summary and partner's notes | 4 | 2-3 h | C3 |
| C8 | Context evals | All | about 2 h, then ongoing | C1 |

### C1: stop the cap from cutting the conversation

- Replace `total_chars` with an estimated token budget (characters / 4) of about 5,000.
- Leave the newest player turn out of `TURNS` when it matches the transcript or is part of it, as with carried turns. It's already the message.
- Never trim the last 4 turns. Send every current player fact, plus up to 5 observed or wiki facts.
- Reword the preamble: `TURNS` is the conversation so far, and lines marked partner are what you said.
- Search recall with the transcript plus the partner's last line, so "that" and "it" find something.
- **Done when:** running session 14 back through the context, every player turn includes the partner's line before it, and a unit test covers that shape.

### C2: prompt caching and token logging

- Split the system prompt into two blocks, with rules (layer 1) first and marked for caching, and the context after it. This works before C3.
- Log `input_tokens`, `cache_read_input_tokens` and time to first token for each role. Add cache hit rate to `scripts/latency_report.py`.
- Count the tool declarations once with `count_tokens`.
- **Done when:** two player turns in a row show cache reads on the second one, and median and p95 time to first token are recorded before and after.

### C3: conversation as messages

- Add `brain/memory/conversation.py`. It returns turns, event notes and tool notes in time order within the layer-3 budget, plus the rolling summary for older turns.
- Extend the LLM interface so a call can take earlier messages, and `ToolChat` can start from them. Gemini must accept the same input, since every vendor sits behind one interface.
- Move memory to layer 2 and live state to layer 4. Merge consecutive messages from the same speaker.
- **Done when:** in replay, "what did you just ask me?" gets the right answer, and asking the same question twice no longer happens on session 14's script.

### C4: tool and event notes

- Log each tool call as an event, `tool.<name>`, with a result of 120 characters or fewer. Event reactions log the event they answered.
- These notes reach layer 3 and the session notes.

### C5: partner state

- The director keeps the last question and whether it was answered, the last three tips, the last tool result and any promise to watch. It renders them as a `YOU` section in layer 4.
- The tip prompt checks the tips list, so tips stop repeating.

### C6: game timeline and recent sights

- The tracker keeps the last 5 different `seen` summaries with their times (track 2). Memory renders the last 2 minutes of game events from the `events` table with their ages (track 4).
- First confirm in a live run that game events are being logged at all. The database has none yet.

### C7: rolling summary and partner's notes

- Add a new kind of session note, `working`, written by Sonnet in the background. It holds a summary of turns that have left the word-for-word window, plus the partner's notes: what the player is trying to do, open threads, and what the partner suggested or promised.
- It runs when the word-for-word window overflows, every 20 turns, when a fight ends, or every 5 minutes. It never runs on the voice path.

### C8: context evals

- **Free, with no model calls:** for every player turn in recorded sessions, the partner's previous line is present, every player fact is present, and no layer is over its budget.
- **Paid, small, approved first:** how often the partner repeats a question from its last 10 lines; "what did you just say or ask" probes; recall of a player fact given more than 5 minutes earlier; contradicting a player fact.
- **Latency:** time to first token and to first audio, median and p95, for each role, plus cache hit rate.
- Results go in the Benchmarks table in [TEST_PLAN.md](TEST_PLAN.md).

## Rule change

`CLAUDE.md` says now: "Fight context drift: the talker only gets a small pre-assembled context, never raw session history. Use rolling summaries."

Proposed: "Fight context drift: the talker gets the recent conversation as messages, a rolling summary of older turns and a pre-assembled memory block, within a logged token budget. It never gets the raw event log, or earlier sessions' turns."

This keeps the rule's aim: a bounded window plus a summary isn't raw history. Agree it before C3 lands, and record it in [DECISIONS.md](DECISIONS.md).

## Risks

- **Thinking and edited history.** With thinking on, Haiku 5.5 checks thinking blocks sent back against an edited history. We rebuild history from our own log and send no earlier turns' thinking, so nothing is checked. Confirm that with one live call before merging C3. Within a tool turn, thinking is still sent back unchanged, as it is now.
- **Cache misses.** A change of personality, hints or tool set changes the cached prefix. Tips use only `point_at`, and blinding removes tools, so each of those caches separately. Switching thinking on or off also clears cached messages, so keep the roles that share a cache on the same setting.
- **Quiet gaps.** An entry expires after 5 minutes unread, so the first turn after a long lull pays full price. Measure how often that happens before paying double for the 1-hour cache.
- **The leak filter names sections** ([talker.py:111](../brain/director/talker.py#L111)). Update it whenever a section is added or renamed.
- **More context, longer replies.** Rerun the reply-length checks from the thinking change after C3.
- **File length.** [claude.py](../brain/llm/claude.py) is 228 lines, and caching plus messages may push it past 300. Split it if so.

## If time is short

1. C1 alone fixes the measured bug.
2. C2 next: it wins back part of the latency that thinking added.
3. C3 to C5 are the real fix.
4. C6 and C7 can wait until after the demo.

## Sources

- Anthropic, [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents), 2025-09-29
- Hong, Troynikov and Huber (Chroma), [Context Rot: How Increasing Input Tokens Impacts LLM Performance](https://www.trychroma.com/research/context-rot), July 2025
- Liu et al., [Lost in the Middle: How Language Models Use Long Contexts](https://arxiv.org/abs/2307.03172), TACL 2024
- Park et al., [Generative Agents: Interactive Simulacra of Human Behavior](https://arxiv.org/abs/2304.03442), 2023
- Wang et al., [Recursively Summarizing Enables Long-Term Dialogue Memory in Large Language Models](https://arxiv.org/abs/2308.15022), 2023
- Maharana et al., [Evaluating Very Long-Term Conversational Memory of LLM Agents](https://aclanthology.org/2024.acl-long.747), ACL 2024
- Chhikara et al., [Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory](https://arxiv.org/abs/2504.19413), 2025
- Pipecat, [Context summarization](https://docs.pipecat.ai/guides/fundamentals/context-summarization)
- Anthropic's prompt caching launch, as reported by [SD Times](https://sdtimes.com/ai/anthropic-introduces-prompt-caching-to-reduce-latency-and-costs). Haiku 5.5's 512-token minimum is from Anthropic's prompt caching documentation
