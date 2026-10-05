"""Versioned repair prompts built only from model-visible task inputs."""

from .runtime import VISIBLE_COMMAND

CONTRACT_CHECK = (
    " Contract coverage check: keep one compact checklist of the reported symptoms and the relevant "
    "invariants found in repository documentation. For each item, identify the implementation path, "
    "required behavior, and verification status. A symptom may involve multiple modules; do not mark "
    "it resolved after changing only the first suspicious location. After reading the relevant contract "
    "and implementation, make the supported repairs instead of repeatedly rewriting plans. "
    "Before finishing, review every checklist item against the final source, including interactions "
    "between modules, and run the permitted visible tests. Passing those tests does not establish "
    "coverage of undocumented test cases. In the final response, briefly list each symptom, the repair "
    "and verification evidence, and any unresolved behavior. Do not invent test results."
)


def repair_prompt(description: str, allowed_files, search_backend: str, policy: str = "baseline",
                  visible_command: str = VISIBLE_COMMAND) -> str:
    if policy not in {"baseline", "contract-check"}:
        raise ValueError("Unknown repair prompt policy")
    prompt = (f"{description}\n\nAllowed source files: {', '.join(allowed_files)}. "
              f"Read related modules before editing. Do not modify tests or create files. "
              f"The only permitted shell command is: {visible_command}. "
              "Fix the implementation; passing visible tests alone is not final acceptance.")
    if search_backend != "off":
        prompt += (" Use search_code first to locate relevant code and documented contracts. "
                   "Check cross-module behavior and use read_file for full context before editing. "
                   "Search may return no evidence; existing read/glob/grep remain available.")
    return prompt + (CONTRACT_CHECK if policy == "contract-check" else "")
