"""Run additive contracts in four independent module environments; no hardware."""
import argparse
import json
from pathlib import Path
from contract_harness import ROOT, run_stage, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT/'out/approach-tactile-contracts')
    args = parser.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    report = {'status': 'RUNNING'}
    write_json(out/'result.json', report)
    try:
        worker = ROOT/'integration/contracts/approach_tactile_stage.py'
        geometry = json.loads((ROOT/'interfaces/application/approach/geometry-v1.json').read_text())
        tactile = json.loads((ROOT/'interfaces/application/tactile/cases.json').read_text())
        producer = run_stage('vision', geometry, out, worker)
        consumer = run_stage('action', producer['observed'], out, worker)
        behavior = run_stage('behavior', tactile, out, worker)
        emotion = run_stage('emotion', tactile, out, worker)
        responses = [producer, consumer, behavior, emotion]
        assert len({r['provenance']['pid'] for r in responses}) == 4
        report = {'status': 'PASS', 'skipped': 0, 'geometry_scenarios': 1, 'tactile_scenarios': 4,
                  'responses': responses, 'scope': 'Real module production/consumption; fixture observations; no devices or DDS'}
    except Exception as exc:
        report = {'status': 'FAIL', 'error': str(exc)}
    write_json(out/'result.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
