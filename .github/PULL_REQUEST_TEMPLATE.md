## Summary

<!--
Describe what this PR does and why. Reference any related issues.
-->

## Changes

- 

## Testing

- [ ] `pytest tests/` passes locally
- [ ] New or changed pipeline stages have corresponding unit tests
- [ ] If templates/patches were changed, eval fixtures in `eval/reference_prompts.json` are updated

## Checklist

- [ ] No secrets or `.env` files committed
- [ ] `.gitignore` updated if new artifact types are produced
- [ ] `TECHNICAL_SPEC.md` updated if scope or architecture changed
- [ ] RAG index rebuilt (`python -m rag.ingest`) if knowledge base files were edited
