# M28 reliability verification - PARTIAL

Final code passed all 757 backend tests with exact default-collection identity
matching, four native zero exits and no skipped tests. The final live recheck
passed 18/18 primary detection, kind and source-coverage screens. Whole-field
author review still found unsupported explanatory clauses; this is not a release
or a claim of fully reliable findings.

The engineering fix adds bounded caller context to API jobs, the Python client
and CLI submit --context-file. Every role receives the same owned immutable
snapshot documents. Limits are four paths and 6000 UTF-8 bytes, idempotency
includes the request, prompt pressure never silently drops it, and neither task
permissions nor inspection receipts expand. Context guidance is conditional,
keeping stable policies compact. Final tests prove delivery to all seven roles;
the live harness asserted contract bytes/hashes before every actual dispatch.

Both clean public bitcounts now respect the nonnegative input domain. The
iterator impacts use concrete actual/expected witnesses. Closure outputs no
longer invent an exception from invoking a callback that empty input never
creates. The earlier missing-impact fixture completed naturally in the recheck,
without field fabrication or an extra repair.

Retained failures matter. The first v5.0 live attempt completed only 10/18
reviews, with eight primary passes, a quarantined missing-impact submission
after its one repair, and an unknown Planner call. Its original backend run had
a compact-policy regression and an interrupted worker. All original artifacts
remain. v5.1 moved shared-context guidance out of the stable policy and into a
conditional skill; the subsequent full backend run passed.

Final author review inspected all four claim fields in all 12 final findings:

- Full Python bitcount correctly detects nontermination but incorrectly says
  XOR flips the lowest set bit: 3 XOR 2 = 1 leaves that bit set.
- A raw Python specialist incorrectly generalizes the n=1 fixed point to every
  odd n: n=3 changes to 1.
- A raw iterator description contrasts zero with the correct sum without
  qualifying permitted zero-sum inputs. Its concrete impact and repair are valid.

Closure binding descriptions also need the ordinary qualification that equal
values, one-element inputs and the last reader can return the expected value.
A valid failing witness does not establish failure for every callback. Neither
gold labels nor actual findings were rewritten to improve these scores.

M28 conservative cost is US$0.34770075, including US$0.02324550 retained for
the unknown call; known usage is US$0.32445525. Final public and synthetic phases
cost US$0.13256700 and US$0.09375675, with no new unknowns or cap refusals.
Combined original M26 envelope usage is US$0.51671175 / US$0.60; M27 is
US$0.48210000 / US$1.40. Shared conservative spend is US$7.11897075 / US$9,
remaining US$1.88102925. All historical unknown holds total US$0.12293325 and
remain included. The revised internal ceiling added no user grant.

Generated wire parity, compilation, diff checks and literal credential scans
passed. The previously approved two LangSmith trace writes/readbacks were not
repeated; exporter and SDK hashes remain unchanged. No commit, push, PR or
deployment occurred. This is exposed regression author review, not independent
human adjudication, a fresh holdout, alternate-provider validation or an SLA.

Evidence: tasks/evidence/m28-closing-review.json;
m28-backend-02/summary.json; m28-whole-claim-review.json;
m28-review-witnesses.json; both m28-*-settlement-02.json receipts;
m28-source-archive-01.json and m28-source-archive-02.json.
The two remaining issue groups continue in [M29](m29-claim-consistency-plan.md).
