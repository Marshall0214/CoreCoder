import asyncio
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

pytest.importorskip('mcp')

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp.exceptions import ToolError

from corecoder.agent import Agent
from corecoder.demo import ScriptedLLM
from corecoder.llm import LLMResponse, ToolCall
from corecoder.mcp import MCPClient, MCPError
from corecoder.tools.search_code import SearchCodeTool
from mcp_servers.code_knowledge import CodeKnowledge, create_server

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def corpus(tmp_path):
    (tmp_path / 'transport.py').write_text('def timeout_seconds(milliseconds):\n    return milliseconds / 1000\n', encoding='utf-8')
    (tmp_path / 'contract.md').write_text('# Timeout\nConvert milliseconds to seconds.\n', encoding='utf-8')
    (tmp_path / '中文.md').write_text('超时需要单位转换。\n', encoding='utf-8')
    (tmp_path / '.env').write_text('PRIVATE_SECRET=not-evidence', encoding='utf-8')
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 'hidden.py').write_text('PRIVATE_EXPECTED_ANSWER=42', encoding='utf-8')
    return tmp_path


def params(corpus):
    return StdioServerParameters(command=sys.executable,
                                 args=['-m', 'mcp_servers.code_knowledge', '--workspace', str(corpus)],
                                 env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING='utf-8'))


def core_client(corpus):
    config = params(corpus)
    return MCPClient('knowledge', config.command, config.args, config.env)


def test_official_stdio_client_structured_output_pagination_and_refresh(corpus):
    async def run():
        async with stdio_client(params(corpus)) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            specs = (await session.list_tools()).tools
            assert {t.name for t in specs} == {'search_code', 'list_code_files', 'read_code'}
            assert all(t.outputSchema and t.annotations.readOnlyHint for t in specs)
            paths, cursor = [], None
            for _ in range(4):
                result = await session.call_tool('list_code_files', {'page_size': 1, 'cursor': cursor})
                assert not result.isError
                assert json.loads(result.content[0].text) == result.structuredContent
                paths.extend(f['path'] for f in result.structuredContent['files'])
                cursor = result.structuredContent['next_cursor']
                if cursor is None:
                    break
            assert paths == ['contract.md', 'transport.py', '中文.md']
            result = await session.call_tool('search_code', {'query': 'timeout_seconds'})
            evidence = result.structuredContent
            local = json.loads(SearchCodeTool(corpus).execute('timeout_seconds'))
            assert evidence == local
            first = next(item for item in evidence['results'] if item['path'] == 'transport.py')
            result = await session.call_tool('read_code', {'path': first['path'], 'expected_hash': first['content_hash']})
            assert not result.isError and 'milliseconds / 1000' in result.structuredContent['content']
            (corpus / 'transport.py').write_text('def timeout_seconds(milliseconds):\n    return milliseconds / 2000\n', encoding='utf-8')
            stale = await session.call_tool('read_code', {'path': first['path'], 'expected_hash': first['content_hash']})
            assert stale.isError and 'File changed' in stale.content[0].text
            changed = await session.call_tool('search_code', {'query': 'timeout_seconds'})
            assert changed.structuredContent['index_hash'] != evidence['index_hash']
            assert any('/ 2000' in item['content'] for item in changed.structuredContent['results'])
            missing = await session.call_tool('search_code', {'query': 'nonexistent_unfindable_identifier'})
            assert missing.structuredContent['results'] == []
            bad = await session.call_tool('read_code', {'path': '../outside.py'})
            assert bad.isError
            invalid = await session.call_tool('search_code', {'query': 'timeout', 'top_k': True})
            assert invalid.isError
            assert not (await session.call_tool('search_code', {'query': 'timeout'})).isError
    asyncio.run(run())


