```dot
digraph chunking_strategy {
    // Sentence Chunking Strategy for Inch 3 — LANGUAGE-AGNOSTIC META-DOCUMENT
    // Reference for /inch-generate-blocks block generation.
    //
    // This file defines the FRAMEWORK and universal rules only.
    // For language-specific pattern definitions (NP-A, NP-B, VP-A–I, annotated examples):
    //   consult knowledge/{lang_code}.md (e.g. knowledge/jpn.md for Japanese).
    // Read BOTH files before generating blocks for any new sentence.
    //
    // PATTERN SLOT TAXONOMY (load-bearing — used as block role= tags in the DB):
    //   NP patterns:  NP-A · NP-B(a) · NP-B(b) · NP-Compound
    //   VP patterns:  VP-A · VP-B · VP-C · VP-D · VP-E · VP-F · VP-G · VP-H · VP-I
    // Each slot is DEFINED in knowledge/{lang_code}.md with language-specific rules
    // and annotated examples. Some languages may use a subset of VP slots or add sub-types.
    //
    // NP+VP FRAMEWORK APPLICABILITY:
    //   SVO/SOV languages: NP before VP in block delivery (most languages)
    //   VSO languages (Arabic, Hebrew): VP-initial — {lang_code}.md specifies delivery order
    //   Agglutinative languages: fewer slots may apply; {lang_code}.md specifies
    //   The Phase 0 draft and all ABSOLUTE RULES apply to every language.

    // ================================================================
    // PHASE 0: SENTENCE ANALYSIS — always do this first
    // ================================================================

    subgraph cluster_phase0 {
        label="PHASE 0: Analyse the sentence before writing any blocks";

        "Read the full sentence" [shape=box];

        "Identify main clause structure:\nA) [NP subject] + [VP predicate]\nB) [NP subject with relative/modifier clause] + [VP predicate]\nC) [NP] + copula\nD) Grammatical fragment (no predicate)\n(See {lang_code}.md for language-specific clause types and markers)" [shape=box];

        "Identify the subject NP:\n- find head noun + grammatical marker\n- note ALL modifiers (adjectives, adverbs, relative clauses)\n- note compound forms used as modifiers\n(See {lang_code}.md for the marker system)" [shape=box];

        "Identify the predicate VP:\n- main verb, copula, or none (fragment)\n- complements, adverbs, fixed expressions\n- embedded clauses (modal/quote/conditional)\n(See {lang_code}.md for VP categories)" [shape=box];

        "List fixed expressions and grammatical patterns.\nThese become ATOMIC blocks — never split.\n(See {lang_code}.md for the language-specific fixed patterns list)" [shape=box];

        "Write a 4-step draft (DO NOT skip):\n  Step 1: label each constituent grammatically\n    (subject NP / relative clause / adverb / object / main verb / modal)\n  Step 2: assign NP pattern (A, B-a, B-b) and VP pattern(s) (A–I)\n    by matching against the patterns defined in {lang_code}.md\n  Step 3: list planned blocks as:\n    [N] tts='...'  role='NP-A step 2 / VP-C step 1 / ...'\n  Step 4: verify all ABSOLUTE RULES before writing blocks" [shape=box];

        "Analysis complete" [shape=ellipse];

        "Read the full sentence" -> "Identify main clause structure:\nA) [NP subject] + [VP predicate]\nB) [NP subject with relative/modifier clause] + [VP predicate]\nC) [NP] + copula\nD) Grammatical fragment (no predicate)\n(See {lang_code}.md for language-specific clause types and markers)";
        "Identify main clause structure:\nA) [NP subject] + [VP predicate]\nB) [NP subject with relative/modifier clause] + [VP predicate]\nC) [NP] + copula\nD) Grammatical fragment (no predicate)\n(See {lang_code}.md for language-specific clause types and markers)" -> "Identify the subject NP:\n- find head noun + grammatical marker\n- note ALL modifiers (adjectives, adverbs, relative clauses)\n- note compound forms used as modifiers\n(See {lang_code}.md for the marker system)";
        "Identify the subject NP:\n- find head noun + grammatical marker\n- note ALL modifiers (adjectives, adverbs, relative clauses)\n- note compound forms used as modifiers\n(See {lang_code}.md for the marker system)" -> "Identify the predicate VP:\n- main verb, copula, or none (fragment)\n- complements, adverbs, fixed expressions\n- embedded clauses (modal/quote/conditional)\n(See {lang_code}.md for VP categories)";
        "Identify the predicate VP:\n- main verb, copula, or none (fragment)\n- complements, adverbs, fixed expressions\n- embedded clauses (modal/quote/conditional)\n(See {lang_code}.md for VP categories)" -> "List fixed expressions and grammatical patterns.\nThese become ATOMIC blocks — never split.\n(See {lang_code}.md for the language-specific fixed patterns list)";
        "List fixed expressions and grammatical patterns.\nThese become ATOMIC blocks — never split.\n(See {lang_code}.md for the language-specific fixed patterns list)" -> "Write a 4-step draft (DO NOT skip):\n  Step 1: label each constituent grammatically\n    (subject NP / relative clause / adverb / object / main verb / modal)\n  Step 2: assign NP pattern (A, B-a, B-b) and VP pattern(s) (A–I)\n    by matching against the patterns defined in {lang_code}.md\n  Step 3: list planned blocks as:\n    [N] tts='...'  role='NP-A step 2 / VP-C step 1 / ...'\n  Step 4: verify all ABSOLUTE RULES before writing blocks";
        "Write a 4-step draft (DO NOT skip):\n  Step 1: label each constituent grammatically\n    (subject NP / relative clause / adverb / object / main verb / modal)\n  Step 2: assign NP pattern (A, B-a, B-b) and VP pattern(s) (A–I)\n    by matching against the patterns defined in {lang_code}.md\n  Step 3: list planned blocks as:\n    [N] tts='...'  role='NP-A step 2 / VP-C step 1 / ...'\n  Step 4: verify all ABSOLUTE RULES before writing blocks" -> "Analysis complete";
    }

    // ================================================================
    // PHASE 1: SUBJECT NP CHUNKING
    // (pattern slots — language-specific definitions in {lang_code}.md)
    // ================================================================

    subgraph cluster_np {
        label="PHASE 1: Chunking the Subject NP\n(three pattern slots — language-specific rules in {lang_code}.md)";

        subgraph cluster_np_a {
            label="NP-A: Simple NP (modifier chain without relative clause)\nSee {lang_code}.md: NP-A section for language-specific steps and examples";

            "NP-A step 1: Introduce HEAD NOUN + grammatical marker." [shape=box];
            "NP-A step 2: Expand by adding ONE modifier at a time\n(adjective / adverb / possession marker),\nexpanding outward in surface order.\n(See {lang_code}.md for modifier direction.)" [shape=box];
            "NP-A step 3: If any modifier is a compound form (V1+V2 or similar),\napply the Compound Modifier sub-pattern FIRST.\n(See {lang_code}.md for compound types.)" [shape=box];
            "NP-A done" [shape=ellipse];

            "NP-A step 1: Introduce HEAD NOUN + grammatical marker." -> "NP-A step 2: Expand by adding ONE modifier at a time\n(adjective / adverb / possession marker),\nexpanding outward in surface order.\n(See {lang_code}.md for modifier direction.)";
            "NP-A step 2: Expand by adding ONE modifier at a time\n(adjective / adverb / possession marker),\nexpanding outward in surface order.\n(See {lang_code}.md for modifier direction.)" -> "NP-A step 3: If any modifier is a compound form (V1+V2 or similar),\napply the Compound Modifier sub-pattern FIRST.\n(See {lang_code}.md for compound types.)";
            "NP-A step 3: If any modifier is a compound form (V1+V2 or similar),\napply the Compound Modifier sub-pattern FIRST.\n(See {lang_code}.md for compound types.)" -> "NP-A done";
        }

        subgraph cluster_np_b {
            label="NP-B: NP with relative or modifier clause\n(a verb phrase or equivalent modifies the head noun)\nSee {lang_code}.md: NP-B(a) and NP-B(b) sections";

            "Is the head noun a SIMPLE noun or short compound?" [shape=diamond];

            subgraph cluster_np_ba {
                label="NP-B(a): Simple head noun\nSee {lang_code}.md: NP-B(a) section for steps and examples";

                "NP-B(a) step 1: Introduce the head noun first,\nwith any close modifiers." [shape=box];
                "NP-B(a) step 2: Build the modifier clause SEPARATELY\nfrom its own head outward." [shape=box];
                "NP-B(a) step 3: Attach the fully-built modifier clause to the NP." [shape=box];
                "NP-B(a) done" [shape=ellipse];

                "NP-B(a) step 1: Introduce the head noun first,\nwith any close modifiers." -> "NP-B(a) step 2: Build the modifier clause SEPARATELY\nfrom its own head outward.";
                "NP-B(a) step 2: Build the modifier clause SEPARATELY\nfrom its own head outward." -> "NP-B(a) step 3: Attach the fully-built modifier clause to the NP.";
                "NP-B(a) step 3: Attach the fully-built modifier clause to the NP." -> "NP-B(a) done";
            }

            subgraph cluster_np_bb {
                label="NP-B(b): Compound head noun\n(head noun requires its own multi-step build)\nSee {lang_code}.md: NP-B(b) section for steps, examples,\nand the MODIFICATION REVELATION BLOCK technique";

                "NP-B(b) step 1: Build the inner compound NP first\n(the head noun from inside out)." [shape=box];
                "NP-B(b) step 2: Build the modifier clause standalone." [shape=box];
                "NP-B(b) step 3 — MODIFICATION REVELATION BLOCK:\nAttach modifier clause to NP stem (omitting the final head noun).\nUse when: modifier clause is ≥ 3 words AND head noun is a compound.\nPurpose: makes the modification relationship explicit as a\ncognitive anchor before the final noun lands.\n(See {lang_code}.md for the stem marker form.)" [shape=box];
                "NP-B(b) step 4: Full sentence adds the final head noun." [shape=box];
                "NP-B(b) done" [shape=ellipse];

                "NP-B(b) step 1: Build the inner compound NP first\n(the head noun from inside out)." -> "NP-B(b) step 2: Build the modifier clause standalone.";
                "NP-B(b) step 2: Build the modifier clause standalone." -> "NP-B(b) step 3 — MODIFICATION REVELATION BLOCK:\nAttach modifier clause to NP stem (omitting the final head noun).\nUse when: modifier clause is ≥ 3 words AND head noun is a compound.\nPurpose: makes the modification relationship explicit as a\ncognitive anchor before the final noun lands.\n(See {lang_code}.md for the stem marker form.)";
                "NP-B(b) step 3 — MODIFICATION REVELATION BLOCK:\nAttach modifier clause to NP stem (omitting the final head noun).\nUse when: modifier clause is ≥ 3 words AND head noun is a compound.\nPurpose: makes the modification relationship explicit as a\ncognitive anchor before the final noun lands.\n(See {lang_code}.md for the stem marker form.)" -> "NP-B(b) step 4: Full sentence adds the final head noun.";
                "NP-B(b) step 4: Full sentence adds the final head noun." -> "NP-B(b) done";
            }

            "Is the head noun a SIMPLE noun or short compound?" -> "NP-B(a) step 1: Introduce the head noun first,\nwith any close modifiers." [label="yes → NP-B(a)"];
            "Is the head noun a SIMPLE noun or short compound?" -> "NP-B(b) step 1: Build the inner compound NP first\n(the head noun from inside out)." [label="no → NP-B(b)"];
        }

        subgraph cluster_np_compound {
            label="NP Sub-pattern: Compound modifier (V1+V2 or prefix+stem used as adjective)\nSee {lang_code}.md: Compound modifier section for examples";

            "Compound step 1: Introduce RIGHT component alone\n(aspectual / resultative / intensifier element).\nTranslate the aspectual MEANING, not the literal morpheme." [shape=box];
            "Compound step 2: Build full compound by adding LEFT component." [shape=box];
            "Compound step 3: Attach compound to the NP\n(at the position dictated by NP-A step 3)." [shape=box];

            "Compound step 1: Introduce RIGHT component alone\n(aspectual / resultative / intensifier element).\nTranslate the aspectual MEANING, not the literal morpheme." -> "Compound step 2: Build full compound by adding LEFT component.";
            "Compound step 2: Build full compound by adding LEFT component." -> "Compound step 3: Attach compound to the NP\n(at the position dictated by NP-A step 3).";
        }
    }

    // ================================================================
    // PHASE 2: PREDICATE VP CHUNKING
    // (nine pattern slots — language-specific definitions in {lang_code}.md)
    // ================================================================

    subgraph cluster_vp {
        label="PHASE 2: Chunking the Predicate VP\n(nine pattern slots — may be combined; details in {lang_code}.md)";

        subgraph cluster_vp_a {
            label="VP-A: Simple verb ± directly attached adverb\nSee {lang_code}.md: VP-A section";

            "VP-A step 1: Introduce main verb alone." [shape=box];
            "VP-A step 2: Add adverb to the left (if present)." [shape=box];
            "VP-A done" [shape=ellipse];

            "VP-A step 1: Introduce main verb alone." -> "VP-A step 2: Add adverb to the left (if present).";
            "VP-A step 2: Add adverb to the left (if present)." -> "VP-A done";
        }

        subgraph cluster_vp_b {
            label="VP-B: VP with manner/location phrase built around an internal modifiable noun\nDO NOT use VP-A for this predicate.\nWhen VP-B is active, ALL adverbs are sequenced within VP-B steps 4–6.\nSee {lang_code}.md: VP-B section";

            "VP-B step 1: Introduce core noun of the phrase alone." [shape=box];
            "VP-B step 2: Build the fixed phrase around it.\nLabel as idiomatic in l1 if applicable." [shape=box];
            "VP-B step 3: Expand the phrase by adding modifiers\nto its internal nouns." [shape=box];
            "VP-B step 4: Introduce standalone adverbs in SURFACE ORDER:\ntemporal → locative → manner.\nEach adverbial gets its own block." [shape=box];
            "VP-B step 5: Introduce main verb alone." [shape=box];
            "VP-B step 6: Combine adverb(s) + verb." [shape=box];
            "VP-B step 7: Attach manner/location phrase → full VP." [shape=box];
            "VP-B done" [shape=ellipse];

            "VP-B step 1: Introduce core noun of the phrase alone." -> "VP-B step 2: Build the fixed phrase around it.\nLabel as idiomatic in l1 if applicable.";
            "VP-B step 2: Build the fixed phrase around it.\nLabel as idiomatic in l1 if applicable." -> "VP-B step 3: Expand the phrase by adding modifiers\nto its internal nouns.";
            "VP-B step 3: Expand the phrase by adding modifiers\nto its internal nouns." -> "VP-B step 4: Introduce standalone adverbs in SURFACE ORDER:\ntemporal → locative → manner.\nEach adverbial gets its own block.";
            "VP-B step 4: Introduce standalone adverbs in SURFACE ORDER:\ntemporal → locative → manner.\nEach adverbial gets its own block." -> "VP-B step 5: Introduce main verb alone.";
            "VP-B step 5: Introduce main verb alone." -> "VP-B step 6: Combine adverb(s) + verb.";
            "VP-B step 6: Combine adverb(s) + verb." -> "VP-B step 7: Attach manner/location phrase → full VP.";
            "VP-B step 7: Attach manner/location phrase → full VP." -> "VP-B done";
        }

        subgraph cluster_vp_c {
            label="VP-C: Modal or evidential expression wrapping an embedded clause\n(seem / must / probably / appears-that type constructions)\nSee {lang_code}.md: VP-C section";

            "VP-C step 1: Build the embedded clause using VP-A or VP-B,\nfrom object/complement outward." [shape=box];
            "VP-C step 2: Introduce the modal expression AS A STANDALONE block." [shape=box];
            "VP-C step 3: Attach modal to embedded clause (full VP)." [shape=box];
            "VP-C done" [shape=ellipse];

            "VP-C step 1: Build the embedded clause using VP-A or VP-B,\nfrom object/complement outward." -> "VP-C step 2: Introduce the modal expression AS A STANDALONE block.";
            "VP-C step 2: Introduce the modal expression AS A STANDALONE block." -> "VP-C step 3: Attach modal to embedded clause (full VP).";
            "VP-C step 3: Attach modal to embedded clause (full VP)." -> "VP-C done";
        }

        subgraph cluster_vp_d {
            label="VP-D: Restrictive focus with negative potential\n(only X / cannot do anything but X type constructions)\nSee {lang_code}.md: VP-D section";

            "VP-D step 1: Object NP head alone." [shape=box];
            "VP-D step 2: Attach restriction marker (signals exclusivity)." [shape=box];
            "VP-D step 3: Verb in citation / dictionary form." [shape=box];
            "VP-D step 4: Build the negative-potential construction." [shape=box];
            "VP-D step 5: Combine object + restriction marker + predicate." [shape=box];
            "VP-D done" [shape=ellipse];

            "VP-D step 1: Object NP head alone." -> "VP-D step 2: Attach restriction marker (signals exclusivity).";
            "VP-D step 2: Attach restriction marker (signals exclusivity)." -> "VP-D step 3: Verb in citation / dictionary form.";
            "VP-D step 3: Verb in citation / dictionary form." -> "VP-D step 4: Build the negative-potential construction.";
            "VP-D step 4: Build the negative-potential construction." -> "VP-D step 5: Combine object + restriction marker + predicate.";
            "VP-D step 5: Combine object + restriction marker + predicate." -> "VP-D done";
        }

        subgraph cluster_vp_e {
            label="VP-E: Concessive or scene-frame adverbial clause\n(no matter where / whatever / whenever type constructions)\nDistinct from VP-B: VP-E clauses don't contain modifiable nouns.\nSee {lang_code}.md: VP-E section";

            "VP-E step 1: Introduce the concessive/frame as STANDALONE block." [shape=box];
            "VP-E step 2: Build the main predicate clause\nusing VP-A, VP-B, VP-C, or VP-D." [shape=box];
            "VP-E step 3: Prepend the concessive to the built VP." [shape=box];
            "VP-E done" [shape=ellipse];

            "VP-E step 1: Introduce the concessive/frame as STANDALONE block." -> "VP-E step 2: Build the main predicate clause\nusing VP-A, VP-B, VP-C, or VP-D.";
            "VP-E step 2: Build the main predicate clause\nusing VP-A, VP-B, VP-C, or VP-D." -> "VP-E step 3: Prepend the concessive to the built VP.";
            "VP-E step 3: Prepend the concessive to the built VP." -> "VP-E done";
        }

        subgraph cluster_vp_f {
            label="VP-F: Sequential clause (two actions joined by sequential connector)\n(and-then / after-which type constructions)\nSee {lang_code}.md: VP-F section";

            "VP-F step 1: Build the first action clause independently\nusing VP-A/B." [shape=box];
            "VP-F step 2: Build the second (main) action clause\nusing VP-A/B." [shape=box];
            "VP-F step 3: Combine first clause + connector + main clause." [shape=box];
            "VP-F done" [shape=ellipse];

            "VP-F step 1: Build the first action clause independently\nusing VP-A/B." -> "VP-F step 2: Build the second (main) action clause\nusing VP-A/B.";
            "VP-F step 2: Build the second (main) action clause\nusing VP-A/B." -> "VP-F step 3: Combine first clause + connector + main clause.";
            "VP-F step 3: Combine first clause + connector + main clause." -> "VP-F done";
        }

        subgraph cluster_vp_g {
            label="VP-G: Quoted speech or thought\n(said-that / thought-that / felt-that type constructions)\nSee {lang_code}.md: VP-G section";

            "VP-G step 1: Build the quoted clause (what was said/thought)\nas an embedded clause using VP-A/B/C." [shape=box];
            "VP-G step 2: Introduce the quoting verb alone." [shape=box];
            "VP-G step 3: Combine quoted clause + quoting verb (full VP)." [shape=box];
            "VP-G done" [shape=ellipse];

            "VP-G step 1: Build the quoted clause (what was said/thought)\nas an embedded clause using VP-A/B/C." -> "VP-G step 2: Introduce the quoting verb alone.";
            "VP-G step 2: Introduce the quoting verb alone." -> "VP-G step 3: Combine quoted clause + quoting verb (full VP).";
            "VP-G step 3: Combine quoted clause + quoting verb (full VP)." -> "VP-G done";
        }

        subgraph cluster_vp_h {
            label="VP-H: Passive main predicate\n(the sentence's primary verb is passive)\nDistinct from NP-B where a passive modifies a noun.\nSee {lang_code}.md: VP-H section";

            "VP-H step 1: Introduce the causer/agent + causer marker alone." [shape=box];
            "VP-H step 2: Introduce the passive verb form alone." [shape=box];
            "VP-H step 3: Combine agent + passive verb (full VP)." [shape=box];
            "VP-H done" [shape=ellipse];

            "VP-H step 1: Introduce the causer/agent + causer marker alone." -> "VP-H step 2: Introduce the passive verb form alone.";
            "VP-H step 2: Introduce the passive verb form alone." -> "VP-H step 3: Combine agent + passive verb (full VP).";
            "VP-H step 3: Combine agent + passive verb (full VP)." -> "VP-H done";
        }

        subgraph cluster_vp_i {
            label="VP-I: Conditional clause (if / when / unless type)\nSee {lang_code}.md: VP-I section";

            "VP-I step 1: Build the protasis (condition) independently\nusing VP-A/B as appropriate." [shape=box];
            "VP-I step 2: Build the apodosis (result) independently." [shape=box];
            "VP-I step 3: Combine protasis + conditional marker + apodosis." [shape=box];
            "VP-I done" [shape=ellipse];

            "VP-I step 1: Build the protasis (condition) independently\nusing VP-A/B as appropriate." -> "VP-I step 2: Build the apodosis (result) independently.";
            "VP-I step 2: Build the apodosis (result) independently." -> "VP-I step 3: Combine protasis + conditional marker + apodosis.";
            "VP-I step 3: Combine protasis + conditional marker + apodosis." -> "VP-I done";
        }
    }

    // ================================================================
    // PHASE 3: COMBINING SUBJECT + PREDICATE
    // ================================================================

    subgraph cluster_combine {
        label="PHASE 3: Combining Subject NP + Predicate VP";

        "Subject type?" [shape=diamond];

        "FRAGMENT (no predicate):\nFinal block = complete fragment.\nNo penultimate VP block." [shape=box];

        "COPULA SENTENCE:\nSee {lang_code}.md for copula handling.\nGeneral rule: if copula is a single short element,\nno separate penultimate VP block is needed.\nOtherwise: penultimate = NP + copula, final = full sentence." [shape=box];

        "SHORT SUBJECT path\n(simple noun / pronoun as subject):\nIf a scene-setting temporal or locative frame adverb precedes,\nintroduce that adverb FIRST, then attach subject.\nIf adverb directly modifies verb, introduce subject first.\nAfter subject is introduced: build full VP.\nPenultimate = full VP alone. Final = full sentence.\n(See {lang_code}.md for adverb-subject ordering rules.)" [shape=box];

        "LONG/COMPLEX SUBJECT path\n(NP with modifier chain, relative clause, or compound modifier):\nComplete the full subject NP chunk first.\nThen build the entire VP chunk.\nPenultimate = full VP clause alone.\nFinal = full subject NP + full VP." [shape=box];

        "Subject type?" -> "FRAGMENT (no predicate):\nFinal block = complete fragment.\nNo penultimate VP block." [label="fragment"];
        "Subject type?" -> "COPULA SENTENCE:\nSee {lang_code}.md for copula handling.\nGeneral rule: if copula is a single short element,\nno separate penultimate VP block is needed.\nOtherwise: penultimate = NP + copula, final = full sentence." [label="copula"];
        "Subject type?" -> "SHORT SUBJECT path\n(simple noun / pronoun as subject):\nIf a scene-setting temporal or locative frame adverb precedes,\nintroduce that adverb FIRST, then attach subject.\nIf adverb directly modifies verb, introduce subject first.\nAfter subject is introduced: build full VP.\nPenultimate = full VP alone. Final = full sentence.\n(See {lang_code}.md for adverb-subject ordering rules.)" [label="short subject"];
        "Subject type?" -> "LONG/COMPLEX SUBJECT path\n(NP with modifier chain, relative clause, or compound modifier):\nComplete the full subject NP chunk first.\nThen build the entire VP chunk.\nPenultimate = full VP clause alone.\nFinal = full subject NP + full VP." [label="long/complex subject"];
    }

    // ================================================================
    // FAMILIARITY FORMULA — universal
    // ================================================================

    subgraph cluster_familiarity {
        label="FAMILIARITY FORMULA (Laplace-smoothed) — universal across all languages";

        "familiarity =\n(times_seen + 1) /\n(times_seen + 1 + times_confused*3\n + times_slower*2 + times_explained*2 + 5)\n\nFresh item: 1/6 ≈ 0.17 (not yet familiar)\nAfter 5 clean OK: 6/11 ≈ 0.55\nAfter 15 clean OK: 16/21 ≈ 0.76\nAfter 20 clean OK: 21/26 ≈ 0.81 ← crosses 0.8 threshold\n\nSkip threshold: 0.8 (configurable per language profile in DB)\nCollapsing is PRESENTATION-TIME only — see ABSOLUTE RULES." [shape=octagon, style=filled, fillcolor=lightblue];
    }

    // ================================================================
    // ABSOLUTE RULES — apply to ALL languages
    // ================================================================

    subgraph cluster_rules {
        label="ABSOLUTE RULES — apply to ALL languages";

        "NEVER split a fixed grammatical expression\nacross multiple blocks.\nFixed expressions are ATOMIC — always one block.\n(See {lang_code}.md for language-specific fixed patterns list.)" [shape=octagon, style=filled, fillcolor=red, fontcolor=white];

        "NEVER make block 1 the full sentence.\nALWAYS start from the smallest meaningful unit." [shape=octagon, style=filled, fillcolor=red, fontcolor=white];

        "NEVER introduce a compound modifier without\nfirst showing its right component alone." [shape=octagon, style=filled, fillcolor=red, fontcolor=white];

        "PENULTIMATE BLOCK RULE (qualified):\n- Sentences with complex VP (VP-B/C/D/E/F/G/H/I):\n  penultimate = full VP clause alone.\n- Copula sentences where copula is a single short element:\n  no separate penultimate VP block.\n- Grammatical fragments: final block = complete fragment;\n  no penultimate VP block." [shape=octagon, style=filled, fillcolor=orange];

        "NEVER mix VP-A and VP-B for the same predicate.\nOnce VP-B is chosen, ALL adverbs are handled\nwithin VP-B steps 4–6." [shape=octagon, style=filled, fillcolor=orange];

        "Block collapsing is PRESENTATION-TIME only.\nNEVER alter stored sentence_blocks.\nDo NOT collapse across pattern boundaries\n(NP block + VP block, or modal standalone + embedded clause).\nCollapsing is only safe within one pattern's consecutive steps." [shape=octagon, style=filled, fillcolor=orange];

        "ALWAYS complete the 4-step draft in Phase 0\nbefore writing any blocks." [shape=octagon, style=filled, fillcolor=orange];
    }

    // Cross-cluster reading order
    "Analysis complete" -> "NP-A done" [style=dotted, label="apply matching\nNP pattern"];
    "Analysis complete" -> "NP-B(a) done" [style=dotted];
    "Analysis complete" -> "NP-B(b) done" [style=dotted];
    "NP-A done" -> "VP-A done" [style=dotted, label="apply matching\nVP pattern(s)"];
    "NP-B(a) done" -> "VP-A done" [style=dotted];
    "NP-B(b) done" -> "VP-A done" [style=dotted];
    "VP-A done" -> "Subject type?" [style=dotted];
    "VP-B done" -> "Subject type?" [style=dotted];
    "VP-C done" -> "Subject type?" [style=dotted];
    "VP-D done" -> "Subject type?" [style=dotted];
    "VP-E done" -> "Subject type?" [style=dotted];
    "VP-F done" -> "Subject type?" [style=dotted];
    "VP-G done" -> "Subject type?" [style=dotted];
    "VP-H done" -> "Subject type?" [style=dotted];
    "VP-I done" -> "Subject type?" [style=dotted];
}
```

