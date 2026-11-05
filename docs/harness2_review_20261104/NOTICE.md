# Review evidence and limits

This packet is a post-hoc review of one known Toolz task. New inference calls: zero. Original trial artifacts and their 110-file evidence packet remain unchanged. Counterfactual edits were explicitly authored by the analyst and tested only against existing Target/Controls; they are not Agent repairs or accuracy gains. Names-only repair exposes duplicate output. Removing the duplicated loop too passes the two existing checks, not the whole upstream test suite.

The optional context config smoke uses scripted replies and real independent Docker tests. It verifies wiring, not model performance. Replay estimates are pre-guidance request estimates, not native inference usage. Default config is byte-preserving. All-enabled config increases aggregate estimates on these traces.

The implementation snapshot includes a later guard rejecting context-mode recovery through the legacy two-file recovery command. The original smoke protocol hashes are retained; that guard does not affect context organization. Existing step messages precede guidance injection; effective context-smoke receipts include the post-policy request.

verification/ scripts preserve the exact local diagnostic/replay procedures and D: paths. They require the original trial export, existing conda environment and sandbox image. They do not download data or form a standalone portable benchmark. See the parent review document for a new experiment protocol before claiming reproducible method gains.

Source fragments and diagnostic copies retain the Toolz BSD license under source/. Project additions retain implementation/LICENSE. Harness2 upstream provenance/license remains in the original harness2_20261104 packet. No credentials, .env, models, images, dependencies or complete repository exports are copied.
