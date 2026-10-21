"""Day 9 foundation demo: no LLM and no V2 business/Graph writes."""
import argparse
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.v3.capabilities import check_capabilities, list_capabilities
from app.v3.config import SERVER_LIMITS
from app.v3.contracts import LearningProfile, STATE_ACTIONS, PublicProjectView
from app.v3.presets import profile_from_preset
from app.v3.repository import V3Repository
from app.v3.storage import V3Paths, initialize_storage


def demo(paths):
    initialize_storage(paths)
    rows=[]
    with V3Repository(paths) as repo:
        for preset in ('python','mathematics','english','generic'):
            profile=profile_from_preset(preset,subject_label='未注册的文字学科' if preset=='generic' else None)
            request=uuid5(NAMESPACE_URL,'skilltree-v3-day9:'+preset)
            project=repo.create_project(request,profile)
            repeated=repo.create_project(request,profile)
            assert project['id']==repeated['id'] and project['thread_id']==project['id']
            check=check_capabilities(profile,has_material=False)
            rows.append({'preset':preset,'subject_label':profile.subject_label,'project_id':project['id'],
                         'thread_id':project['thread_id'],'pending_input_id':project['pending_input_id'],
                         'capability_check':check.model_dump(),'progress':repo.get_progress(project['id'])})
        before=paths.learning.read_bytes()
        changes_before_queries=repo.conn.total_changes
        for row in rows:
            p=repo.get_project(row['project_id'])
            PublicProjectView(project_id=p['id'],thread_id=p['thread_id'],profile=LearningProfile.model_validate(p['profile']),
                              draft_revision=p['draft_revision'],pending_input_id=p['pending_input_id'])
        assert paths.learning.read_bytes()==before and repo.conn.total_changes==changes_before_queries
    return {'purpose':'Day9基础契约/真实SQLite演示；没有调用模型或完成V3教学闭环',
            'databases':{'business':str(paths.learning),'checkpoint':str(paths.checkpoints)},
            'profiles':rows,'limits':SERVER_LIMITS.model_dump(),
            'capabilities':list_capabilities(),
            'state_actions_upper_bound':{state:sorted(actions) for state,actions in STATE_ACTIONS.items()},
            'note':'动作表为后续实现契约，Day9未开放V3网页动作；完整主题所需文字/数值评价器尚未接好。'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,default=V3Paths().root)
    parser.add_argument('--output',type=Path,default=Path('work/day9/v3-foundation-demo.json'))
    parser.add_argument('--init-only',action='store_true')
    args=parser.parse_args()
    paths=initialize_storage(V3Paths(args.data_dir))
    if args.init_only:
        print('V3独立业务库与Checkpoint已初始化。')
        return
    report=demo(paths)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('四个开放主题档案已保存；重复创建仍是同一个项目。')
    for row in report['profiles']:
        print(row['subject_label']+': '+row['capability_check']['status']+'；正式测评许可='+str(row['capability_check']['formal_assessment_allowed']))
    print('演示报告：'+str(args.output))


if __name__=='__main__':
    main()
