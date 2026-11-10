"""Agent 能力注册表：总控调度与前端快捷按钮的单一事实来源。

每个 Agent 登记自己的适用房间、触发方式（关键词 / 语义示例）、前置数据
（简历、已完成测评等）与产物类型。总控与 LLM 规划器都只允许从本表选择，
新增能力时只需追加一条登记并在执行层补一个分支，不再改动路由规则表。
"""

from dataclasses import dataclass
from typing import Literal

# 房间标识：0=学习室，1=面试间，2=笔记本（笔记本不参与聊天调度）
ROOM_STUDY = 0
ROOM_INTERVIEW = 1

# 默认聊天能力：任何房间可用，未命中任务意图时兜底
CHAT_AGENT = "chat_answer"
QUIZ_AGENT = "quiz_generate_workflow"
DIFFICULTY_AGENT = "difficulty_learner"
INTERVIEW_HOST_AGENT = "interview_host"
INTERVIEW_EVALUATOR_AGENT = "interview_evaluator"
NOTE_AGENT = "note_archiver"

# 前置数据标识：未满足时该能力不参与路由，避免硬调导致 404 / 空转
REQUIRE_RESUME = "resume"
REQUIRE_COMPLETED_INTERVIEW = "completed_interview"
# 笔记来源：本会话已有已完成测评或已完成面试任一即可
REQUIRE_NOTE_SOURCE = "completed_run_or_interview"
REQUIRE_INTERVIEW_ROOM = "session_mode=1"

CapabilityKind = Literal["chat", "workflow", "task"]


@dataclass(frozen=True)
class AgentCapability:
    """一个可被总控调度的能力描述。"""

    name: str
    title: str
    rooms: tuple[int, ...]
    kind: CapabilityKind
    triggers: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    threshold: float = 0.6
    requires: tuple[str, ...] = ()
    returns: str = "text"
    description: str = ""
    enabled: bool = True


# 登记顺序即快筛优先级：先命中哪个就调度哪个
CAPABILITIES: tuple[AgentCapability, ...] = (
    AgentCapability(
        name=CHAT_AGENT,
        title="快速回答",
        rooms=(ROOM_STUDY, ROOM_INTERVIEW),
        kind="chat",
        returns="text",
        description="普通问答、知识点解释与闲聊；未命中具体任务时使用。",
    ),
    AgentCapability(
        name=QUIZ_AGENT,
        title="出题测评",
        rooms=(ROOM_STUDY,),
        kind="workflow",
        triggers=(
            "出题",
            "刷题",
            "题目",
            "试题",
            "练习题",
            "练习",
            "测验",
            "测评",
            "小测",
            "面试题",
            "考考",
        ),
        examples=(
            "帮我出几道练习题",
            "我想刷题巩固一下",
            "给我来一套小测验",
            "测测我对这个知识点的掌握程度",
            "来几道面试题",
        ),
        # 问候与出题示例实测相似度约 0.61，阈值取 0.65 留出余量
        threshold=0.65,
        returns="quiz",
        description="生成结构化题目并在会话中等待作答，提交后再评分。",
    ),
    AgentCapability(
        name=INTERVIEW_HOST_AGENT,
        title="面试主考官",
        rooms=(ROOM_INTERVIEW,),
        kind="workflow",
        triggers=(
            "开始面试",
            "模拟面试",
            "面试开始",
            "准备面试",
            "我准备好了",
            "来场面试",
            "开始模拟",
            "约面试",
            "面试一下吧",
        ),
        examples=(
            "开始一场模拟面试",
            "我准备好了，开始面试吧",
            "帮我准备一下面试",
            "来一场技术面试",
        ),
        threshold=0.68,
        requires=(REQUIRE_INTERVIEW_ROOM, REQUIRE_RESUME),
        returns="interview_prepare",
        description="根据简历与用户资料生成面试背景，确认后进入语音面试。",
    ),
    AgentCapability(
        name=INTERVIEW_EVALUATOR_AGENT,
        title="面试复盘",
        rooms=(ROOM_INTERVIEW,),
        kind="task",
        triggers=(
            "复盘",
            "面试复盘",
            "总结面试",
            "面试总结",
            "点评面试",
            "面试评价",
            "面试表现",
        ),
        examples=(
            "帮我复盘一下刚才的面试",
            "总结一下这次面试的表现",
            "点评我这次模拟面试哪里没答好",
        ),
        threshold=0.66,
        requires=(REQUIRE_INTERVIEW_ROOM, REQUIRE_COMPLETED_INTERVIEW),
        returns="interview_evaluation",
        description="根据最近一次已结束的语音面试生成评分、亮点与改进建议。",
    ),
    AgentCapability(
        name=DIFFICULTY_AGENT,
        title="难点学习",
        rooms=(ROOM_STUDY, ROOM_INTERVIEW),
        kind="task",
        triggers=(
            "知识卡",
            "难点",
            "讲解",
            "详细讲",
            "展开讲",
            "讲一讲",
            "科普",
            "图解",
            "梳理",
            "深入讲",
            "解释一下",
            "是什么原理",
        ),
        examples=(
            "给我讲讲 B+ 树的原理",
            "详细解释一下 MySQL 索引",
            "帮我梳理一下这个难点",
            "用知识卡讲讲 TCP 三次握手",
        ),
        threshold=0.65,
        returns="knowledge_card",
        description="把难点整理成知识卡（配图，可选语音播客）。",
    ),
    AgentCapability(
        name=NOTE_AGENT,
        title="笔记归档",
        rooms=(ROOM_STUDY, ROOM_INTERVIEW),
        kind="task",
        triggers=(
            "笔记",
            "归档",
            "整理成笔记",
            "记录下来",
            "总结成笔记",
            "存成笔记",
        ),
        examples=(
            "把刚才的测评整理成笔记",
            "帮我把这轮内容总结成笔记",
            "归档一下错题与薄弱点",
        ),
        threshold=0.66,
        requires=(REQUIRE_NOTE_SOURCE,),
        returns="note",
        description="把当前会话最近一次已完成的测评或模拟面试整理成可复习的 Markdown 笔记。",
    ),
)

REGISTRY: dict[str, AgentCapability] = {
    capability.name: capability for capability in CAPABILITIES
}
PLANNABLE_CAPABILITIES: tuple[AgentCapability, ...] = tuple(
    capability
    for capability in CAPABILITIES
    if capability.enabled and capability.kind != "chat"
)


def get_capability(name: str | None) -> AgentCapability | None:
    """按名称取能力；未登记或未启用返回 None。"""
    if not name:
        return None
    capability = REGISTRY.get(name)
    if capability is None or not capability.enabled:
        return None
    return capability


def capabilities_for_room(session_mode: int) -> tuple[AgentCapability, ...]:
    """返回指定房间可用且已启用的任务能力（不含默认聊天）。"""
    return tuple(
        capability
        for capability in PLANNABLE_CAPABILITIES
        if session_mode in capability.rooms
    )


def is_room_allowed(capability: AgentCapability, session_mode: int) -> bool:
    """能力是否允许在该房间使用。"""
    return capability.enabled and session_mode in capability.rooms


def public_capabilities(session_mode: int | None = None) -> list[dict]:
    """下发给前端的能力列表；不传房间时返回全部。"""
    rows = [
        capability
        for capability in CAPABILITIES
        if capability.enabled
        and (session_mode is None or session_mode in capability.rooms)
    ]
    return [
        {
            "name": capability.name,
            "title": capability.title,
            "kind": capability.kind,
            "requires": list(capability.requires),
            "returns": capability.returns,
            "description": capability.description,
        }
        for capability in rows
    ]
