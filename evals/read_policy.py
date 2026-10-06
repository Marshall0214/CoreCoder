"""Optional bounded reads; the ordinary CoreCoder tool remains unchanged."""

import copy

from corecoder.tools.read import ReadFileTool


class BoundedReadTool(ReadFileTool):
    description = ('Read a source fragment with line numbers: at most 120 lines and 6000 characters. '
                   'Locate relevant symbols with grep/search_code, then use offset to read them. '
                   'The response states the next offset when truncated. Read before editing.')
    parameters = copy.deepcopy(ReadFileTool.parameters)
    parameters['properties']['limit']['description'] = 'Max lines, default 120; requests above 120 are capped.'

    def execute(self, file_path, offset=1, limit=120):
        if type(offset) is not int or type(limit) is not int or offset < 1 or limit < 1:
            return 'Error: offset and limit must be positive integers'
        response = super().execute(file_path, offset, min(limit, 120))
        if response.startswith('Error:') or response == '(empty file)':
            return response
        lines, shown, used = [], 0, 0
        for line in response.splitlines():
            if '\t' not in line or not line.split('\t', 1)[0].isdigit():
                continue  # Replace the ordinary pagination footer with an explicit continuation.
            if used + len(line) + 1 > 5800:
                if not lines:
                    lines.append(line[:5700] + ' [line truncated; inspect a narrower source representation]')
                    shown = 1
                break
            lines.append(line)
            shown += 1
            used += len(line) + 1
        if len('\n'.join(lines)) < len(response) or limit > 120:
            lines.append(f'[bounded read; showing from line {offset}; next offset {offset + shown}; '
                         'locate the relevant symbol before continuing]')
        return '\n'.join(lines) or response
