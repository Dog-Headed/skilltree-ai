"""Exercise the same public JSON endpoints as the browser, with saved evidence."""
import argparse
import json
from pathlib import Path
from uuid import uuid4

import httpx


def summary(view):
    return {k: view.get(k) for k in ('project_id', 'page_state', 'allowed_actions', 'error_type', 'retry_token', 'learning_basis', 'current_node_id', 'completed_node_ids', 'guard', 'feedback', 'quiz', 'tutor', 'nodes')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:18766')
    parser.add_argument('--evidence', default='work/deployment-smoke')
    parser.add_argument('action')
    parser.add_argument('--payload', default='{}')
    args = parser.parse_args()
    evidence = Path(args.evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    state = evidence / 'latest.json'
    old = json.loads(state.read_text(encoding='utf-8')) if state.exists() else None
    extra = json.loads(args.payload)
    with httpx.Client(base_url=args.url, timeout=600, trust_env=False) as client:
        if args.action == 'create':
            response = client.post('/projects', json={'request_id': str(uuid4()), 'intent': {
                'goal': '学习Python的if else条件判断，只学整数大小比较与分支选择，规划三个有前置依赖的小节点，用文字解释和选择题测评，不执行代码。',
                'prior_knowledge': '知道整数和变量，会阅读简单Python语句', 'time_budget_minutes': 90}, **extra})
        elif args.action == 'get':
            response = client.get('/projects/' + old['project_id'])
        elif args.action == 'begin':
            response = client.post('/projects/' + old['project_id'] + '/begin', json={'request_id': str(uuid4())})
        elif args.action == 'upload':
            response = client.post('/projects/' + old['project_id'] + '/sources', json={'request_id': str(uuid4()), **extra})
        elif args.action == 'retry':
            response = client.post('/projects/' + old['project_id'] + '/retry', json={'request_id': str(uuid4()), 'retry_token': old['retry_token'], **extra})
        else:
            payload = {'request_id': str(uuid4()), 'pending_input_id': old['pending_input_id'],
                       'draft_revision': old['draft_revision'], 'action': args.action, **extra}
            if args.action == 'submit_answer':
                payload['assessment_id'] = old['assessment_id']
            response = client.post('/projects/' + old['project_id'] + '/resume', json=payload)
    print('HTTP', response.status_code)
    value = response.json()
    (evidence / (str(uuid4()) + '-' + args.action + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    if response.is_success and value.get('project_id'):
        state.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(summary(value), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    response.raise_for_status()
