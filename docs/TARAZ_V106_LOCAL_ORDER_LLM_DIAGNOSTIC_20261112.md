# Taraz v1.0.6 local order LLM diagnostic (2026-11-12)

Scope: worker-4 source-only audit, synthetic tests. No release, installed program, user ledger, or Ollama service/process modification.

## Evidence

- Exact source real order probe: suggest_order('چاپ 200 عدد بروشور') with local qwen3:4b on POST /api/generate, JSON mode, think=false, num_predict=80, num_ctx=512: **timeout** waiting for HTTPConnection.getresponse(), configured timeout 45 seconds. Shell output LIVE_ORDER_EXIT=1, ELAPSED_SEC=45.2. No validated real suggestion was produced.
- Prime separately reported minimal generate JSON returning in ~20 seconds; qwen3:0.6b generated an empty-fields response with all seven production kinds. These are prime-reported observations; worker-4 has not independently reproduced them.
- Prime reported Quadro K4000 3GB, with qwen3:4b partly on CPU. Slower model throughput is plausible but not independently proven as the root cause.

## Correction

- A model-suggested stage must have direct matching evidence for that operation in the original request. Reject the **entire** response if any stage is unsupported by the text. Product nouns alone (box, carton, paper) do not justify extra packaging/material production stages.
- Reject responses containing no grounded nonempty field and no supported stage. Preserve exact source grounding for numeric quantities; never fabricate party, order quantity, or planned production.
- Keep qwen3:4b pinned, bounded 45s timeout, strict JSON schema and error fallback. No automatic order or financial posting.

## Verification

- py -3.12 -B -m unittest tests.test_taraz_clarify_product_contract_20261111 -q: **13/13 PASS**. Includes all-seven-stage hallucination rejection, empty-response rejection, and a grounded print order test which clears fabricated customer and production quantity.
- git diff --check on the two source/test files: exit 0.
- SHA-256 taraz_llm_order_suggest.py: 9F5596DEF0B30AD055BDB5ED9AD789109C713C8F2E96D807C72B28BA2BFAFEF0
- SHA-256 tests/test_taraz_clarify_product_contract_20261111.py: CC42998A68BAEC45BB267777FC71A46787E44BA128F02A5AA5B466C0E4462094

Live inference is **unverified**; this patch improves fail-closed semantics. Prime owns source re-freeze and the next immutable v1.0.6 build.