## Quick-Reference: Pattern Slots

| Pattern | Type | Concept |
|---|---|---|
| NP-A | NP | Simple modifier chain (no relative clause) |
| NP-B(a) | NP | Relative/modifier clause + simple head noun |
| NP-B(b) | NP | Relative/modifier clause + compound head noun (Modification Revelation Block) |
| NP-Compound | NP sub | Compound modifier (V1+V2 or similar) used as adjective |
| VP-A | VP | Simple verb ± directly attached adverb |
| VP-B | VP | Manner/location phrase with internal modifiable noun |
| VP-C | VP | Modal/evidential wrapping embedded clause |
| VP-D | VP | Restrictive focus with negative potential |
| VP-E | VP | Concessive or scene-frame adverbial clause |
| VP-F | VP | Sequential clause (two actions) |
| VP-G | VP | Quoted speech or thought |
| VP-H | VP | Passive main predicate |
| VP-I | VP | Conditional clause |

**For language-specific triggers, step-by-step definitions, and annotated examples — see `knowledge/{lang_code}.md`.**

## Quick-Reference: Block Count Guidelines

| Sentence length | Expected blocks |
|---|---|
| Short (< 15 chars) | 5–9 |
| Medium (15–40 chars) | 6–10 |
| Long (40–80 chars) | 9–14 |
