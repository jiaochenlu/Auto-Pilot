# Framing: Mock Test This New Flow Design

## Problem Statement

The requester wants the new flow design to be mock tested, but the request does not yet identify which product area, files, modules, prototype, or subsystem should be examined. The expected result of the mock test is also undefined, including what evidence would count as success from the requester's perspective.

Before research or implementation begins, the work needs enough context to identify the flow under test, the relevant source or design artifacts, the user journey to exercise, and the acceptance criteria for the mock test output.

## Non-Goals

- Do not start research, code inspection, implementation, or test execution yet.
- Do not propose fixes or design changes yet.
- Do not assume the target files, modules, or subsystem without requester confirmation.
- Do not define success criteria on behalf of the requester beyond documenting assumptions and open questions.

## Assumptions

- "Mock test" means an early validation activity for a new flow design, not necessarily an automated unit, integration, or end-to-end test.
- The flow design already exists somewhere in the workspace or in external context that the requester can point to.
- AgentLoop should wait for explicit requester input before researching the target area.
- The Q-FILES and Q-OUTCOME items are blocking because they determine scope and success criteria.

## Open Questions

1. Which files, modules, design artifacts, or subsystem should AgentLoop investigate first?
   - Blocking: yes
   - Reason: The work cannot be scoped without knowing where the new flow design lives or which system behavior it affects.
   - Answer:

2. What does success look like from the requester's perspective, and are there non-goals to keep out of scope?
   - Blocking: yes
   - Reason: The mock test cannot be evaluated without expected outcomes, acceptance criteria, and explicit boundaries.
   - Answer:

## Ready For Research

No. Research should not start until the blocking questions above are answered.
