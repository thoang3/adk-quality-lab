import asyncio, sys, logging
logging.basicConfig(level=logging.WARNING)
sys.path.insert(0, '.')

from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types
from adk_quality_lab_wiring.playground import agent_variants_minimal_cash_markdown_table as m
from adk_quality_lab_wiring.playground.root_agent_cash_query import _load_initial_state

async def run():
    runner = InMemoryRunner(agent=m.root_agent_minimal_cash, app_name='test')
    initial_state = _load_initial_state()
    session = await runner.session_service.create_session(
        app_name='test', user_id='u1', state=initial_state,
    )
    msg = genai_types.Content(role='user', parts=[genai_types.Part(text='Find economy cash flights from SFO to NRT on 2026-07-23')])
    async for event in runner.run_async(user_id='u1', session_id=session.id, new_message=msg):
        author = getattr(event, 'author', '?')
        if event.content and event.content.parts:
            for p in event.content.parts:
                if hasattr(p, 'function_call') and p.function_call:
                    print(f'[CALL] {author} -> {p.function_call.name}({dict(p.function_call.args)})')
                if hasattr(p, 'function_response') and p.function_response:
                    r = p.function_response.response
                    print(f'[RESP] {p.function_response.name} -> {str(r)[:300]}')
                if p.text:
                    print(f'[TEXT] {author}: {p.text[:300]}')

asyncio.run(run())
