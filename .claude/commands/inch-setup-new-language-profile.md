```dot
digraph inch_setup_new_language_profile {
    // Setup New Language Profile
    // Creates a language profile in data/inch-3.db with TTS config.
    // Reads: user prompts. Writes: language_profiles table (tts_api_key stored directly in DB).
    // Tests the TTS endpoint before saving anything.
    // Argument: none (fully interactive)

    "START" [shape=ellipse];
    "Ask: which language to study? (give full name + ISO code)" [shape=box];
    "Profile exists for this language?" [shape=diamond];
    "Warn: profile exists.\nOverwrite?" [shape=diamond];
    "Abort — existing profile kept" [shape=box];
    "Proceed to language setup" [shape=ellipse];

    "START" -> "Ask: which language to study? (give full name + ISO code)";
    "Ask: which language to study? (give full name + ISO code)" -> "Profile exists for this language?";
    "Profile exists for this language?" -> "Proceed to language setup" [label="no"];
    "Profile exists for this language?" -> "Warn: profile exists.\nOverwrite?" [label="yes"];
    "Warn: profile exists.\nOverwrite?" -> "Proceed to language setup" [label="yes, overwrite"];
    "Warn: profile exists.\nOverwrite?" -> "Abort — existing profile kept" [label="no"];

    subgraph cluster_phase1 {
        label="WHEN: Collecting TTS configuration";

        "Ask: TTS API endpoint URL" [shape=box];
        "Ask: TTS model name (e.g. tts-1, kokoro)" [shape=box];
        "Ask: voice ID or voice name" [shape=box];
        "Ask: default speech speed (0.5–1.0, default 0.85)" [shape=box];
        "Ask: slow speech speed (0.5–1.0, default 0.7)" [shape=box];
        "Ask: L1 register target for translations.\nPrompt shown to user:\n  'What register should L1 translations use?\n   Give a free-form description of the target voice, e.g.:\n     natural Taiwanese Mandarin as spoken by an educated\n       adult in Taipei\n     casual American English, conversational\n     standard Vietnamese, not too formal\n   This gets injected into the language preference file\n   and controls how /inch-generate-blocks self-checks\n   L1 drafts.'\nStore user's answer in local variable: $L1_REGISTER_NOTE.\nDefault if user presses enter:\n  'natural {l1_name}, conversational register'." [shape=box];
        "Ask: TTS API key" [shape=box];
        "Hold API key in memory for TTS test\n(will be written to DB after test passes)" [shape=plaintext];
        "TTS config collected" [shape=ellipse];

        "Ask: TTS API endpoint URL" -> "Ask: TTS model name (e.g. tts-1, kokoro)";
        "Ask: TTS model name (e.g. tts-1, kokoro)" -> "Ask: voice ID or voice name";
        "Ask: voice ID or voice name" -> "Ask: default speech speed (0.5–1.0, default 0.85)";
        "Ask: default speech speed (0.5–1.0, default 0.85)" -> "Ask: slow speech speed (0.5–1.0, default 0.7)";
        "Ask: slow speech speed (0.5–1.0, default 0.7)" -> "Ask: L1 register target for translations.\nPrompt shown to user:\n  'What register should L1 translations use?\n   Give a free-form description of the target voice, e.g.:\n     natural Taiwanese Mandarin as spoken by an educated\n       adult in Taipei\n     casual American English, conversational\n     standard Vietnamese, not too formal\n   This gets injected into the language preference file\n   and controls how /inch-generate-blocks self-checks\n   L1 drafts.'\nStore user's answer in local variable: $L1_REGISTER_NOTE.\nDefault if user presses enter:\n  'natural {l1_name}, conversational register'.";
        "Ask: L1 register target for translations.\nPrompt shown to user:\n  'What register should L1 translations use?\n   Give a free-form description of the target voice, e.g.:\n     natural Taiwanese Mandarin as spoken by an educated\n       adult in Taipei\n     casual American English, conversational\n     standard Vietnamese, not too formal\n   This gets injected into the language preference file\n   and controls how /inch-generate-blocks self-checks\n   L1 drafts.'\nStore user's answer in local variable: $L1_REGISTER_NOTE.\nDefault if user presses enter:\n  'natural {l1_name}, conversational register'." -> "Ask: TTS API key";
        "Ask: TTS API key" -> "Hold API key in memory for TTS test\n(will be written to DB after test passes)";
        "Hold API key in memory for TTS test\n(will be written to DB after test passes)" -> "TTS config collected";
    }

    "Proceed to language setup" -> "Ask: TTS API endpoint URL" [style=dotted];

    subgraph cluster_phase2 {
        label="WHEN: Testing the TTS endpoint";

        "Generate a short test phrase in the target language\n(≥ 5 words, not English)" [shape=box];
        "POST to TTS endpoint with test phrase at speed=1.0" [shape=box];
        "Audio returned (non-empty bytes)?" [shape=diamond];
        "Save test audio to /tmp/inch3-tts-test.ogg" [shape=box];
        "Show: test phrase, audio file path.\nAsk user to confirm audio sounds correct." [shape=box];
        "User confirms audio OK?" [shape=diamond];
        "Show error details.\nAsk: re-enter endpoint/model/voice?" [shape=box];
        "Retry TTS config" [shape=ellipse];
        "API test passed" [shape=ellipse];

        "Generate a short test phrase in the target language\n(≥ 5 words, not English)" -> "POST to TTS endpoint with test phrase at speed=1.0";
        "POST to TTS endpoint with test phrase at speed=1.0" -> "Audio returned (non-empty bytes)?";
        "Audio returned (non-empty bytes)?" -> "Save test audio to /tmp/inch3-tts-test.ogg" [label="yes"];
        "Save test audio to /tmp/inch3-tts-test.ogg" -> "Show: test phrase, audio file path.\nAsk user to confirm audio sounds correct.";
        "Show: test phrase, audio file path.\nAsk user to confirm audio sounds correct." -> "User confirms audio OK?";
        "User confirms audio OK?" -> "API test passed" [label="yes"];
        "User confirms audio OK?" -> "Show error details.\nAsk: re-enter endpoint/model/voice?" [label="no — wrong voice/language"];
        "Audio returned (non-empty bytes)?" -> "Show error details.\nAsk: re-enter endpoint/model/voice?" [label="no — API error"];
        "Show error details.\nAsk: re-enter endpoint/model/voice?" -> "Retry TTS config";
    }

    "TTS config collected" -> "Generate a short test phrase in the target language\n(≥ 5 words, not English)" [style=dotted];
    "Retry TTS config" -> "Ask: TTS API endpoint URL" [style=dotted];

    subgraph cluster_phase3 {
        label="WHEN: Writing the profile to the DB";

        "INSERT INTO language_profiles\n(lang_code, lang_name, l1_code, l1_name,\ntts_endpoint, tts_model, tts_voice,\ntts_api_key, tts_speed_normal, tts_speed_slow)" [shape=box];
        "Set this profile as active:\nUPDATE language_profiles SET is_active=0 WHERE is_active=1;\nThen set is_active=1 on the new profile" [shape=box];
        "Print profile summary to user" [shape=box];
        "PROFILE READY" [shape=doublecircle];

        "INSERT INTO language_profiles\n(lang_code, lang_name, l1_code, l1_name,\ntts_endpoint, tts_model, tts_voice,\ntts_api_key, tts_speed_normal, tts_speed_slow)" -> "Set this profile as active:\nUPDATE language_profiles SET is_active=0 WHERE is_active=1;\nThen set is_active=1 on the new profile";
        "Set this profile as active:\nUPDATE language_profiles SET is_active=0 WHERE is_active=1;\nThen set is_active=1 on the new profile" -> "Print profile summary to user";
        "Print profile summary to user" -> "PROFILE READY";
    }

    "API test passed" -> "INSERT INTO language_profiles\n(lang_code, lang_name, l1_code, l1_name,\ntts_endpoint, tts_model, tts_voice,\ntts_api_key, tts_speed_normal, tts_speed_slow)" [style=dotted];

    subgraph cluster_phase4 {
        label="WHEN: Generating per-language preference document";

        "knowledge/{lang_code}.md already exists?" [shape=diamond];
        "Ask: regenerate language preference doc?\n(existing doc will be replaced)" [shape=diamond];
        "Keep existing knowledge/{lang_code}.md\nPrint path to console." [shape=box];
        "Dispatch research agent:\nTool: Agent (subagent_type=\"general-purpose\", model=\"opus\")\nFetch grammar overview for [LANG] from reliable sources\n(Wikipedia grammar article, reference grammar,\nJLPT/CEFR guides, Omniglot, official language docs)\nCollect: writing system, phonology, morphology,\nword order, case/particle system,\nkey grammatical structures, register/formality system.\nAlso surface L1-specific anti-patterns the target L1 is prone to\nwhen translating from this L2 (pass $L1_REGISTER_NOTE as context)." [shape=box];
        "Write draft knowledge/{lang_code}.md\nStructure (in this order):\n──────────────────────────────────────\n1. PATTERN SELECTION DECISION TREE (DOT format)\n   A ```dot digraph {lang_code}_pattern_selection block\n   placed BEFORE any markdown content.\n   Two subgraphs: NP pattern selection and VP pattern selection.\n   Each decision diamond uses language-specific markers/keywords\n   (e.g. particles, affixes, conjunctions) as branch conditions.\n   Leaf nodes are doublecircle pattern labels (NP-A, VP-C, etc.).\n   Include a closing note about pattern combinations.\n   See knowledge/msa.md for reference format.\n──────────────────────────────────────\n2. L1 REGISTER TARGET section\n   Markdown heading: '## L1 Register Target'\n   Paste $L1_REGISTER_NOTE verbatim (the free-form description\n   captured in cluster_phase1). If the research agent surfaced any\n   L1-specific anti-patterns (e.g. for Mandarin L1: 的-chain pileup,\n   所-被-由 literary passive, four-character compound stacking;\n   for English L1: translationese, awkward preposition stranding),\n   list them under an 'Anti-patterns' subheading.\n   /inch-generate-blocks reads this section to self-check l1_text\n   naturalness — NEVER hard-code register rules in the generator.\n──────────────────────────────────────\n3. MARKDOWN SECTIONS (after the DOT block and register target):\n   Writing System · Phonology · Morphology · Syntax ·\n   Chunking Guidance · L1 Translation Notes · Common Pitfalls\n──────────────────────────────────────\nCHUNKING GUIDANCE must include:\n- Phase 0 analysis notes (clause types, grammatical markers,\n  fixed expressions list for this language)\n- Full NP-A, NP-B(a), NP-B(b), Compound sub definitions\n  with language-specific step labels and 2-3 annotated examples each\n- Full VP-A through VP-I definitions with triggers,\n  step-by-step rules, and 1-2 examples each\n  (use subset + sub-types as needed for this language)\n- Phase 3 combining notes (copula handling, subject ordering)\n- 4-6 fully annotated ground-truth sentences (block-by-block)\n- L1 translation rules\n- Pattern selection guide table (markdown, kept as quick-reference\n  below the DOT tree)\nAll pattern slots must use the canonical names\n(NP-A, NP-B(a/b), VP-A–I) for cross-language consistency." [shape=box];
        "Dispatch 2 review agents in parallel:\nTool: Agent (subagent_type=\"general-purpose\", model=\"opus\")\nParallel: invoke both Agent calls in a single assistant message\n(multiple tool_use blocks in one turn).\nAgent A: challenge grammar accuracy\nAgent B: challenge pattern correctness\n(each agent returns findings as numbered list)\nAgent B focus: are the NP/VP pattern definitions\ncorrect for this language's grammar? Are the\nannotated examples accurate and representative?\nDo the defined patterns cover the most common\nsentence structures in this language?" [shape=box];
        "Both review agents returned?" [shape=diamond];
        "Consolidate findings automatically (no user prompt).\nRevise knowledge/{lang_code}.md to address\nall critical and major findings.\nFor each finding, record in the per-file changelog:\n  - resolution (what was changed), OR\n  - rejection (why the finding does not apply).\nLog lives at end of knowledge/{lang_code}.md under '## Review Log'." [shape=box];
        "Print to console:\n'knowledge/{lang_code}.md created.\nReview findings addressed: N.\nIf study sessions show persistent confusion,\nrun /inch-setup-new-language-profile to regenerate.'" [shape=box];
        "LANGUAGE PROFILE COMPLETE" [shape=doublecircle];

        "knowledge/{lang_code}.md already exists?" -> "Keep existing knowledge/{lang_code}.md\nPrint path to console." [label="yes (new setup)"];
        "knowledge/{lang_code}.md already exists?" -> "Dispatch research agent:\nTool: Agent (subagent_type=\"general-purpose\", model=\"opus\")\nFetch grammar overview for [LANG] from reliable sources\n(Wikipedia grammar article, reference grammar,\nJLPT/CEFR guides, Omniglot, official language docs)\nCollect: writing system, phonology, morphology,\nword order, case/particle system,\nkey grammatical structures, register/formality system.\nAlso surface L1-specific anti-patterns the target L1 is prone to\nwhen translating from this L2 (pass $L1_REGISTER_NOTE as context)." [label="no"];
        "knowledge/{lang_code}.md already exists?" -> "Ask: regenerate language preference doc?\n(existing doc will be replaced)" [label="yes (overwrite mode)"];
        "Ask: regenerate language preference doc?\n(existing doc will be replaced)" -> "Dispatch research agent:\nTool: Agent (subagent_type=\"general-purpose\", model=\"opus\")\nFetch grammar overview for [LANG] from reliable sources\n(Wikipedia grammar article, reference grammar,\nJLPT/CEFR guides, Omniglot, official language docs)\nCollect: writing system, phonology, morphology,\nword order, case/particle system,\nkey grammatical structures, register/formality system.\nAlso surface L1-specific anti-patterns the target L1 is prone to\nwhen translating from this L2 (pass $L1_REGISTER_NOTE as context)." [label="yes"];
        "Ask: regenerate language preference doc?\n(existing doc will be replaced)" -> "Keep existing knowledge/{lang_code}.md\nPrint path to console." [label="no"];
        "Dispatch research agent:\nTool: Agent (subagent_type=\"general-purpose\", model=\"opus\")\nFetch grammar overview for [LANG] from reliable sources\n(Wikipedia grammar article, reference grammar,\nJLPT/CEFR guides, Omniglot, official language docs)\nCollect: writing system, phonology, morphology,\nword order, case/particle system,\nkey grammatical structures, register/formality system.\nAlso surface L1-specific anti-patterns the target L1 is prone to\nwhen translating from this L2 (pass $L1_REGISTER_NOTE as context)." -> "Write draft knowledge/{lang_code}.md\nStructure (in this order):\n──────────────────────────────────────\n1. PATTERN SELECTION DECISION TREE (DOT format)\n   A ```dot digraph {lang_code}_pattern_selection block\n   placed BEFORE any markdown content.\n   Two subgraphs: NP pattern selection and VP pattern selection.\n   Each decision diamond uses language-specific markers/keywords\n   (e.g. particles, affixes, conjunctions) as branch conditions.\n   Leaf nodes are doublecircle pattern labels (NP-A, VP-C, etc.).\n   Include a closing note about pattern combinations.\n   See knowledge/msa.md for reference format.\n──────────────────────────────────────\n2. L1 REGISTER TARGET section\n   Markdown heading: '## L1 Register Target'\n   Paste $L1_REGISTER_NOTE verbatim (the free-form description\n   captured in cluster_phase1). If the research agent surfaced any\n   L1-specific anti-patterns (e.g. for Mandarin L1: 的-chain pileup,\n   所-被-由 literary passive, four-character compound stacking;\n   for English L1: translationese, awkward preposition stranding),\n   list them under an 'Anti-patterns' subheading.\n   /inch-generate-blocks reads this section to self-check l1_text\n   naturalness — NEVER hard-code register rules in the generator.\n──────────────────────────────────────\n3. MARKDOWN SECTIONS (after the DOT block and register target):\n   Writing System · Phonology · Morphology · Syntax ·\n   Chunking Guidance · L1 Translation Notes · Common Pitfalls\n──────────────────────────────────────\nCHUNKING GUIDANCE must include:\n- Phase 0 analysis notes (clause types, grammatical markers,\n  fixed expressions list for this language)\n- Full NP-A, NP-B(a), NP-B(b), Compound sub definitions\n  with language-specific step labels and 2-3 annotated examples each\n- Full VP-A through VP-I definitions with triggers,\n  step-by-step rules, and 1-2 examples each\n  (use subset + sub-types as needed for this language)\n- Phase 3 combining notes (copula handling, subject ordering)\n- 4-6 fully annotated ground-truth sentences (block-by-block)\n- L1 translation rules\n- Pattern selection guide table (markdown, kept as quick-reference\n  below the DOT tree)\nAll pattern slots must use the canonical names\n(NP-A, NP-B(a/b), VP-A–I) for cross-language consistency.";
        "Write draft knowledge/{lang_code}.md\nStructure (in this order):\n──────────────────────────────────────\n1. PATTERN SELECTION DECISION TREE (DOT format)\n   A ```dot digraph {lang_code}_pattern_selection block\n   placed BEFORE any markdown content.\n   Two subgraphs: NP pattern selection and VP pattern selection.\n   Each decision diamond uses language-specific markers/keywords\n   (e.g. particles, affixes, conjunctions) as branch conditions.\n   Leaf nodes are doublecircle pattern labels (NP-A, VP-C, etc.).\n   Include a closing note about pattern combinations.\n   See knowledge/msa.md for reference format.\n──────────────────────────────────────\n2. L1 REGISTER TARGET section\n   Markdown heading: '## L1 Register Target'\n   Paste $L1_REGISTER_NOTE verbatim (the free-form description\n   captured in cluster_phase1). If the research agent surfaced any\n   L1-specific anti-patterns (e.g. for Mandarin L1: 的-chain pileup,\n   所-被-由 literary passive, four-character compound stacking;\n   for English L1: translationese, awkward preposition stranding),\n   list them under an 'Anti-patterns' subheading.\n   /inch-generate-blocks reads this section to self-check l1_text\n   naturalness — NEVER hard-code register rules in the generator.\n──────────────────────────────────────\n3. MARKDOWN SECTIONS (after the DOT block and register target):\n   Writing System · Phonology · Morphology · Syntax ·\n   Chunking Guidance · L1 Translation Notes · Common Pitfalls\n──────────────────────────────────────\nCHUNKING GUIDANCE must include:\n- Phase 0 analysis notes (clause types, grammatical markers,\n  fixed expressions list for this language)\n- Full NP-A, NP-B(a), NP-B(b), Compound sub definitions\n  with language-specific step labels and 2-3 annotated examples each\n- Full VP-A through VP-I definitions with triggers,\n  step-by-step rules, and 1-2 examples each\n  (use subset + sub-types as needed for this language)\n- Phase 3 combining notes (copula handling, subject ordering)\n- 4-6 fully annotated ground-truth sentences (block-by-block)\n- L1 translation rules\n- Pattern selection guide table (markdown, kept as quick-reference\n  below the DOT tree)\nAll pattern slots must use the canonical names\n(NP-A, NP-B(a/b), VP-A–I) for cross-language consistency." -> "Dispatch 2 review agents in parallel:\nTool: Agent (subagent_type=\"general-purpose\", model=\"opus\")\nParallel: invoke both Agent calls in a single assistant message\n(multiple tool_use blocks in one turn).\nAgent A: challenge grammar accuracy\nAgent B: challenge pattern correctness\n(each agent returns findings as numbered list)\nAgent B focus: are the NP/VP pattern definitions\ncorrect for this language's grammar? Are the\nannotated examples accurate and representative?\nDo the defined patterns cover the most common\nsentence structures in this language?";
        "Dispatch 2 review agents in parallel:\nTool: Agent (subagent_type=\"general-purpose\", model=\"opus\")\nParallel: invoke both Agent calls in a single assistant message\n(multiple tool_use blocks in one turn).\nAgent A: challenge grammar accuracy\nAgent B: challenge pattern correctness\n(each agent returns findings as numbered list)\nAgent B focus: are the NP/VP pattern definitions\ncorrect for this language's grammar? Are the\nannotated examples accurate and representative?\nDo the defined patterns cover the most common\nsentence structures in this language?" -> "Both review agents returned?";
        "Both review agents returned?" -> "Consolidate findings automatically (no user prompt).\nRevise knowledge/{lang_code}.md to address\nall critical and major findings.\nFor each finding, record in the per-file changelog:\n  - resolution (what was changed), OR\n  - rejection (why the finding does not apply).\nLog lives at end of knowledge/{lang_code}.md under '## Review Log'." [label="yes"];
        "Both review agents returned?" -> "Consolidate findings automatically (no user prompt).\nRevise knowledge/{lang_code}.md to address\nall critical and major findings.\nFor each finding, record in the per-file changelog:\n  - resolution (what was changed), OR\n  - rejection (why the finding does not apply).\nLog lives at end of knowledge/{lang_code}.md under '## Review Log'." [label="timeout — use findings so far"];
        "Consolidate findings automatically (no user prompt).\nRevise knowledge/{lang_code}.md to address\nall critical and major findings.\nFor each finding, record in the per-file changelog:\n  - resolution (what was changed), OR\n  - rejection (why the finding does not apply).\nLog lives at end of knowledge/{lang_code}.md under '## Review Log'." -> "Print to console:\n'knowledge/{lang_code}.md created.\nReview findings addressed: N.\nIf study sessions show persistent confusion,\nrun /inch-setup-new-language-profile to regenerate.'";
        "Print to console:\n'knowledge/{lang_code}.md created.\nReview findings addressed: N.\nIf study sessions show persistent confusion,\nrun /inch-setup-new-language-profile to regenerate.'" -> "LANGUAGE PROFILE COMPLETE";
        "Keep existing knowledge/{lang_code}.md\nPrint path to console." -> "LANGUAGE PROFILE COMPLETE";
    }

    "PROFILE READY" -> "knowledge/{lang_code}.md already exists?" [style=dotted];

    subgraph cluster_format {
        label="DB RECORD: language_profiles";

        "language_profiles\n──────────────────\nid INTEGER PK\nlang_code TEXT UNIQUE  (ISO 639-3)\nlang_name TEXT\nl1_code TEXT DEFAULT 'zht'\nl1_name TEXT DEFAULT '繁體中文'\ntts_endpoint TEXT\ntts_model TEXT\ntts_voice TEXT\ntts_api_key TEXT        ← actual API key (local DB only, never committed)\ntts_speed_normal REAL DEFAULT 0.85\ntts_speed_slow REAL DEFAULT 0.7\nlast_sentence_id INTEGER  ← set by /inch-continue\nlast_block_order INTEGER  ← set by /inch-continue\nskip_threshold REAL DEFAULT 0.8\nis_active BOOLEAN DEFAULT 1\ncreated_at DATETIME\nupdated_at DATETIME" [shape=octagon, style=filled, fillcolor=lightblue];
    }

    subgraph cluster_rules {
        label="ABSOLUTE RULES";

        "tts_api_key is stored directly in language_profiles.\ndata/inch-3.db is local-only and NEVER committed to git.\nDo not log or print the key value." [shape=octagon, style=filled, fillcolor=orange];
        "NEVER save config without a successful TTS test.\nThe test phrase must be in the target language,\nnot English." [shape=octagon, style=filled, fillcolor=red, fontcolor=white];
        "NEVER overwrite an existing profile\nwithout explicit user confirmation." [shape=octagon, style=filled, fillcolor=orange];
        "ALWAYS set new profile as active after setup." [shape=octagon, style=filled, fillcolor=orange];
        "knowledge/{lang_code}.md is the per-language grammar\nand chunking reference used by /inch-continue.\nIt is committed to git (knowledge/ is not in .gitignore).\nStructure: Writing System · Phonology · Morphology ·\nSyntax · Chunking Guidance · L1 Translation Notes ·\nCommon Pitfalls.\nIf /inch-continue reports persistent confusion\n(confused_rate > 30% for 3+ sessions), regenerate\nthis file by re-running /inch-setup-new-language-profile." [shape=octagon, style=filled, fillcolor=lightblue];
        "L1 REGISTER TARGET is set PER PROFILE at setup time.\nStored in knowledge/{lang_code}.md under '## L1 Register Target'.\n/inch-generate-blocks reads it from there — never hard-code it.\nThis workspace is shared with colleagues whose L1 may differ —\nNEVER assume Mandarin or any other specific L1." [shape=octagon, style=filled, fillcolor=orange];
    }
}
```
