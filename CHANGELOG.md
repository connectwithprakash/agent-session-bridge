# Changelog

## [0.2.4](https://github.com/connectwithprakash/agent-session-bridge/compare/v0.2.3...v0.2.4) (2026-07-28)


### Bug Fixes

* **claude-code:** drop empty reasoning blocks the API rejects on resume ([269a874](https://github.com/connectwithprakash/agent-session-bridge/commit/269a874fabf80726166b62d238a94e8833b77cde))

## [0.2.3](https://github.com/connectwithprakash/agent-session-bridge/compare/v0.2.2...v0.2.3) (2026-07-28)


### Bug Fixes

* **codex:** assistant turns survive resume (phase + agent_message events) ([2e221dc](https://github.com/connectwithprakash/agent-session-bridge/commit/2e221dc88efb8c55165b90d24f9817d67496d599))

## [0.2.2](https://github.com/connectwithprakash/agent-session-bridge/compare/v0.2.1...v0.2.2) (2026-07-28)


### Bug Fixes

* **codex:** registered sessions now appear in the resume picker ([14c5d17](https://github.com/connectwithprakash/agent-session-bridge/commit/14c5d1745f7ae098b7b9b6f7c4b37054fd5c79b8))

## [0.2.1](https://github.com/connectwithprakash/agent-session-bridge/compare/v0.2.0...v0.2.1) (2026-07-28)


### Bug Fixes

* **tui:** warn when a converted file will not be resumable ([695a45f](https://github.com/connectwithprakash/agent-session-bridge/commit/695a45fdcd8f3b11c1eb28ffa02fe9271991ddb8))


### Documentation

* add Homebrew install option ([4f955c0](https://github.com/connectwithprakash/agent-session-bridge/commit/4f955c09a6fc1ec9e002c1e78fd75d1d3bdd1186))
* record main branch-protection posture and its release-please constraints ([e1fe10e](https://github.com/connectwithprakash/agent-session-bridge/commit/e1fe10e2e1b293e2a3759cb6ae19384de4ef6885))

## [0.2.0](https://github.com/connectwithprakash/session-bridge/compare/v0.1.0...v0.2.0) (2026-07-28)


### Features

* Claude Code resume works from transcript; add --place-claude-cwd ([f1177c1](https://github.com/connectwithprakash/session-bridge/commit/f1177c1f55ee54f79d4c373db4da402ca07120f1))
* **cli:** --version flag; release metadata and compatibility matrix ([f968362](https://github.com/connectwithprakash/session-bridge/commit/f96836210853524bc460c3c6a7e521a4a5e93cdb))
* **cli:** agent-session-bridge command alias for the dist name ([89e200a](https://github.com/connectwithprakash/session-bridge/commit/89e200a07e6967e9df3fa22f53e7dedd6a8e06f4))
* **codex:** register resumable imported sessions ([c20e194](https://github.com/connectwithprakash/session-bridge/commit/c20e194dbbaf5527057345b1373efa2c32b92294))
* cross-harness agent-session portability tool (v1) ([da521b1](https://github.com/connectwithprakash/session-bridge/commit/da521b135d129d9d18fae4b0864df6192bff26d6))
* Hermes resume works end-to-end; add 'register' command ([2213621](https://github.com/connectwithprakash/session-bridge/commit/221362161c747849f8b9e4d6f49e878971c52d75))
* Hermes state.db writer (lists session; context-resume still open) ([3a1bc03](https://github.com/connectwithprakash/session-bridge/commit/3a1bc03d597655fe17757f84ced8cf481f9257fb))
* **review r23:** --stub-open-calls for resumable transcripts; position-precise open_tool_calls ([f5c6941](https://github.com/connectwithprakash/session-bridge/commit/f5c694170ab11e623d19eeaa5136fe722c8e6b55))
* **skill:** package session-handoff skill; install-skill bootstrap ([8bc5a28](https://github.com/connectwithprakash/session-bridge/commit/8bc5a28b4f0ef6aedc92a0555c305b4ebd131350))
* **skill:** repo-shipped session-handoff skill for agents ([33cab89](https://github.com/connectwithprakash/session-bridge/commit/33cab8989140070a849068ca7e51d01b1d3c29cf))
* **tui:** Enter in a form field submits the options/register forms ([8e1f0f4](https://github.com/connectwithprakash/session-bridge/commit/8e1f0f45abd6cb15d35510c4a6602cedde6cfb0b))
* **tui:** interactive convert wizard behind optional textual extra ([0db5a1a](https://github.com/connectwithprakash/session-bridge/commit/0db5a1ad462cf5ac7ddb1df0d8a79119e81ad09d))
* **tui:** pure registration module for hermes and codex stores ([cb4c176](https://github.com/connectwithprakash/session-bridge/commit/cb4c176ad00cb67c6d9a1480950b5589fb319ca4))
* **tui:** register wizard screens with pre-mutation plan view ([37eaae9](https://github.com/connectwithprakash/session-bridge/commit/37eaae9499adaf1a48316aae1f1495fc9a0cccd3))


### Bug Fixes

* Codex reasoning content[] shape; validate reader on real tool session ([863aff2](https://github.com/connectwithprakash/session-bridge/commit/863aff27d9977c37e0f9058952b86fee5f25d4d4))
* **codex:** select target-native resume model ([fc86078](https://github.com/connectwithprakash/session-bridge/commit/fc8607850e566d6cca09d6346e1ab802394e31b3))
* publish distribution as agent-session-bridge ([1be59e4](https://github.com/connectwithprakash/session-bridge/commit/1be59e49ac6f330d0d9bddeb4fc87ac6250d6bd8))
* resolve 5 correctness findings from adversarial review ([61b08db](https://github.com/connectwithprakash/session-bridge/commit/61b08db697937dedf95076b4787c9e4c989556c7))
* **review r11:** preserve empty-text reasoning blocks (Codex); report Hermes loss ([aa4a887](https://github.com/connectwithprakash/session-bridge/commit/aa4a8875103f733d8290e828301e0e9b6ef32433))
* **review r12:** preserve non-text parts inside tool_result.content ([fef04dc](https://github.com/connectwithprakash/session-bridge/commit/fef04dccb62fda67f5829be8e54493be949effff))
* **review r13:** handle queue-operation 'remove' (auto-withdrawn notifications) ([9a27c26](https://github.com/connectwithprakash/session-bridge/commit/9a27c26e279af88d83cfac4bb7eb3ebbfcde9a46))
* **review r14:** queue-op popAll; carry tool_result non-text parts ON the result ([02cca7d](https://github.com/connectwithprakash/session-bridge/commit/02cca7d0d4c610f2d72c2448a8c1e05fe7103336))
* **review r15:** remove queue-op is content-less; withdraw newest (LIFO) ([1acdcbf](https://github.com/connectwithprakash/session-bridge/commit/1acdcbfe5d1961c9b19cb150f42fd3bbecf262ec))
* **review r16:** Hermes reader recovers reasoning from codex_reasoning_items ([ff198f2](https://github.com/connectwithprakash/session-bridge/commit/ff198f24d2fc2a016c34f8d607338e92c76ae3ea))
* **review r17:** filter Claude Code &lt;synthetic&gt; model placeholder ([7b8f17b](https://github.com/connectwithprakash/session-bridge/commit/7b8f17bdbc5eb4fdc01317e05ea6c185df2fe850))
* **review r18b:** cross-harness writers emit placeholder for parts-only tool results ([ac57607](https://github.com/connectwithprakash/session-bridge/commit/ac5760792b61a2893257a43fdc4d18065f30d09e))
* **review r18:** skip isApiErrorMessage records; import Optional ([fd2226a](https://github.com/connectwithprakash/session-bridge/commit/fd2226a8dd7f66ec1a6a98ebdbdc43336223a84f))
* **review r19:** surface tool_result parts even when text is also present ([e9ab89e](https://github.com/connectwithprakash/session-bridge/commit/e9ab89e89496315200def1c8548e6bf8102cd973))
* **review r1:** robust JSONL loading, Codex SYSTEM role, Hermes DB parallel results, +5 more ([ec5fdde](https://github.com/connectwithprakash/session-bridge/commit/ec5fddec08a75d2097235fe6a435da832c6c8d39))
* **review r21:** open_tool_calls reports only tail-outstanding calls ([f7a7908](https://github.com/connectwithprakash/session-bridge/commit/f7a7908dc656e0aa54b7f28bda94163ecff03f64))
* **review r22:** fix open_tool_calls false-negative; surface losses on register ([546a76d](https://github.com/connectwithprakash/session-bridge/commit/546a76dc2833a7a4aaa8b6e252fb87270552f6ed))
* **review r24:** register --stub-open-calls for resumable DB rows ([393c5d3](https://github.com/connectwithprakash/session-bridge/commit/393c5d359383bf0a87291d6e79893ccfd42b72df))
* **review r25:** WAL-safe register backup via SQLite backup API ([29dea39](https://github.com/connectwithprakash/session-bridge/commit/29dea3917ccd2780dc0426b9633acd639802fe24))
* **review r27:** CLI/placement robustness — no silent overwrite, clean errors ([2a21c5c](https://github.com/connectwithprakash/session-bridge/commit/2a21c5cecb2b20f039fb16616dd993e7d3cd413a))
* **review r28:** report tool-schema loss on register; bound cwd length ([6df5797](https://github.com/connectwithprakash/session-bridge/commit/6df5797ed681a05e63c8d1cd2ef29e487b0aff1d))
* **review r2:** path-traversal, RAW passthrough, handshake accumulation, +6 more ([ec24bbf](https://github.com/connectwithprakash/session-bridge/commit/ec24bbf7d97977d50e05256540d43070d5d0d5b7))
* **review r3:** unforgeable handshake marker, Hermes SYSTEM + RAW readers, +5 more ([92788db](https://github.com/connectwithprakash/session-bridge/commit/92788db921b20e4481ab966e9cd9254a03090f36))
* **review r4:** multi-hop is_error recovery, Codex turn-count, +3 more ([ebaa036](https://github.com/connectwithprakash/session-bridge/commit/ebaa0363cb123d78847cba018b2e381b88db84a0))
* **review r5:** Codex block ordering, source-gated RAW loss, Codex model switch, unforgeable error marker ([d851335](https://github.com/connectwithprakash/session-bridge/commit/d851335aa2b7e0722464c2d0f237774efc1dbbdd))
* **review r6:** uuid-collision on re-conversion, clean CLI error on bad db ([74bc5d6](https://github.com/connectwithprakash/session-bridge/commit/74bc5d6b40df87a71d7989ef007a61dacbe74630))
* **review r7:** report Hermes intra-message block-order loss ([3812f7a](https://github.com/connectwithprakash/session-bridge/commit/3812f7ab277e29c7511c6492efb680b112595f44))
* **review r8:** Hermes ordering check covers RAW and TOOL_RESULT ([8ef5055](https://github.com/connectwithprakash/session-bridge/commit/8ef5055e93efdbb2ec3c5e3ff5d057a594e7fcaa))
* **review r9:** hermes_db preserves block order; TOOL-role stray text kept ([2bc720d](https://github.com/connectwithprakash/session-bridge/commit/2bc720d0ff2ac578557f5f7d47a2b68c9d334185))
* **tui:** focus the confirm button once the plan/dry-run enables it ([7992d43](https://github.com/connectwithprakash/session-bridge/commit/7992d43866434b028608891e7f81ce936ff56c90))
* **tui:** harden register slice per adversarial review ([f48774e](https://github.com/connectwithprakash/session-bridge/commit/f48774e1ad9c0a9c04d143c01142375386ff31fc))


### Documentation

* add step-by-step TUTORIAL.md with real worked example ([4e8b943](https://github.com/connectwithprakash/session-bridge/commit/4e8b9436d61be8ad0589ebd483e585768359c6ca))
* complete Codex resume tutorial ([2e0f9c6](https://github.com/connectwithprakash/session-bridge/commit/2e0f9c6f0afc13debdbeeae644d259652958c1df))
* contributor skills (releasing, harness recertification) and PR template ([7030808](https://github.com/connectwithprakash/session-bridge/commit/70308081974b8a7907813f5c28f82ca727e2583a))
* document that resume needs per-harness store registration ([b00e375](https://github.com/connectwithprakash/session-bridge/commit/b00e3753a3ac4cfbdffa5c6b5732464b8020ba90))
* embed TUI walkthrough GIF in the README ([627119c](https://github.com/connectwithprakash/session-bridge/commit/627119ce83ca431b47c03324499ef6ea6e3d171a))
* humanize README and TUTORIAL prose ([4252ac9](https://github.com/connectwithprakash/session-bridge/commit/4252ac911236ba2d25e99bfe964bd7f671438fc8))
* lead install instructions with uv ([2215fa9](https://github.com/connectwithprakash/session-bridge/commit/2215fa92a5cb4391bc02488596e6330e870b794b))
* redact real cwd/timezone from schema-reference example before publishing ([0d7d5a8](https://github.com/connectwithprakash/session-bridge/commit/0d7d5a8ca9264f9773c016cde6661c9b585b2f1f))
* **review r10:** correct hermes_db ordering comment to state real limitation ([77710e5](https://github.com/connectwithprakash/session-bridge/commit/77710e5b9df80233fdace27d969063024d9bed86))

## 0.1.0 (2026-07-28)


### Features

* Claude Code resume works from transcript; add --place-claude-cwd ([f1177c1](https://github.com/connectwithprakash/session-bridge/commit/f1177c1f55ee54f79d4c373db4da402ca07120f1))
* **cli:** --version flag; release metadata and compatibility matrix ([f968362](https://github.com/connectwithprakash/session-bridge/commit/f96836210853524bc460c3c6a7e521a4a5e93cdb))
* **codex:** register resumable imported sessions ([c20e194](https://github.com/connectwithprakash/session-bridge/commit/c20e194dbbaf5527057345b1373efa2c32b92294))
* cross-harness agent-session portability tool (v1) ([da521b1](https://github.com/connectwithprakash/session-bridge/commit/da521b135d129d9d18fae4b0864df6192bff26d6))
* Hermes resume works end-to-end; add 'register' command ([2213621](https://github.com/connectwithprakash/session-bridge/commit/221362161c747849f8b9e4d6f49e878971c52d75))
* Hermes state.db writer (lists session; context-resume still open) ([3a1bc03](https://github.com/connectwithprakash/session-bridge/commit/3a1bc03d597655fe17757f84ced8cf481f9257fb))
* **review r23:** --stub-open-calls for resumable transcripts; position-precise open_tool_calls ([f5c6941](https://github.com/connectwithprakash/session-bridge/commit/f5c694170ab11e623d19eeaa5136fe722c8e6b55))
* **skill:** package session-handoff skill; install-skill bootstrap ([8bc5a28](https://github.com/connectwithprakash/session-bridge/commit/8bc5a28b4f0ef6aedc92a0555c305b4ebd131350))
* **skill:** repo-shipped session-handoff skill for agents ([33cab89](https://github.com/connectwithprakash/session-bridge/commit/33cab8989140070a849068ca7e51d01b1d3c29cf))
* **tui:** Enter in a form field submits the options/register forms ([8e1f0f4](https://github.com/connectwithprakash/session-bridge/commit/8e1f0f45abd6cb15d35510c4a6602cedde6cfb0b))
* **tui:** interactive convert wizard behind optional textual extra ([0db5a1a](https://github.com/connectwithprakash/session-bridge/commit/0db5a1ad462cf5ac7ddb1df0d8a79119e81ad09d))
* **tui:** pure registration module for hermes and codex stores ([cb4c176](https://github.com/connectwithprakash/session-bridge/commit/cb4c176ad00cb67c6d9a1480950b5589fb319ca4))
* **tui:** register wizard screens with pre-mutation plan view ([37eaae9](https://github.com/connectwithprakash/session-bridge/commit/37eaae9499adaf1a48316aae1f1495fc9a0cccd3))


### Bug Fixes

* Codex reasoning content[] shape; validate reader on real tool session ([863aff2](https://github.com/connectwithprakash/session-bridge/commit/863aff27d9977c37e0f9058952b86fee5f25d4d4))
* **codex:** select target-native resume model ([fc86078](https://github.com/connectwithprakash/session-bridge/commit/fc8607850e566d6cca09d6346e1ab802394e31b3))
* resolve 5 correctness findings from adversarial review ([61b08db](https://github.com/connectwithprakash/session-bridge/commit/61b08db697937dedf95076b4787c9e4c989556c7))
* **review r11:** preserve empty-text reasoning blocks (Codex); report Hermes loss ([aa4a887](https://github.com/connectwithprakash/session-bridge/commit/aa4a8875103f733d8290e828301e0e9b6ef32433))
* **review r12:** preserve non-text parts inside tool_result.content ([fef04dc](https://github.com/connectwithprakash/session-bridge/commit/fef04dccb62fda67f5829be8e54493be949effff))
* **review r13:** handle queue-operation 'remove' (auto-withdrawn notifications) ([9a27c26](https://github.com/connectwithprakash/session-bridge/commit/9a27c26e279af88d83cfac4bb7eb3ebbfcde9a46))
* **review r14:** queue-op popAll; carry tool_result non-text parts ON the result ([02cca7d](https://github.com/connectwithprakash/session-bridge/commit/02cca7d0d4c610f2d72c2448a8c1e05fe7103336))
* **review r15:** remove queue-op is content-less; withdraw newest (LIFO) ([1acdcbf](https://github.com/connectwithprakash/session-bridge/commit/1acdcbfe5d1961c9b19cb150f42fd3bbecf262ec))
* **review r16:** Hermes reader recovers reasoning from codex_reasoning_items ([ff198f2](https://github.com/connectwithprakash/session-bridge/commit/ff198f24d2fc2a016c34f8d607338e92c76ae3ea))
* **review r17:** filter Claude Code &lt;synthetic&gt; model placeholder ([7b8f17b](https://github.com/connectwithprakash/session-bridge/commit/7b8f17bdbc5eb4fdc01317e05ea6c185df2fe850))
* **review r18b:** cross-harness writers emit placeholder for parts-only tool results ([ac57607](https://github.com/connectwithprakash/session-bridge/commit/ac5760792b61a2893257a43fdc4d18065f30d09e))
* **review r18:** skip isApiErrorMessage records; import Optional ([fd2226a](https://github.com/connectwithprakash/session-bridge/commit/fd2226a8dd7f66ec1a6a98ebdbdc43336223a84f))
* **review r19:** surface tool_result parts even when text is also present ([e9ab89e](https://github.com/connectwithprakash/session-bridge/commit/e9ab89e89496315200def1c8548e6bf8102cd973))
* **review r1:** robust JSONL loading, Codex SYSTEM role, Hermes DB parallel results, +5 more ([ec5fdde](https://github.com/connectwithprakash/session-bridge/commit/ec5fddec08a75d2097235fe6a435da832c6c8d39))
* **review r21:** open_tool_calls reports only tail-outstanding calls ([f7a7908](https://github.com/connectwithprakash/session-bridge/commit/f7a7908dc656e0aa54b7f28bda94163ecff03f64))
* **review r22:** fix open_tool_calls false-negative; surface losses on register ([546a76d](https://github.com/connectwithprakash/session-bridge/commit/546a76dc2833a7a4aaa8b6e252fb87270552f6ed))
* **review r24:** register --stub-open-calls for resumable DB rows ([393c5d3](https://github.com/connectwithprakash/session-bridge/commit/393c5d359383bf0a87291d6e79893ccfd42b72df))
* **review r25:** WAL-safe register backup via SQLite backup API ([29dea39](https://github.com/connectwithprakash/session-bridge/commit/29dea3917ccd2780dc0426b9633acd639802fe24))
* **review r27:** CLI/placement robustness — no silent overwrite, clean errors ([2a21c5c](https://github.com/connectwithprakash/session-bridge/commit/2a21c5cecb2b20f039fb16616dd993e7d3cd413a))
* **review r28:** report tool-schema loss on register; bound cwd length ([6df5797](https://github.com/connectwithprakash/session-bridge/commit/6df5797ed681a05e63c8d1cd2ef29e487b0aff1d))
* **review r2:** path-traversal, RAW passthrough, handshake accumulation, +6 more ([ec24bbf](https://github.com/connectwithprakash/session-bridge/commit/ec24bbf7d97977d50e05256540d43070d5d0d5b7))
* **review r3:** unforgeable handshake marker, Hermes SYSTEM + RAW readers, +5 more ([92788db](https://github.com/connectwithprakash/session-bridge/commit/92788db921b20e4481ab966e9cd9254a03090f36))
* **review r4:** multi-hop is_error recovery, Codex turn-count, +3 more ([ebaa036](https://github.com/connectwithprakash/session-bridge/commit/ebaa0363cb123d78847cba018b2e381b88db84a0))
* **review r5:** Codex block ordering, source-gated RAW loss, Codex model switch, unforgeable error marker ([d851335](https://github.com/connectwithprakash/session-bridge/commit/d851335aa2b7e0722464c2d0f237774efc1dbbdd))
* **review r6:** uuid-collision on re-conversion, clean CLI error on bad db ([74bc5d6](https://github.com/connectwithprakash/session-bridge/commit/74bc5d6b40df87a71d7989ef007a61dacbe74630))
* **review r7:** report Hermes intra-message block-order loss ([3812f7a](https://github.com/connectwithprakash/session-bridge/commit/3812f7ab277e29c7511c6492efb680b112595f44))
* **review r8:** Hermes ordering check covers RAW and TOOL_RESULT ([8ef5055](https://github.com/connectwithprakash/session-bridge/commit/8ef5055e93efdbb2ec3c5e3ff5d057a594e7fcaa))
* **review r9:** hermes_db preserves block order; TOOL-role stray text kept ([2bc720d](https://github.com/connectwithprakash/session-bridge/commit/2bc720d0ff2ac578557f5f7d47a2b68c9d334185))
* **tui:** focus the confirm button once the plan/dry-run enables it ([7992d43](https://github.com/connectwithprakash/session-bridge/commit/7992d43866434b028608891e7f81ce936ff56c90))
* **tui:** harden register slice per adversarial review ([f48774e](https://github.com/connectwithprakash/session-bridge/commit/f48774e1ad9c0a9c04d143c01142375386ff31fc))


### Documentation

* add step-by-step TUTORIAL.md with real worked example ([4e8b943](https://github.com/connectwithprakash/session-bridge/commit/4e8b9436d61be8ad0589ebd483e585768359c6ca))
* complete Codex resume tutorial ([2e0f9c6](https://github.com/connectwithprakash/session-bridge/commit/2e0f9c6f0afc13debdbeeae644d259652958c1df))
* contributor skills (releasing, harness recertification) and PR template ([7030808](https://github.com/connectwithprakash/session-bridge/commit/70308081974b8a7907813f5c28f82ca727e2583a))
* document that resume needs per-harness store registration ([b00e375](https://github.com/connectwithprakash/session-bridge/commit/b00e3753a3ac4cfbdffa5c6b5732464b8020ba90))
* embed TUI walkthrough GIF in the README ([627119c](https://github.com/connectwithprakash/session-bridge/commit/627119ce83ca431b47c03324499ef6ea6e3d171a))
* humanize README and TUTORIAL prose ([4252ac9](https://github.com/connectwithprakash/session-bridge/commit/4252ac911236ba2d25e99bfe964bd7f671438fc8))
* redact real cwd/timezone from schema-reference example before publishing ([0d7d5a8](https://github.com/connectwithprakash/session-bridge/commit/0d7d5a8ca9264f9773c016cde6661c9b585b2f1f))
* **review r10:** correct hermes_db ordering comment to state real limitation ([77710e5](https://github.com/connectwithprakash/session-bridge/commit/77710e5b9df80233fdace27d969063024d9bed86))
