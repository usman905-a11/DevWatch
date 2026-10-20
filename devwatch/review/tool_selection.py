"""Model-facing tool relevance; execution authorization remains separate."""
from devwatch.review.contracts import SPECIALISTS


def select(catalogue, state, context):
    task,private=state['task'],state['private_state']
    phase=state.get('phase','investigation')
    if phase=='synthesis':
        return 'synthesis',[]
    names={tool['name'] for tool in catalogue}
    pages=context.get('evidence',[]) if isinstance(context,dict) else []
    if not (private.evidence_refs or task.evidence_refs or pages):
        names.discard('read_evidence')
    stage=phase
    if task.agent_id in SPECIALISTS:
        source_available=(any(receipt.source_file in task.files for receipt in private.evidence_progress.values())
            or any(isinstance(page,dict) and page.get('source_file') in task.files for page in pages))
        stage='analysis' if source_available else 'source'
        if not source_available:
            names.intersection_update({'read_source','read_evidence'})
    return stage,[tool for tool in catalogue if tool['name'] in names]
