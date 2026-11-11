# Working on awt

This repository is the source of the tool. The `AGENTS.md` that users get is a template embedded in the `awt` script, not this file.

- `SPEC.md` is the contract. Change it in the same commit as behaviour.
- `awt` stays one file: Python 3.9+, stdlib only. `migrate-wt` is a separate one-off.
- Complexity is debt. The verb limit in `SPEC.md` is real: a new verb means removing one.
- A rule belongs in a script or test, not in prompt text.
- Run before committing: `python3 -m unittest discover -s tests -p 'test_*.py' && python3 tests/chaos.py`.
- `tests/agentic/run.py` spends real tokens. Run it when `AGENTS.md` text or a verb's interface changes.
- Fixtures use the fictional `parsekit` project. Never add real task data or token-shaped strings to this repository.
- The node tree, Paseo plugin and `migrate-paseo` are specified in `SPEC.md` (Node tree) and `tests/TEST-SPEC.md`. Write the test for a rule before the code for it.
