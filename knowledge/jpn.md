# Japanese (jpn) — Language-Specific Chunking Reference

This file is consulted alongside `knowledge/chunking-strategy.md` when generating blocks for Japanese sentences. It defines the language-specific content for each pattern slot (NP-A, NP-B, VP-A–I) and provides annotated ground-truth examples.

**L1:** Traditional Chinese (繁體中文, Taiwan)

---

## L1 Register Target

Natural Taiwanese Mandarin as spoken by an educated adult in Taipei. Translations should read like something a Taiwanese speaker would actually say in everyday conversation — not literal word-for-word glosses, not formal/literary Chinese, not Mainland-register phrasing. If a draft reads like Google Translate output, revise it.

### Anti-patterns (Mandarin L1)

- **的-chain pileup**: avoid more than two consecutive `的` in a single noun phrase. Restructure with a relative clause, appositive, or split sentence.
- **所-被-由 literary passive**: do not use `所` / `被...所` / `由...所` chains unless the L2 register is explicitly formal/literary.
- **Four-character compound stacking**: avoid piling 成語 / 四字格 to sound "literary". Plain words are usually better.
- **Translationese copula**: do not translate every Japanese です/だ with `是` — Mandarin often drops it, or uses a different construction.
- **Pronoun over-specification**: Mandarin drops pronouns readily; do not preserve every implied Japanese pronoun.
- **Particle literalism**: do not try to preserve は/が/を/に distinctions in Chinese word order — reorder the sentence if needed.

Consult these anti-patterns during the /inch-generate-blocks self-check step.

---

## Phase 0: Japanese-Specific Analysis Notes

**Main clause types:**
- `A) [NP は/が] + [VP]` — subject + predicate
- `B) [NP with relative clause] + [VP]` — head noun modified by embedded verb phrase
- `C) [NP] + copula (だ / です / である)` — nominal predicate
- `D) Grammatical fragment` — excerpt ending mid-clause (common in literary prose)

**Subject NP identification:**
- Head noun + case marker: `が` (subject), `は` (topic/subject), `を` (object), `に` (direction/agent), `から` (source), `で` (location/means)
- Note ALL left-branching modifiers: adjectives (い/な), adverbs, の-modifiers, relative clauses
- Note compound verbs used as pre-nominal modifiers (V1-V2 forms like 冷え切った, 言い切った)

**Fixed expressions — always one atomic block:**
```
ような気がする  /  ことが出来ず  /  ことができない
に沿う形で  /  に関して  /  に基づいて
どこに居ても  /  さっきから  /  いつの間にか
に違いない  /  かもしれない  /  と思われる
```
Add language-specific ones you encounter during study.

---

## NP-A: Simple NP (modifier chain without relative clause)

**Trigger:** Subject NP consists of head noun + any combination of: い/な adjectives, adverbs, の-modifier chains, compound verb modifiers. No embedded verb clause.

**Examples:** S1 subject `生成り色の細長い建売住宅が`, S4 subject `冷え切った右手の指先のささくれが`

### Steps

**Step 1:** Introduce HEAD NOUN + case marker alone.
- S1: `建売住宅が` ← head noun
- S4: `ささくれが` ← head noun

**Step 2:** Add ONE modifier at a time, expanding LEFT (adjective → adjective+adjective → attr-NP+adjective → …). Japanese is left-branching — modifiers always precede the noun.
- S1: → `細長い建売住宅が` → `生成り色の細長い建売住宅が`
- S4: → `指先のささくれが` → `右手の指先のささくれが`

**Step 3:** If any modifier is a compound verb (V1-V2, see Compound sub-pattern below), apply the Compound sub-pattern FIRST before attaching it to the NP.
- S4: `切った` → `冷え切った` → `冷え切った右手の指先のささくれが`

---

## NP-B(a): NP with relative clause — simple head noun

**Trigger:** Head noun is modified by a verb phrase (relative clause in Japanese = pre-nominal verb phrase). Head noun is a simple noun or short compound (1–2 elements).

**Example:** S6 subject `子育てモデル地区に指定された郊外のこの町は`

### Steps

