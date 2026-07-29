# ADR-0005: No agent framework and no MCP server

- **Status:** Accepted
- **Date:** 2026-07-29
- **Supersedes:** the OpenAI Agents SDK and MCP entries in DECISIONS.md dated 2026-07-07

## Context

The original plan used the OpenAI Agents SDK for the answer loop and exposed the retrieval layer as
an MCP server so the agent would consume it as a standard tool. I recorded that on 2026-07-07 with
the reasoning that the task is small, so a lightweight framework is the right weight.

Writing the query routing model in section 8 of the technical documentation is what showed me the
argument runs the other way.

## The answer loop is not an agent

An agent framework earns its place when control flow is genuinely dynamic: the number of tool calls
is unknown ahead of time, the model decides what to do next, and there is replanning. None of that
is true here. The loop is:

1. Classify the question.
2. Retrieve, or look up in the ledger.
3. Generate with span attribution.
4. Check support and decide whether to abstain.

Four steps, fixed order, no branching the model controls. **That is a function, not an agent.**
Wrapping it in an agent loop buys nondeterminism, a worse latency tail, and a much harder time
answering "why did it do that".

The irony is the part that decided it: **this project's entire thesis is verifiability and
auditability, and I had chosen the least deterministic available orchestration to deliver it.** A
system whose selling point is that you can check its work should not have a control flow I cannot
predict.

There is a coupling problem too. A provider's agent SDK sits badly with keeping the generator behind
a seam under principle P6, and I want that seam so an EU-hosted generation path stays cheap.

## MCP buys optionality nobody has asked for

The stated benefit was that anything else speaking MCP could call the retriever. Nothing else does.
The candidate consumer was my own agent, in the same process.

What it costs is concrete: a process boundary, a serialisation layer, a transport and a debugging
surface, placed **on the hot path between the answer loop and retrieval**. In the previous
architecture diagram, MCP was the edge label on the single most latency-sensitive hop in the system.

The clearest signal is that the ADR justifying MCP argued against itself. It said the scope is small
enough that the lightest agent framework wins. If the scope is that small, a Python function call
beats a remote procedure call.

## Decision

- **No agent framework.** The answer loop is explicit Python: a classifier, a retriever, a
  generator, a support check. Each behind a protocol per P6.
- **No MCP server in v1.** Retrieval is a module the service imports.

## What would bring them back

I am recording this so the reversal is a decision rather than a drift.

**An agent framework** becomes correct when the number of retrieval calls stops being predictable,
for example multi-hop questions where a first retrieval determines the second query. If M3 shows a
class of questions failing because one retrieval round is not enough, that is the trigger, and it
gets its own ADR.

**MCP** becomes correct when there is a second consumer that is not this service. It is a couple of
hours of work at that point, and building it before then is the definition of speculative.

## Trade-offs I accept

- **I do not get "I used the Agents SDK and MCP" on the project.** I judge that a bad trade for a
  slower, less explainable system, and being able to explain why I did not use them is a better
  answer than having used them.
- **Multi-hop questions are out of scope for v1**, and will show up as a failure class in the M3
  taxonomy rather than being handled.
- **If a second consumer appears sooner than expected**, I pay the couple of hours then rather than
  having it ready.

## The rest of the cut list

Recording alongside this because it is the same judgement applied consistently. Full table in
[STACK.md](../STACK.md#taken-out-and-staying-out): Cohere Rerank (paid vendor added before
establishing a reranker helps), AWS with ECS or EKS (one stateless service and one database),
Bedrock (unimplemented optionality), Next.js (scope that does not exist), and Ragas as a CI gate
(kept nightly, see ADR-0006).

The single largest risk to this project finishing is scope creeping back toward that list. Nothing
on it returns without an ADR saying what changed.
