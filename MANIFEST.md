# v0.2.0 release manifest — thin Japanese decision support

Technical Preview v0.2.0, intentionally incompatible with v0.1.7 managed features.
Only ume-harness-engineering is canonical; public ume-harness is a generated
one-way mirror. Installation never migrates live settings automatically.

package_manifest.json defines release.payload, install_payload and the immutable
release_identity.closure. release_promote.py stages only these bytes and does not
publish or reverse-sync. Existing installations are not overwritten, even with
--force. Keep old source/prefix until explicit disconnect.

## Generated release closure

70 files including one generated RELEASE_IDENTITY.json.

```
.gitignore
.github/workflows/ci.yml
CHANGELOG.md
LICENSE
MANIFEST.md
NOTICE
PHASE4_HOLD.md
QUARANTINE_NOTICE.md
README.md
README.en.md
assets/brand/ume-harness-lockup.svg
assets/readme/en/translation-konjac-cards.svg
assets/readme/en/ume-harness-human-layer.gif
assets/readme/en/ume-harness-human-layer-poster.png
assets/readme/en/ume-stack-responsibility.svg
assets/readme/ja/translation-konjac-cards.svg
assets/readme/ja/ume-harness-human-layer.gif
assets/readme/ja/ume-harness-human-layer-poster.png
assets/readme/ja/ume-stack-responsibility.svg
assets/readme/source/asset-build.toml
assets/readme/source/fonts/NotoSansJP-Regular.ttf
assets/readme/source/fonts/OFL-1.1.txt
assets/readme/source/generate_ume_harness_assets.py
assets/readme/source/requirements-assets.txt
RELEASE_IDENTITY.json
SECURITY.md
SUPPORT_MATRIX.md
VERSION
adapters/claude-code/README.md
adapters/claude-code/permission_request_hook.py
adapters/claude-code/posttooluse_failure_hook.py
adapters/claude-code/settings.json.fragment
bin/ume-harness
common-language/packs/ja-JP/p0_concepts.json
common-language/schema/concept_pack.schema.json
contracts/authority_contract.md
contracts/task_intake.md
contracts/tool_policy.md
design/clarification_impact_contract_v0.md
domain_descriptor.json
examples/basic_usage.md
package_manifest.json
runtime/common_language_pack.py
runtime/hook_setup_service.py
runtime/human_layer_adapter.py
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
tests/test_hook_registration_diagnostics.py
tests/test_presentation_safety.py
tests/test_cli.py
tests/test_preview_handoff.py
tests/test_human_layer_adapter.py
tests/test_portable_core.py
tests/test_release_lifecycle.py
tests/test_translation_konjac.py
ux/japanese-human-layer/README.md
ux/japanese-human-layer/contracts/human_request_contract.md
ux/japanese-human-layer/fixtures/expected_behavior.jsonl
ux/japanese-human-layer/fixtures/vague_requests_ja.jsonl
ux/japanese-human-layer/prompts/intent_interpreter.md
ux/japanese-human-layer/tests/test_human_layer.py
```

## Installed v0.2.0

28 files; 27 identity members.
Only the health checker itself is excluded from its recursive root calculation;
its independent hash remains pinned by the release/ownership verifier.
Current root/checker anchors are frozen in scripts/health_check.py and
scripts/release_promote.py after implementation. Historical anchors remain for
ownership diagnostics, not as current feature claims.

-> root: 44180c01f105bb17d8189e43cb78643a0c897f01590455b6e1d4d02f806ee069
-> checker: 7fe93582cd63a481d970aa15667e395212b4a1cbc96c7eb1fea0a0b58b319069

The payload contains preview/meaning, the Japanese language pack, two presentation
hooks and ownership/install diagnostics. Custom PreToolUse/Lease/token/Stop and
notifier/OSC execution routes are retired. Legacy registration recognition is
retained solely for diagnosis/explicit disconnect; user state is preserved.

## Verification

```bash
python3 scripts/health_check.py --installed-dir . --identity-only --json
python3 -m pytest -q -p no:cacheprovider tests ux/japanese-human-layer/tests
```

Fresh isolated lifecycle tests cover install -> presentation setup -> offline
preview -> identity/wrapper proof -> disconnect -> uninstall. Source test counts
are reported against their exact tree. f999276 physical observations are a
separate historical baseline in SUPPORT_MATRIX.md, not v0.2.0 real-host acceptance.