**Step 1:** Introduce the head noun first, with any close modifiers.
- `この町は` → `郊外のこの町は`

**Step 2:** Build the relative clause SEPARATELY from its own head outward (left-branching, expand leftward).
- `指定された` → `モデル地区に指定された` → `子育てモデル地区に指定された`

**Step 3:** Attach fully-built relative clause to the NP:
- `子育てモデル地区に指定された郊外のこの町は`

---

## NP-B(b): NP with relative clause — compound head noun

**Trigger:** Head noun is itself a compound requiring multi-step build (2+ elements), AND it is modified by a relative clause.

**Example:** S5 `初めて降りる田園都市線の駅だ`

### Steps

**Step 1:** Build the inner compound NP (head noun from inside out):
- `田園都市線` → `田園都市線の駅`

**Step 2:** Build the relative clause standalone:
- `初めて降りる`

**Step 3 — MODIFICATION REVELATION BLOCK:** Attach relative clause to the NP stem (の), omitting the final head noun. Use when: relative clause ≥ 3 words AND head noun is a compound. The の-modifier relationship is made explicit as a cognitive anchor before the final noun lands.
- `初めて降りる田園都市線の` ← note: `駅` is omitted
- l1 shows the full meaning even though `駅` is not in the tts text

**Step 4:** Full sentence adds the final head noun:
- `初めて降りる田園都市線の駅だ。`

---

## NP Sub-pattern: Compound Modifier (V1+V2 compound verb as adjective)

**Trigger:** A V1+V2 compound verb modifies the head noun (e.g. 冷え切った, 言い切った, 走り回った).

**Example:** `冷え切った` in S4

### Steps

**Step 1:** Introduce RIGHT component alone (the aspectual/resultative element). Translate the ASPECTUAL MEANING, not the literal morpheme. Match register of source text.
- `切った` → l1: `到爆` (colloquial register for physical intensity)
- Note: `切った` alone in this context = "to an extreme degree / completely through". NOT "cut".
- Literary/formal text → `徹底`, `完全`, `極度` etc. | Casual/spoken → `到爆`, `超～` etc.

**Step 2:** Build full compound by adding LEFT component:
- `冷え切った` → l1: `冷到爆`

**Step 3:** Attach compound to the NP (at NP-A step 3 position):
- `冷え切った右手の指先のささくれが`

---

## VP-A: Simple verb ± directly attached adverb

**Trigger:** VP has NO internally modifiable phrase before the verb. A single adverb like 大きく, ゆっくり, すぐに directly precedes the verb.

**Example:** S4 predicate `大きくめくれた`

### Steps

**Step 1:** Introduce main verb alone:
- `めくれた` → l1: `翻了`

**Step 2:** Add adverb to the left:
- `大きくめくれた。` → l1: `翻了一大塊。`

---

## VP-B: VP with manner/location phrase built around an internal modifiable noun

**Trigger:** A phrase BEFORE the verb contains a noun that is itself modified (e.g. `なだらかな丘に沿う形で` — `丘` is modified by `なだらかな`). DO NOT use VP-A for this predicate.

**Example:** S1 predicate `なだらかな丘に沿う形でどこまでも連なっている`

### Steps

**Step 1:** Introduce the core noun of the phrase alone:
- `丘` → l1: `山丘`

**Step 2:** Build the fixed phrase around it. Label as `（固定句型）` in l1 if idiomatic:
- `丘に沿う形で` → l1: `順著山丘（固定句型）`

**Step 3:** Expand the phrase by adding modifiers to its internal nouns:
- `なだらかな丘に沿う形で` → l1: `順著平緩的山丘`

**Step 4:** Introduce standalone adverbs in SURFACE ORDER (temporal → locative → manner). Each gets its own block:
- `どこまでも` → l1: `無論到哪裡都（無止盡地）`

**Step 5:** Introduce main verb alone:
- `連なっている` → l1: `連綿排列著`

**Step 6:** Combine adverb(s) + verb:
- `どこまでも連なっている`

**Step 7:** Attach manner/location phrase → full VP:
- `なだらかな丘に沿う形でどこまでも連なっている。`

