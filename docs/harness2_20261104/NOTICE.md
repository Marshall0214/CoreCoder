# Evidence scope

This packet preserves the 2026-11-04 restricted Harness² integration trial, including the first failed attempt and post-adoption recovery. It is not a 50-task result or evidence of improved accuracy. The frozen own-agent baseline remains 21/50.

The completed trial used 28 native model calls / 196,025 tokens. The earlier failed attempt used 9 calls / 54,283 tokens. Combined usage is 37 calls / 250,308 tokens, verified against 11 local Langfuse inference traces. Controller spans do not duplicate generations. Paid API usage is zero; local computation is not priced.

The original partial summary/core-result is retained; recovery.json documents completion of reflection, grading and publication without repeating four rollouts. Final agg1 is adopted before independent scoring and remains unresolved: Target fails with undefined iteritems; Controls pass. No new experience entry was retained. Checks are hand-authored Target/Controls, not the full upstream Toolz suite.

Implementation snapshots are the final integration/recovery version. The original protocol records the earlier executing version's hashes. Initial proposals/rollouts were not regenerated using the later lossless duplicate-alias transport.

Harness² upstream source is pinned by commit and per-file hashes, downloadable with integrations.fetch_harness2; Apache-2.0 license is retained under upstream/. Toolz source fragments in trajectories are covered by licenses/toolz-LICENSE.txt. CoreCoder/project code retains licenses/project-LICENSE and its existing provenance. Full model requests are local development evidence; no .env files, credentials, full repository exports, model files, Docker images or dependencies are included.

Runtime paths refer to the original D: workspace. verification/readback.py is the exact local acceptance helper, not a portable replay launcher. The maintained entry point and prerequisites are in docs/harness2-integration.md. No claim of official full Windows benchmark support or unseen-task generalization is made.
