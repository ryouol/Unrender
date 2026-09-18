# Safe chart parsing and completion checks

Local implementation and CPU verification, September 18, 2026. This is not a
production provider rollout or a new model evaluation.

## Contract

`chart-json-v2` accepts the complete canonical ChartData shape. It may remove a
prose/Markdown envelope and trailing commas **outside quoted strings**. It never
closes a truncated object, completes a numerical token, changes quoted labels,
drops points, guesses key synonyms, or converts currency/percentage/suffix strings
into numbers without unit context. Duplicate keys, nonfinite values, missing
points, unknown fields, unsupported types, and incomplete structures are rejected.
The existing finite binary-float value representation remains; arbitrary-precision
numerical preservation is not claimed.

Only a whole table or no table is returned. Diagnostics are fixed codes that do
not contain source labels, numerical values or raw model text. A recovered table
is explicitly marked `syntax_repaired`. Parser acceptance is structural/type
validation, **not** proof of accurate values or unambiguous series/category identity.
Those have separate semantic evaluation checks and need human review.

The primary `chart-table-v2` scorer still uses raw strict output; safe formatting
recovery earns no primary quality credit. Reports now identify the parser version
because secondary recovery diagnostics differ from historical reports. The shared
strict JSON loader rejects duplicate keys and nonfinite constants in both paths.
Historical results and their source hashes remain unchanged.

## Provider completion boundary

The new production contract is `unrender-infer-one-v3`. Its release digest includes
the provider and parser source, so it cannot silently impersonate the deployed
v2 provider. It returns parser version, privacy-safe diagnostics, generated-token
count, output cap and observed finish reason.

The Transformers adapter inspects the generated token sequence before decoding.
It reports EOS only if the sequence ends in a configured EOS token **below** the
cap. Reaching the cap is classified as `length` even if the last token is EOS,
because generation configuration may force EOS at that boundary. Other endings
are `unknown`. This is a conservative completion check, not a correctness claim.
[Transformers generation configuration](https://huggingface.co/docs/transformers/v4.57.1/en/main_classes/text_generation)
documents the token cap, EOS and forced-EOS behavior; the pinned production
runtime remains Transformers 4.57.6 and needs its own GPU canary.

The application requires the matching parser contract and a verified completion.
It independently parses the raw output and compares it to the provider's table
and diagnostic claims. A token-cap result receives `model_output_truncated`; an
unverified completion receives `model_completion_unverified`. Neither publishes
a partial result. These error codes/messages persist through the existing job
failure path and are exposed by its API/UI. A dispatched attempt remains spent;
no automatic additional GPU attempt is made.

Provider and application must roll out together with matching release pins.
Deploying this API against the old provider will fail the contract check; there
is no compatibility fallback that silently trusts missing completion metadata.
No deployment was made during this verification.

## Saved-output audit

[Machine-readable audit](saved-output-audit.json) records source/prediction hashes
and all 300 historical inputs per model. CPU-only reproduction from the repository
root, with the saved model-output directory available:

```sh
python -m analysis.parser_audit --model-root PATH/TO/SAVED/OUTPUTS \
  --out outputs/parser-v2-audit.json
```

| Model | Complete tables accepted | Rejected | Primary semantic cell F1 |
|---|---:|---:|---:|
| Base 4B | 232/300 | 68 | 6.59% |
| Fair table LoRA | 289/300 | 11 | 28.90% |
| Numeric-loss LoRA | 284/300 | 16 | 26.67% |

None of these accepted outputs needed the allowed syntax repairs. All 11 rejected
fair-model responses are invalid JSON. The earlier parser recovered all 300 fair
outputs using its broader repair policy; those recoveries cannot support a clean,
complete-output claim. The primary scores are unchanged from the existing v2
receipt because that scorer already withheld credit from repaired raw responses.

These artifacts do not record reliable finish metadata for every historical
attempt. The table is parser acceptance, **not** a claim that the new live provider
would accept every one of those responses. It also says nothing new about the
production image budget or real-chart generalization. Raw-artifact distribution
and clean-clone reproducibility remain separate readiness work.

## Verification and unfinished work

Final full-suite run: **427 passed, one skipped**, four existing warnings, 125.53
seconds. The skip is the private train-table overlap check. Product lint/security
lint, evaluation/parser lint and formatting, and product type checking passed.
The source hash in the saved-output receipt was checked against the final parser.
All inference tests used local mocks; no trained model or paid provider was called.

Adversarial tests cover every proper prefix of a representative table, unfinished
exponents and strings, null/boolean/printed-number points, duplicate keys, escaped
quotes, punctuation inside labels, multiple JSON objects, privacy-safe diagnostics,
EOS/cap distinctions, mismatched provider claims, and persisted token-cap failure
without a partial result, double charge or automatic retry.

At this parser milestone, successful diagnostics were not yet durable per result.
The follow-up [extraction receipt verification](../extraction-receipts/README.md)
implements that requirement across correction/restore, review and every export.
A bounded real-GPU check is also still required before provider promotion.