---

## VP-C: Modal expression wrapping embedded clause

**Trigger:** Modal/evidential fixed expressions wrapping an embedded clause: `ような気がする`, `と思う`, `かもしれない`, `に違いない`, `と感じる`.

**Example:** S3 predicate `同じ場所をずっとぐるぐる回っているような気がする`

### Steps

**Step 1:** Build the embedded clause using VP-A or VP-B, from object/complement outward:
- `同じ場所を` → `ずっと` → `ずっとぐるぐる回っている` → `同じ場所をずっとぐるぐる回っている`

**Step 2:** Introduce the modal expression AS A STANDALONE block:
- `ような気がする` → l1: `看起來`

**Step 3:** Attach modal to embedded clause (full VP):
- `同じ場所をずっとぐるぐる回っているような気がする。`

---

## VP-D: しか…できない / ことが出来ず restriction

**Trigger:** Restrictive focus pattern using `しか` + negative potential (`ことが出来ない/ず`, `しかできない`).

**Example:** S2 predicate `均一な印象しか受けとることが出来ず`

### Steps

**Step 1:** Object NP head alone:
- `均一な印象` → l1: `均一的印象`

**Step 2:** Attach `しか` (signals restriction/exclusivity):
- `均一な印象しか` → l1: `除了單調的印象`

**Step 3:** Verb in dictionary/citation form:
- `受けとる` → l1: `感受到`

**Step 4:** Build the negative-potential construction:
- `受けとることが出来ず` → l1: `不能感受到什麼`

**Step 5:** Combine object+しか + predicate:
- `均一な印象しか受けとることが出来ず`

---

## VP-E: Concessive/scene-frame adverbial clause

**Trigger:** `どこに居ても`, `どんなに〜ても`, `いつも`, `たとえ〜ても` — concessive or universal frame clauses. Distinct from VP-B: VP-E clauses don't contain internally modifiable nouns.

**Example:** S2 `どこに居ても`

### Steps

**Step 1:** Introduce the concessive/frame as STANDALONE:
- `どこに居ても` → l1: `無論身在何處`

**Step 2:** Build the main predicate clause using VP-A, VP-B, VP-C, or VP-D.

**Step 3:** Prepend the concessive to the built VP:
- `どこに居ても` + [VP from step 2]

---

## VP-F: Te-form sequential clause (〜て / 〜で joining two actions)

**Trigger:** Two actions joined by て-form connector.

**Example:** `電車を降りて、改札口を出た。`

### Steps

**Step 1:** Build the te-clause (first action) as independent clause using VP-A/B:
- `電車を降りて` → l1: `下了電車`

**Step 2:** Build the main clause (second action) using VP-A/B:
- `改札口を出た` → l1: `出了剪票口`

**Step 3:** Combine te-clause + main clause:
- `電車を降りて、改札口を出た。`

---

## VP-G: Quoted speech / thought (〜と言った / 〜と思った / 〜と感じた)

**Trigger:** Quoting verb construction with `と`.

**Example:** `彼女は「また来たい」と言った。`

### Steps

**Step 1:** Build the quoted clause as embedded clause using VP-A/B/C:
- `また来たい` → l1: `還想再來`

**Step 2:** Introduce the quoting verb alone:
- `と言った` → l1: `說道`

**Step 3:** Combine quoted clause + と + quoting verb:
- `また来たいと言った。`

---

## VP-H: Passive main predicate

**Trigger:** The sentence's primary verb is passive (〜られた/〜された). Distinct from NP-B where a passive verb modifies a noun.

**Example:** `彼女は上司に叱られた。`

### Steps

**Step 1:** Introduce agent with `に` alone (the causer):
- `上司に` → l1: `被主管`

**Step 2:** Introduce passive verb form alone:
- `叱られた` → l1: `責罵了`

**Step 3:** Combine agent + passive verb:
- `上司に叱られた。` → l1: `被主管責罵了。`

---

## VP-I: Conditional clause (〜たら / 〜ば / 〜と / 〜なら)

**Trigger:** Conditional connectives: `〜たら`, `〜ば`, `〜と`, `〜なら`.

