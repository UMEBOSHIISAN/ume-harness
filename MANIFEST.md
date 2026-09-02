# Release Manifest (ume-harness v0.1.4)

`ume-harness-engineering` is the sole canonical source. The public
`ume-harness` repository is a generated release mirror and is not a supported
source for edits or reverse synchronization.

The machine-readable source of truth is `package_manifest.json` →
`release.payload`. `scripts/release_promote.py` accepts only a clean canonical
checkout, copies only this explicit closure, generates `RELEASE_IDENTITY.json`,
runs the test suite, and compares the staged bytes with a clean public mirror.
It has no publish, push, merge, import, or public-to-engineering operation.

Ambient files, ignored files, untracked scratch, caches, and repository history
do not become release bytes merely because they exist in the checkout.

Release payload count: 67 files (66 canonical source files plus one generated
`RELEASE_IDENTITY.json`).

```
.gitignore
.github/workflows/ci.yml
LICENSE
MANIFEST.md
NOTICE
PHASE4_HOLD.md
QUARANTINE_NOTICE.md
README.md
assets/brand/ume-harness-lockup.svg
RELEASE_IDENTITY.json
SECURITY.md
SUPPORT_MATRIX.md
VERSION
adapters/claude-code/README.md
adapters/claude-code/lease_gate_runner.py
adapters/claude-code/permission_request_hook.py
adapters/claude-code/posttooluse_failure_hook.py
adapters/claude-code/pretooluse_hook.py
adapters/claude-code/settings.json.fragment
bin/ume-harness
common-language/packs/ja-JP/p0_concepts.json
common-language/schema/concept_pack.schema.json
contracts/authority_contract.md
contracts/autonomous_stop.md
contracts/task_intake.md
contracts/tool_policy.md
design/clarification_impact_contract_v0.md
domain_descriptor.json
examples/basic_usage.md
package_manifest.json
runtime/activation_updater.py
runtime/common_language_pack.py
runtime/decision_state.py
runtime/hook_setup_service.py
runtime/human_layer_adapter.py
runtime/local_execution_gate.py
runtime/local_execution_lease.py
runtime/local_execution_lease_state.py
runtime/stop_adapter.py
runtime/tool_policy.py
runtime/translation_konjac.py
schemas/intent_interpreter_output.schema.json
scripts/health_check.py
scripts/install.sh
scripts/release_promote.py
scripts/uninstall.sh
tests/acceptance_record_claude.md
tests/case1_acceptance_v2_spec.md
tests/case1_v2_sampling_contract.md
tests/test_claude_code_adapter.py
tests/test_cli.py
tests/test_human_layer_adapter.py
tests/test_local_execution_gate.py
tests/test_local_execution_lease.py
tests/test_local_execution_lease_state.py
tests/test_portable_core.py
tests/test_release_lifecycle.py
tests/test_translation_konjac.py
ux/japanese-human-layer/README.md
ux/japanese-human-layer/contracts/human_request_contract.md
ux/japanese-human-layer/fixtures/expected_behavior.jsonl
ux/japanese-human-layer/fixtures/vague_requests_ja.jsonl
ux/japanese-human-layer/prompts/clarification_batcher.md
ux/japanese-human-layer/prompts/execution_preview.md
ux/japanese-human-layer/prompts/intent_interpreter.md
ux/japanese-human-layer/prompts/result_presenter.md
ux/japanese-human-layer/tests/test_human_layer.py
```

## Installed release identity

`package_manifest.json` declares a 40-file install payload. The frozen byte
identity covers 39 explicit files, including the manifest itself. Only the
executing `scripts/health_check.py` trust anchor is excluded to avoid a
self-referential digest. It embeds the expected SHA-256 root and fails unless
the declared mandatory closure and actual bytes agree.

Mandatory closure members include Translation Konjac, hook setup, all three
Claude hooks, and the common-language pack and schema.

## Verification

Measured against the v0.1.4 release-candidate bytes on 2026-09-02:

```
python3 -m pytest -q -p no:cacheprovider tests ux/japanese-human-layer/tests
  -> 316 passed

python3 scripts/health_check.py --installed-dir . --identity-only --json
  -> all_passed: true
  -> root: 19ef4ea326a5c5a388ba7a900b82e90e63ed0f3a40e41ebe54271ec1834f252c

python3 scripts/health_check.py --installed-dir . --json
  -> all_passed: true
  -> 40 declared install files present
```

`tests/test_release_lifecycle.py` covers install → setup → offline use → byte
verification → disconnect → uninstall and asserts all final postconditions.
