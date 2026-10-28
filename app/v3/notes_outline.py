"""Concise whole-route Markdown, using the existing single-content contract."""
import re

from .materials import ContextBudgetExceeded

PROMPT_VERSION = 'notes-outline-2'


def outline_request(payload):
    profile=payload['profile']
    branches=profile.get('scope_in') or []
    if not branches or len(branches)>12 or any(not isinstance(b,str) or not b.strip() for b in branches):
        raise ValueError('Notes require every confirmed scope branch')
    headings=[' '.join(branch.splitlines()).strip() for branch in branches]
    heading_size=sum(len(h)+4 for h in headings)
    if heading_size+40*len(headings)>6000:
        raise ContextBudgetExceeded('Scope labels leave insufficient room under the existing notes contract')
    target=min(6000,max(2800,heading_size+100*len(headings)))
    per_section=max(40,min(300,(target-heading_size)//len(headings)))
    data={'learning_goal':profile['goal'],'bounded_goal':profile['bounded_goal'],
          'prior_knowledge':profile.get('prior_knowledge',{}).get('self_reported',[]),
          'target_level':profile.get('target_level','入门'),
          'scope_out':profile.get('scope_out',[]),
          'section_headings':['## '+h for h in headings],
          'recommended_characters_per_section':per_section,
          'recommended_total_characters':heading_size+len(headings)*per_section}
    return data,headings


def validate_outline(notes,headings):
    """Preserve all confirmed branches; no clipping or invented replacements."""
    matches=[];fence=None;position=0
    for line in notes.content.splitlines(keepends=True):
        marker=re.match(r'^ {0,3}(`{3,}|~{3,})',line)
        if marker:
            value=marker.group(1)
            if fence is None:fence=value
            elif value[0]==fence[0] and len(value)>=len(fence):fence=None
        elif fence is None:
            match=re.match(r'^ {0,3}##[ \t]+(.+?)[ \t]*$',line.rstrip('\r\n'))
            if match:matches.append((position,position+len(line),match.group(1).strip()))
        position+=len(line)
    actual=[m[2] for m in matches]
    if actual!=headings:
        missing=[h for h in headings if h not in actual]
        raise ValueError('资料须按section_headings原顺序保留全部二级标题，不得合并或漏章；缺少：'+','.join(missing)[:500])
    for i,match in enumerate(matches):
        body=notes.content[match[1]:matches[i+1][0] if i+1<len(matches) else len(notes.content)]
        if len(re.sub(r'\s','',body))<40:
            raise ValueError(f'第{i+1}节缺少实质教学内容，不能仅列目录')


INSTRUCTION=(
    '整理整条已确认路线的中文Markdown教学依据提纲。只输出原来的单字段JSON：{"content":"Markdown正文"}。'
    'section_headings是程序给出的完整分支目录，按原顺序逐字使用全部二级标题，每个目录项对应一节，不合并或重复生成目录项。'
    '每节用紧凑的一小段说明具体定义和规则/操作步骤，再给一个短例子、一条常见误解和一个可观察练习方向。'
    '例子必须包含理解本节所需的具体数值、关系或规则，不能用“例如相关案例”这类空话。'
    'SQL等代码只保留说明当前规则所需的最短完整合法语句，交代使用的表/列或别名；不要重复整套示例数据。'
    'recommended_characters_per_section和recommended_total_characters按全部字符计算，包含标点、英文和代码，不是汉字数。'
    '按这个篇幅建议写出实质内容；复杂分支可适度多写，必须先保证所有分支都有依据，不得删章或把多章合并来节省篇幅。'
    '后续Tutor会逐节展开，不在这里写长篇教材、多个变式或重复总结；不复述用户档案，不写引言、学习寄语和结语。'
    '简洁不能牺牲正确性：保留规则成立的必要条件、例外与约束；涉及数据库方言、语言版本或实现差异时明确适用环境，不声称普遍成立。'
    '提交前逐节核对例子的结果、符号、单位、关键字拼写与声明的表/列或别名；必要条件必须出现在规则正文，不能只在例子中暗示。'
    '保持独立分支和综合应用的知识范围。资料是教学内容，不负责规定节点数量或强制节点按目录顺序串联。'
    '只整理通用知识，遵守scope_out；不编造外部引用、公司制度、官方背书、实验结果、隐藏答案卷或评分政策。'
    '输出完整合法JSON，正文换行和英文双引号正确转义。只写一次content字段。'
)
