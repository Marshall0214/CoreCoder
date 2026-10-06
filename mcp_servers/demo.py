"""Exercise the code knowledge server using the official MCP stdio client."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def demonstrate(workspace, query):
    root = Path(__file__).resolve().parent.parent
    parameters = StdioServerParameters(
        command=sys.executable, args=['-m', 'mcp_servers.code_knowledge', '--workspace', str(workspace.resolve())],
        env=dict(os.environ, PYTHONPATH=str(root), PYTHONIOENCODING='utf-8'))
    async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        searched = await session.call_tool('search_code', {'query': query})
        if searched.isError:
            raise RuntimeError(searched.content[0].text)
        result = {'tools': [tool.name for tool in tools.tools], 'search': searched.structuredContent}
        if searched.structuredContent['results']:
            first = searched.structuredContent['results'][0]
            inspected = await session.call_tool('read_code', {
                'path': first['path'], 'start_line': first['start_line'], 'end_line': first['end_line'],
                'expected_hash': first['content_hash']})
            if inspected.isError:
                raise RuntimeError(inspected.content[0].text)
            result['read'] = inspected.structuredContent
        print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--query', default='timeout_seconds')
    args = parser.parse_args()
    asyncio.run(demonstrate(args.workspace, args.query))


if __name__ == '__main__':
    main()
