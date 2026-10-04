"""Evaluate the existing direct LLMs; never invokes an agent or sends Telegram posts.

python scripts/maintenance/evaluate_translation.py --live --limit 30
Without --live, validate fixtures offline. Reports contain no credentials.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def evaluate(limit=30, live=False):
    import translate
    import config
    import translation_quality
    samples = json.loads((ROOT / 'evaluation/translation_golden.json').read_text(encoding='utf-8'))['entries'][:limit]
    if not live:
        return {'samples': len(samples), 'reference_issues': {
            s['id']: translation_quality.check(s, {'body': s['reference']}, config.GLOSSARY)
            for s in samples}}
    deployments, _, _ = translate._deployments()
    def run(task):
        dep, sample = task
        start = time.monotonic()
        result = {'model': dep['model_name'], 'id': sample['id']}
        try:
            params = dict(dep['litellm_params'], timeout=25, max_retries=0)
            resp = translate.litellm.completion(messages=translate._build_messages(sample),
                                              temperature=0, max_tokens=translate._output_budget(sample), **params)
            tr = translate._extract_json(translate._msg_text(resp))
            result['valid'] = translate._valid_result(tr)
            result['issues'] = translation_quality.check(sample, tr, config.GLOSSARY) if result['valid'] else ['invalid output']
            result['translation'] = tr if result['valid'] else None
        except Exception as exc:
            result.update(valid=False, issues=['provider unavailable'], error_type=type(exc).__name__)
        result['seconds'] = round(time.monotonic() - start, 2)
        return result
    def run_model(dep):
        records, consecutive_unavailable = [], 0
        for sample in samples:
            result = run((dep, sample))
            records.append(result)
            consecutive_unavailable = consecutive_unavailable + 1 if result.get('error_type') else 0
            if consecutive_unavailable >= 3:
                break  # Avoid hammering an unavailable free endpoint for all thirty samples.
        return records
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = [r for batch in pool.map(run_model, deployments) for r in batch]
    ranks = []
    for dep in deployments:
        rows = [r for r in records if r['model'] == dep['model_name']]
        ranks.append({'model': dep['model_name'], 'samples': len(rows),
                      'valid': sum(r['valid'] for r in rows),
                      'facts_pass': sum(r['valid'] and not r['issues'] for r in rows),
                      'mean_seconds': round(sum(r['seconds'] for r in rows) / max(1, len(rows)), 2)})
    ranks.sort(key=lambda r: (-r['facts_pass'], -r['valid'], r['mean_seconds']))
    return {'samples': len(samples), 'ranking': ranks, 'records': records,
            'note': 'Automatic source-fidelity ranking; human fluency review required. Provider configuration is not rewritten.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--limit', type=int, default=30)
    args = parser.parse_args()
    result = evaluate(args.limit, args.live)
    out = ROOT / 'evaluation/results/translation-evaluation.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'records'}, ensure_ascii=True))