def test_corecoder_client_parallel_tools_errors_and_agent_loop(corpus):
    client = core_client(corpus)
    try:
        tools = {t.name: t for t in client.tools}
        assert 'mcp__knowledge__search_code' in tools
        with ThreadPoolExecutor(max_workers=3) as pool:
            answers = list(pool.map(lambda q: json.loads(client.call_tool('search_code', {'query': q})),
                                    ['timeout_seconds', 'Convert', '超时']))
        assert [a['query'] for a in answers] == ['timeout_seconds', 'Convert', '超时']
        assert all(a['results'] for a in answers)
        with pytest.raises(MCPError, match='allowed'):
            client.call_tool('read_code', {'path': '.env'})
        agent = Agent(llm=ScriptedLLM([
            LLMResponse(tool_calls=[ToolCall(id='search-1', name='mcp__knowledge__search_code',
                                             arguments={'query': 'timeout_seconds'})]),
            LLMResponse(content='done'),
        ]), tools=list(tools.values()))
        assert agent.chat('Locate the timeout conversion') == 'done'
        messages = [m for m in agent.messages if m['role'] == 'tool']
        assert 'transport.py' in messages[0]['content']
    finally:
        client.close()
        assert client._proc.poll() is not None


def test_cursor_cannot_be_reused_after_changes_or_parameter_changes(corpus):
    client = core_client(corpus)
    try:
        page = json.loads(client.call_tool('list_code_files', {'page_size': 1}))
        cursor = page['next_cursor']
        for arguments in [{'page_size': 2, 'cursor': cursor}, {'page_size': 1, 'cursor': cursor + 'x'}]:
            with pytest.raises(MCPError, match='cursor'):
                client.call_tool('list_code_files', arguments)
        (corpus / 'extra.py').write_text('extra = True\n', encoding='utf-8')
        with pytest.raises(MCPError, match='stale cursor'):
            client.call_tool('list_code_files', {'page_size': 1, 'cursor': cursor})
        assert len(json.loads(client.call_tool('list_code_files', {}))['files']) == 4
    finally:
        client.close()


@pytest.mark.parametrize('path', ['../escape.py', '/absolute.py', 'C:/secret.py', 'tests/hidden.py',
                                 '.env', 'transport.py/../contract.md', 'transport\\file.py'])
def test_reads_reject_unlisted_or_unsafe_paths(corpus, path):
    with pytest.raises(ValueError):
        CodeKnowledge(corpus).read(path, 1, 80, None)


def test_evidence_and_read_limits(corpus):
    (corpus / 'long.py').write_text('timeout = "' + 'a' * 10000 + '"\n', encoding='utf-8')
    knowledge = CodeKnowledge(corpus)
    result = knowledge.search('timeout', 5)
    assert result.evidence_chars <= 6000
    code = knowledge.read('long.py', 1, 1, None)
    assert code.truncated and len(code.content) == 6000 and code.end_line == 1
    assert code.content_hash == hashlib.sha256((corpus / 'long.py').read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='200 lines'):
        knowledge.read('long.py', 1, 201, None)
    with pytest.raises(ValueError, match='outside'):
        knowledge.read('long.py', 2, 3, None)


def test_server_timeout_is_a_tool_error_and_next_call_works(corpus, monkeypatch):
    server = create_server(corpus, timeout=0.02)
    original = CodeKnowledge.search

    def slow(self, query, top_k):
        time.sleep(0.1)
        return original(self, query, top_k)

    async def run():
        with monkeypatch.context() as patch:
            patch.setattr(CodeKnowledge, 'search', slow)
            with pytest.raises(ToolError, match='timed out'):
                await server.call_tool('search_code', {'query': 'timeout'})
        await asyncio.sleep(0.12)
        assert await server.call_tool('search_code', {'query': 'timeout'})
    asyncio.run(run())


def test_corpus_limit_is_exposed_as_tool_error(corpus):
    (corpus / 'oversize.py').write_bytes(b'x' * 1_000_001)
    client = core_client(corpus)
    try:
        with pytest.raises(MCPError, match='corpus exceeds'):
            client.call_tool('search_code', {'query': 'timeout'})
    finally:
        client.close()


def test_symlink_escape_is_not_listed_or_read(corpus, tmp_path_factory):
    outside = tmp_path_factory.mktemp('mcp-outside') / 'secret.py'
    outside.write_text('PRIVATE_SECRET = 42', encoding='utf-8')
    try:
        (corpus / 'link.py').symlink_to(outside)
    except OSError:
        pytest.skip('Creating symlinks is not permitted on this host')
    knowledge = CodeKnowledge(corpus)
    assert 'link.py' not in [f.path for f in knowledge.list_files(100, None).files]
    with pytest.raises(ValueError):
        knowledge.read('link.py', 1, 80, None)