**Example:** `雨が降ったら、試合は中止になる。`

### Steps

**Step 1:** Build the protasis (condition) independently using VP-A/B:
- `雨が降ったら` → l1: `如果下雨的話`

**Step 2:** Build the apodosis (result) independently:
- `試合は中止になる` → l1: `比賽會中止`

**Step 3:** Combine protasis + apodosis:
- `雨が降ったら、試合は中止になる。`

---

## Phase 3: Japanese Combining Notes

**Copula sentences (だ/です/である):**
- If NP-B(b) was used: copula is part of the final block (S5: `初めて降りる田園都市線の駅だ。`). No separate penultimate VP block when copula is a single syllable.
- Otherwise: penultimate = NP + copula, final = full sentence.

**Short subject — adverb ordering:**
- If attached adverb is a SCENE-SETTING TEMPORAL or LOCATIVE FRAME (`さっきから`, `あの頃`, `そこで`, etc.) → introduce adverb FIRST, then attach subject: `さっきから` → `里佳はさっきから`
- If adverb directly modifies the VERB (`ゆっくり`, `すぐに`, etc.) → introduce subject first: `里佳は` → `里佳はすぐに`

---

## Annotated Samples (ground truth — never contradict these)

### S1 — NP-A + VP-B — long/complex subject
```
生成り色の細長い建売住宅が、なだらかな丘に沿う形でどこまでも連なっている。
[1] 建売住宅が            NP-A step 1: head noun
[2] 細長い建売住宅が      NP-A step 2: add adj
[3] 生成り色の細長い建売住宅が  NP-A step 2: add attr-NP
[4] 丘                    VP-B step 1: core noun of manner phrase
[5] 丘に沿う形で          VP-B step 2: fixed phrase（固定句型）
[6] なだらかな丘に沿う形で  VP-B step 3: expand phrase
[7] どこまでも            VP-B step 4: standalone adverb
[8] 連なっている          VP-B step 5: main verb
    (どこまでも連なっている — implicit, absorbed by step 7+8 pairing)
[9] なだらかな丘に沿う形でどこまでも連なっている。  VP-B step 7: full VP (PENULTIMATE)
[10] full sentence
```

### S2 — NP-A (with postposition) + VP-E + VP-D — long/complex subject
```
よく整備された町並みからはどこに居ても均一な印象しか受けとることが出来ず
[1] 町並み                     NP-A step 1
[2] 整備された町並み           NP-A step 2: add relative modifier
[3] よく整備された町並み       NP-A step 2: add adverb to modifier
[4] よく整備された町並みからは  NP-A step 2: add postposition
[5] どこに居ても               VP-E step 1: concessive standalone
[6] 均一な印象                 VP-D step 1: object NP
[7] 均一な印象しか             VP-D step 2: add しか
[8] 受けとる                   VP-D step 3: dictionary form
[9] 受けとることが出来ず       VP-D step 4: negative potential
[10] 均一な印象しか受けとることが出来ず  VP-D step 5
[11] どこに居ても均一な印象しか受けとることが出来ず  VP-E step 3 (PENULTIMATE)
[12] full clause
```

### S3 — short subject (frame adverb first) + VP-C
```
里佳はさっきから同じ場所をずっとぐるぐる回っているような気がする。
[1] さっきから              short subject path: frame adverb first
[2] 里佳はさっきから        subject attached to frame
[3] 同じ場所を              VP-C step 1: embedded clause object
[4] ずっと                  VP-C step 1: embedded clause adverb
[5] ずっとぐるぐる回っている  VP-C step 1: verb
[6] 同じ場所をずっとぐるぐる回っている  VP-C step 1: full embedded clause
[7] ような気がする          VP-C step 2: modal standalone
[8] 同じ場所をずっとぐるぐる回っているような気がする。  VP-C step 3 (PENULTIMATE)
[9] full sentence
```

