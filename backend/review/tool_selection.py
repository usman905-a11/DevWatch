"""Model-facing tool relevance; execution authorization remains separate."""
from pathlib import PurePosixPath

from backend.review.contracts import AgentId, SPECIALISTS
from backend.review.intelligence import SUPPORTED_EXTENSIONS

PARSER_TOOLS = frozenset({'parse_ast', 'symbol_lookup', 'call_graph'})


def select(catalogue, state, context):
    task, private = state['task'], state['private_state']
    phase = state.get('phase', 'investigation')
    if phase == 'synthesis':
        return 'synthesis', []
    names = {tool['name'] for tool in catalogue}
    pages = context.get('evidence', []) if isinstance(context, dict) else []
    if not (private.evidence_refs or task.evidence_refs or pages):
        names.discard('read_evidence')
    stage = phase
    if task.agent_id in SPECIALISTS:
        source_available = (
            any(receipt.source_file in task.files for receipt in private.evidence_progress.values())
            or any(isinstance(page, dict) and page.get('source_file') in task.files for page in pages)
        )
        stage = 'analysis' if source_available else 'source'
        if not source_available:
            names.intersection_update({'read_file', 'read_evidence'})
        elif not any(PurePosixPath(path).suffix.lower() in SUPPORTED_EXTENSIONS for path in task.files):
            # Avoid advertising AST tools when none of the assigned files have a supported parser.
            names.difference_update(PARSER_TOOLS)
    elif (
        task.agent_id == AgentId.PLANNER
        and isinstance(context, dict)
        and 'intelligence' in context
        and not context.get('omitted_intelligence_count')
        and not context.get('omitted_changes_count')
    ):
        names.discard('repo_map')
    return stage, [tool for tool in catalogue if tool['name'] in names]
