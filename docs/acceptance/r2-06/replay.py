"""Reuse the pinned R2-03 replay, with a separate R2-06 engineering output and isolated DB."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
script = (ROOT / "docs/acceptance/r2-03/compare-frozen.py").read_text()
assert script.count('unspun_r2_detail_tests_20261020') == 1
script = script.replace('unspun_r2_detail_tests_20261020', 'unspun_r206_replay_20261020')
script = script.replace('r2-candidate-comparison-v3', 'r2-06-engineering-replay-v1')
script = script.replace('docs/evaluations/r2/candidate-comparison-v3.json', 'docs/acceptance/r2-06/frozen-replay.json')
script = script.replace('    tx.rollback()', '''
    from unspun.core.member_recall import current_input, vector_input
    from unspun.core.content import fingerprint
    from unspun.core.tasks import PipelineTask
    from unspun.pipeline.member_processing import enqueue_member_processing
    from sqlalchemy import func, select
    version_keys = {}
    count_before = session.scalar(select(func.count()).select_from(PipelineTask))
    for item in after:
        snapshot = current_input(session, item.article.id, sources, at)
        version_keys[str(item.article.id)] = fingerprint(vector_input(snapshot))
        assert enqueue_member_processing(session, item.article.id, sources=sources, now=at) is None
    assert session.scalar(select(func.count()).select_from(PipelineTask)) == count_before
    report.update(vector_version_keys=version_keys, default_closed_no_new_tasks=True,
                  real_membership_precision=None, real_membership_coverage=None,
                  semantic_quality_status="unmeasured; no model evaluation",
                  engineering_replay_only=True)
    tx.rollback()''')
exec(compile(script, str(ROOT / "docs/acceptance/r2-03/compare-frozen.py"), "exec"))
