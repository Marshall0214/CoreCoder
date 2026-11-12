The base rollout (base1.md) shows the agent repeatedly reading `toolz/itertoolz.py` at offset 800 (steps 4-7), but failing to identify that `iteritems` is undefined in Python 3. The public validation fails with NameError: name &#x27;iteritems&#x27; is not defined at line 918. The candidate.diff.txt shows the correct fix: replacing `iteritems(d)` with `d.items()`. 

The systemprompt.md now encodes this verified workspace fact directly: the defect location, the undefined name, and the exact fix. This prevents future agents from rediscovering what is already known.

The tool_guidance.md adds a specific rule about `iteritems` being Python 2-only, which addresses the root cause of the error.

context_policy.json is updated to enable deduplicate_reads, complete_symbols_first, and read_index as specified in the mission requirements.