### S4 — NP-A + Compound modifier + VP-A — long/complex subject
```
冷え切った右手の指先のささくれが、大きくめくれた。
[1] ささくれが              NP-A step 1
[2] 指先のささくれが        NP-A step 2
[3] 右手の指先のささくれが  NP-A step 2
[4] 切った                  Compound step 1: right component
[5] 冷え切った              Compound step 2: add left
[6] 冷え切った右手の指先のささくれが  Compound step 3: attach
[7] めくれた                VP-A step 1: main verb
[8] 大きくめくれた。        VP-A step 2: add adverb (PENULTIMATE)
[9] full sentence
```

### S5 — NP-B(b) + copula — Modification Revelation Block
```
初めて降りる田園都市線の駅だ。
[1] 田園都市線              NP-B(b) step 1: inner compound
[2] 田園都市線の駅          NP-B(b) step 1: build compound NP
[3] 初めて降りる            NP-B(b) step 2: relative clause
[4] 初めて降りる田園都市線の  NP-B(b) step 3: MODIFICATION REVELATION
    (omits final head noun 駅; makes の-modification explicit)
    l1 shows full meaning even though 駅 is not in tts
[5] 初めて降りる田園都市線の駅だ。  final sentence
    (copula sentence: no separate penultimate VP block)
```

### S6 — NP-B(a) — FRAGMENT (subject only, no predicate shown)
```
子育てモデル地区に指定された郊外のこの町は
[1] この町は                        NP-B(a) step 1: head noun
[2] 郊外のこの町は                  NP-B(a) step 1: add modifier
[3] 指定された                      NP-B(a) step 2: relative clause head
[4] モデル地区に指定された          NP-B(a) step 2: expand
[5] 子育てモデル地区に指定された    NP-B(a) step 2: expand
[6] 子育てモデル地区に指定された郊外のこの町は  NP-B(a) step 3: attach
    (fragment: [6] IS the final block — no penultimate VP)
```

---

## L1 Translation Rules (Traditional Chinese, Taiwan)

**L1-1:** Each block's l1 translates ONLY the tts content of THAT block — never the full sentence.

**L1-2:** Fixed expressions — add a usage note in parentheses:
- `丘に沿う形で` → `順著山丘（固定句型）`
- `ような気がする` → `看起來`
- `ことが出来ず` → `不能~`
- `どこに居ても` → `無論身在何處`

**L1-3:** Compound verb auxiliaries — translate the ASPECTUAL or RESULTATIVE meaning, not the literal morpheme. Match the REGISTER of the source text:
- Literary/formal text → `徹底`、`完全`、`極度` etc.
- Casual/spoken text → `到爆`、`超～` etc.
- `切った` in `冷え切った` (physical, colloquial context) → `到爆` is appropriate.
- DO NOT use slang translations for formal literary prose.

**L1-4:** Partial-phrase blocks must use natural Traditional Chinese, not word-by-word gloss:
- `均一な印象しか` → `除了單調的印象` (not `只有均一的印象`)

**L1-5:** `l2_display` = `tts_text` exactly. No furigana, no additions.

**L1-6:** Register matching principle: the L1 translation's register must match the source sentence's register. Literary prose → formal Chinese. Conversational dialogue → natural spoken Chinese. Never use internet slang for a literary text.

---

## Pattern Selection Guide (Japanese)

| Sentence feature | NP pattern | VP pattern |
|---|---|---|
| NP with only adjectives / adverbs / の-modifiers | NP-A | — |
| NP with relative clause; simple head noun | NP-B(a) | — |
| NP with relative clause; compound head noun | NP-B(b) | — |
| Compound modifier (V1+V2, e.g. 冷え切った) | NP-A + Compound sub | — |
| Verb ± single directly attached adverb | — | VP-A |
| Manner/location phrase with internal modifiable noun | — | VP-B |
| Modal wrapping embedded clause (ような気がする etc.) | — | VP-C |
| しか…できない / ことが出来ず restriction | — | VP-D |
| Concessive or scene-frame clause (どこに居ても etc.) | — | VP-E |
| Te-form sequential (〜て joining two actions) | — | VP-F |
| Quoted speech / thought (〜と言った/思った) | — | VP-G |
| Passive main predicate (not as relative modifier) | — | VP-H |
| Conditional clause (〜たら/ば/と/なら) | — | VP-I |
