import json
import math
import sqlite3

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from app.models.schemas import (
    AssessmentEvaluation, AssessmentQuiz, SkillNode,
    validate_and_score_evaluation, validate_quiz_against_node,
)
PROJECT_ROOT = (
    Path(__file__).resolve().parents[2]
)

DEFAULT_DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "learning.sqlite"
)

def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def dump_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
    )


def load_json(value: str | None) -> Any:
    if value is None:
        return None

    return json.loads(value)


def repository_for_state(state: dict[str, Any]):
    return LearningRepository(state.get("learning_db_path") or DEFAULT_DB_PATH)


def get_assessment_for_state(repo, state: dict[str, Any]) -> dict[str, Any]:
    assessment = repo.get_assessment(state["assessment_id"])
    if assessment is None:
        raise ValueError("数据库中找不到当前测验")
    if (
        assessment["project_id"] != state["project_id"]
        or assessment["node_id"] != state["current_node_id"]
    ):
        raise ValueError("当前测验与项目 / 节点不匹配")
    return assessment


class LearningRepository:
    def __init__(
        self,
        db_path: str | Path,
    ):
        self.db_path = Path(db_path).resolve()

        self.db_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.conn = sqlite3.connect(
            self.db_path
        )

        self.conn.row_factory = sqlite3.Row

        # SQLite 外键约束需要每个连接显式开启
        self.conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        self.init_schema()


    def init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS learning_projects (
                id TEXT PRIMARY KEY,
                goal TEXT NOT NULL,
                created_at TEXT NOT NULL
            );


            CREATE TABLE IF NOT EXISTS knowledge_nodes (
                project_id TEXT NOT NULL,
                id TEXT NOT NULL,

                title TEXT NOT NULL,
                description TEXT NOT NULL,

                objectives_json TEXT NOT NULL,
                prerequisite_ids_json TEXT NOT NULL,

                difficulty TEXT NOT NULL,
                estimated_minutes INTEGER NOT NULL,
                sort_order INTEGER NOT NULL,

                PRIMARY KEY (
                    project_id,
                    id
                ),

                FOREIGN KEY (
                    project_id
                )
                REFERENCES learning_projects(id)
                ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS learning_progress (
                project_id TEXT NOT NULL,
                node_id TEXT NOT NULL,

                started_at TEXT,
                completed_at TEXT,
                completion_assessment_id TEXT,

                PRIMARY KEY (
                    project_id,
                    node_id
                ),

                FOREIGN KEY (
                    project_id,
                    node_id
                )
                REFERENCES knowledge_nodes(
                    project_id,
                    id
                )
                ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS assessments (
                id TEXT PRIMARY KEY,

                project_id TEXT NOT NULL,
                node_id TEXT NOT NULL,

                round_no INTEGER NOT NULL,

                quiz_json TEXT,
                answers_json TEXT,
                evaluation_json TEXT,
                diagnosis_json TEXT,

                status TEXT NOT NULL
                    CHECK (
                        status IN (
                            'prepared',
                            'awaiting_answer',
                            'graded',
                            'abandoned'
                        )
                    ),

                created_at TEXT NOT NULL,

                FOREIGN KEY (
                    project_id,
                    node_id
                )
                REFERENCES knowledge_nodes(
                    project_id,
                    id
                )
                ON DELETE CASCADE
            );


            CREATE INDEX IF NOT EXISTS
            idx_assessments_project_node
            ON assessments(
                project_id,
                node_id,
                round_no
            );
            """
        )

        self.conn.commit()

    def create_project_with_tree(
        self,
        *,
        project_id: str,
        goal: str,
        tree: list[dict[str, Any]],
    ) -> None:

        now = utc_now()

        # 一个 with = 一个事务
        # 全部成功 -> commit
        # 中途任何一步失败 -> rollback
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO learning_projects (
                    id,
                    goal,
                    created_at
                )
                VALUES (?, ?, ?)
                """,
                (
                    project_id,
                    goal,
                    now,
                ),
            )

            for sort_order, node in enumerate(
                tree
            ):
                self.conn.execute(
                    """
                    INSERT INTO knowledge_nodes (
                        project_id,
                        id,
                        title,
                        description,
                        objectives_json,
                        prerequisite_ids_json,
                        difficulty,
                        estimated_minutes,
                        sort_order
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        project_id,
                        node["id"],
                        node["title"],
                        node["description"],
                        dump_json(
                            node["objectives"]
                        ),
                        dump_json(
                            node.get(
                                "prerequisite_ids",
                                [],
                            )
                        ),
                        node["difficulty"],
                        node[
                            "estimated_minutes"
                        ],
                        sort_order,
                    ),
                )

    def get_project(
        self,
        project_id: str,
    ) -> dict[str, Any] | None:

        row = self.conn.execute(
            """
            SELECT
                id,
                goal,
                created_at

            FROM learning_projects

            WHERE id = ?
            """,
            (
                project_id,
            ),
        ).fetchone()

        if row is None:
            return None

        return dict(row)

    def list_projects(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, goal, created_at FROM learning_projects ORDER BY created_at DESC, id DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def create_project_if_absent(self, *, project_id: str, goal: str, tree: list[dict]) -> list[dict]:
        """规划已落库但 Checkpoint 落后时，复用原项目和技能树。"""
        project = self.get_project(project_id)
        if project is None:
            self.create_project_with_tree(project_id=project_id, goal=goal, tree=tree)
        elif project["goal"] != goal:
            raise ValueError("同一 project_id 已有不同的学习目标，请使用新的项目 ID。")
        return self.get_tree(project_id)

    def next_assessment_round(self, *, project_id: str, node_id: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(round_no), 0) + 1 AS next_round FROM assessments "
            "WHERE project_id = ? AND node_id = ?",
            (project_id, node_id),
        ).fetchone()
        return int(row["next_round"])

    def get_tree(
        self,
        project_id: str,
    ) -> list[dict[str, Any]]:

        rows = self.conn.execute(
            """
            SELECT
                id,
                title,
                description,
                objectives_json,
                prerequisite_ids_json,
                difficulty,
                estimated_minutes,
                sort_order

            FROM knowledge_nodes

            WHERE project_id = ?

            ORDER BY sort_order ASC
            """,
            (
                project_id,
            ),
        ).fetchall()

        tree = []

        for row in rows:
            tree.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "description": (
                        row["description"]
                    ),
                    "objectives": load_json(
                        row["objectives_json"]
                    ),
                    "prerequisite_ids": load_json(
                        row[
                            "prerequisite_ids_json"
                        ]
                    ),
                    "difficulty": (
                        row["difficulty"]
                    ),
                    "estimated_minutes": (
                        row[
                            "estimated_minutes"
                        ]
                    ),
                }
            )

        return tree

    def close(self) -> None:
        self.conn.close()


    def __enter__(self):
        return self


    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        self.close()

    def create_prepared_assessment(
            self,
            *,
            assessment_id: str,
            project_id: str,
            node_id: str,
            round_no: int,
    ) -> dict[str, Any]:
        """
        创建一轮 prepared 测验。

        同一个 assessment_id 重复调用时：
        - 若记录一致，直接复用
        - 若身份信息冲突，报错
        """

        existing = self.get_assessment(
            assessment_id
        )

        if existing is not None:
            if (
                    existing["project_id"] != project_id
                    or existing["node_id"] != node_id
                    or existing["round_no"] != round_no
            ):
                raise ValueError(
                    "assessment_id 已存在，"
                    "但项目、节点或轮次不一致"
                )

            return existing

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO assessments (
                    id,
                    project_id,
                    node_id,
                    round_no,
                    quiz_json,
                    answers_json,
                    evaluation_json,
                    diagnosis_json,
                    status,
                    created_at
                )
                VALUES (
                    ?, ?, ?, ?,
                    NULL, NULL, NULL, NULL,
                    'prepared',
                    ?
                )
                """,
                (
                    assessment_id,
                    project_id,
                    node_id,
                    round_no,
                    utc_now(),
                ),
            )

        result = self.get_assessment(
            assessment_id
        )

        assert result is not None

        return result

    def get_assessment(
            self,
            assessment_id: str,
    ) -> dict[str, Any] | None:

        row = self.conn.execute(
            """
            SELECT
                id,
                project_id,
                node_id,
                round_no,
                quiz_json,
                answers_json,
                evaluation_json,
                diagnosis_json,
                status,
                created_at

            FROM assessments

            WHERE id = ?
            """,
            (
                assessment_id,
            ),
        ).fetchone()

        if row is None:
            return None

        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "node_id": row["node_id"],
            "round_no": row["round_no"],

            "quiz": load_json(
                row["quiz_json"]
            ),

            "answers": load_json(
                row["answers_json"]
            ),

            "evaluation": load_json(
                row["evaluation_json"]
            ),

            "diagnosis": load_json(
                row["diagnosis_json"]
            ),

            "status": row["status"],
            "created_at": row["created_at"],
        }

    def save_quiz_if_absent(
            self,
            *,
            assessment_id: str,
            quiz: dict[str, Any],
    ) -> dict[str, Any]:
        """
        固定本轮试卷。

        如果 quiz 已经存在：
        不覆盖，不重新保存，直接返回原试卷。
        """

        assessment = self.get_assessment(
            assessment_id
        )

        if assessment is None:
            raise ValueError(
                f"测验不存在：{assessment_id}"
            )

        # 已经固定过试卷
        if assessment["quiz"] is not None:
            return assessment

        if assessment["status"] != "prepared":
            raise ValueError(
                "只有 prepared 状态"
                "可以首次保存试卷"
            )

        with self.conn:
            self.conn.execute(
                """
                UPDATE assessments

                SET
                    quiz_json = ?,
                    status = 'awaiting_answer'

                WHERE id = ?
                  AND quiz_json IS NULL
                  AND status = 'prepared'
                """,
                (
                    dump_json(quiz),
                    assessment_id,
                ),
            )

        result = self.get_assessment(
            assessment_id
        )

        assert result is not None

        return result

    def save_answers_if_absent(
            self,
            *,
            assessment_id: str,
            answers: dict[str, Any],
    ) -> dict[str, Any]:
        """
        保存本轮答案。

        同一个 assessment_id：
        - 第一次提交 -> 保存
        - 完全相同的重复提交 -> 复用
        - 不同答案再次提交 -> 拒绝
        """

        assessment = self.get_assessment(
            assessment_id
        )

        if assessment is None:
            raise ValueError(
                f"测验不存在：{assessment_id}"
            )

        if assessment["status"] == "abandoned":
            raise ValueError(
                "已放弃的测验不能提交答案"
            )

        if assessment["quiz"] is None:
            raise ValueError(
                "测验尚未固定试卷"
            )

        existing_answers = assessment[
            "answers"
        ]

        # 已经提交过
        if existing_answers is not None:
            if existing_answers != answers:
                raise ValueError(
                    "本轮答案已经固定，"
                    "不能使用不同答案覆盖"
                )

            return assessment

        if assessment["status"] != "awaiting_answer":
            raise ValueError(
                "当前测验状态不允许提交答案："
                f"{assessment['status']}"
            )

        with self.conn:
            self.conn.execute(
                """
                UPDATE assessments

                SET answers_json = ?

                WHERE id = ?
                  AND answers_json IS NULL
                """,
                (
                    dump_json(answers),
                    assessment_id,
                ),
            )

        result = self.get_assessment(
            assessment_id
        )

        assert result is not None

        if result["answers"] != answers:
            raise ValueError("本轮答案已经固定，不能使用不同答案覆盖")
        return result

    def save_evaluation_if_absent(
            self,
            *,
            assessment_id: str,
            evaluation: dict[str, Any],
    ) -> dict[str, Any]:
        """
        保存评分。

        evaluation 一旦存在，
        后续重试直接复用原评分。
        """

        assessment = self.get_assessment(
            assessment_id
        )

        if assessment is None:
            raise ValueError(
                f"测验不存在：{assessment_id}"
            )

        if assessment["evaluation"] is not None:
            return assessment

        if assessment["answers"] is None:
            raise ValueError(
                "尚未保存答案，不能评分"
            )

        if assessment["quiz"] is None:
            raise ValueError(
                "尚未保存试卷，不能评分"
            )

        if assessment["status"] != "awaiting_answer":
            raise ValueError(
                "当前状态不允许首次保存评分："
                f"{assessment['status']}"
            )

        with self.conn:
            self.conn.execute(
                """
                UPDATE assessments

                SET
                    evaluation_json = ?,
                    status = 'graded'

                WHERE id = ?
                  AND evaluation_json IS NULL
                """,
                (
                    dump_json(evaluation),
                    assessment_id,
                ),
            )

        result = self.get_assessment(
            assessment_id
        )

        assert result is not None

        return result

    def save_diagnosis_if_absent(
            self,
            *,
            assessment_id: str,
            diagnosis: dict[str, Any],
    ) -> dict[str, Any]:
        """
        保存本轮最终诊断。

        已经存在 Diagnosis 时直接复用，
        不再次覆盖。
        """

        assessment = self.get_assessment(
            assessment_id
        )

        if assessment is None:
            raise ValueError(
                f"测验不存在：{assessment_id}"
            )

        if assessment["diagnosis"] is not None:
            return assessment

        if assessment["evaluation"] is None:
            raise ValueError(
                "尚未完成评分，不能保存诊断"
            )

        if assessment["status"] != "graded":
            raise ValueError(
                "Diagnosis 只能基于 graded 测验"
            )

        with self.conn:
            self.conn.execute(
                """
                UPDATE assessments

                SET diagnosis_json = ?

                WHERE id = ?
                  AND diagnosis_json IS NULL
                """,
                (
                    dump_json(diagnosis),
                    assessment_id,
                ),
            )

        result = self.get_assessment(
            assessment_id
        )

        assert result is not None

        return result

    def count_graded_assessments(
            self,
            *,
            project_id: str,
            node_id: str,
    ) -> int:

        row = self.conn.execute(
            """
            SELECT COUNT(*) AS count

            FROM assessments

            WHERE project_id = ?
              AND node_id = ?
              AND status = 'graded'
              AND evaluation_json IS NOT NULL
            """,
            (
                project_id,
                node_id,
            ),
        ).fetchone()

        return int(row["count"])

    def abandon_assessment(self, *, project_id: str, assessment_id: str) -> None:
        assessment = self.get_assessment(assessment_id)
        if assessment is None or assessment["project_id"] != project_id:
            raise ValueError("当前项目中找不到该测验")
        if assessment["status"] == "abandoned":
            return
        if assessment["status"] != "awaiting_answer" or assessment["answers"] is not None:
            raise ValueError("只有尚未提交答案的试卷可以放弃")
        with self.conn:
            self.conn.execute("UPDATE assessments SET status = 'abandoned' WHERE id = ?", (assessment_id,))

    def list_project_evaluations(self, project_id: str, *, limit: int = 12) -> list[dict]:
        """只读已评分业务事实；界面投影另做合法性校验与白名单选择。"""
        rows = self.conn.execute(
            "SELECT id FROM assessments WHERE project_id = ? AND status = 'graded' "
            "AND evaluation_json IS NOT NULL ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        ).fetchall()
        return [self.get_assessment(row["id"]) for row in rows]

    def get_progress(
            self,
            *,
            project_id: str,
            node_id: str,
    ) -> dict[str, Any] | None:

        row = self.conn.execute(
            """
            SELECT
                project_id,
                node_id,
                started_at,
                completed_at,
                completion_assessment_id

            FROM learning_progress

            WHERE project_id = ?
              AND node_id = ?
            """,
            (
                project_id,
                node_id,
            ),
        ).fetchone()

        if row is None:
            return None

        return dict(row)

    def mark_node_started(
            self,
            *,
            project_id: str,
            node_id: str,
    ) -> dict[str, Any]:

        now = utc_now()

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO learning_progress (
                    project_id,
                    node_id,
                    started_at,
                    completed_at,
                    completion_assessment_id
                )

                VALUES (
                    ?, ?, ?, NULL, NULL
                )

                ON CONFLICT (
                    project_id,
                    node_id
                )
                DO UPDATE SET
                    started_at = COALESCE(
                        learning_progress.started_at,
                        excluded.started_at
                    )
                """,
                (
                    project_id,
                    node_id,
                    now,
                ),
            )

        result = self.get_progress(
            project_id=project_id,
            node_id=node_id,
        )

        assert result is not None

        return result

    def mark_node_completed(
            self,
            *,
            project_id: str,
            node_id: str,
            assessment_id: str,
    ) -> dict[str, Any]:
        """
        幂等记录节点完成。

        第一次成功后，
        后续重复执行不得覆盖原完成事实。
        """

        assessment = self.get_assessment(
            assessment_id
        )

        if assessment is None:
            raise ValueError(
                f"完成测验不存在：{assessment_id}"
            )

        if (
                assessment["project_id"]
                != project_id
                or assessment["node_id"]
                != node_id
        ):
            raise ValueError(
                "完成测验与项目 / 节点不匹配"
            )

        if assessment["status"] != "graded":
            raise ValueError(
                "只有已评分测验才能作为完成依据"
            )

        now = utc_now()

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO learning_progress (
                    project_id,
                    node_id,
                    started_at,
                    completed_at,
                    completion_assessment_id
                )

                VALUES (
                    ?, ?, ?, ?, ?
                )

                ON CONFLICT (
                    project_id,
                    node_id
                )
                DO UPDATE SET

                    started_at = COALESCE(
                        learning_progress.started_at,
                        excluded.started_at
                    ),

                    completed_at = COALESCE(
                        learning_progress.completed_at,
                        excluded.completed_at
                    ),

                    completion_assessment_id = COALESCE(
                        learning_progress.completion_assessment_id,
                        excluded.completion_assessment_id
                    )
                """,
                (
                    project_id,
                    node_id,
                    now,
                    now,
                    assessment_id,
                ),
            )

        result = self.get_progress(
            project_id=project_id,
            node_id=node_id,
        )

        assert result is not None

        return result

    def get_node(
            self,
            *,
            project_id: str,
            node_id: str,
    ) -> dict[str, Any] | None:

        row = self.conn.execute(
            """
            SELECT
                project_id,
                id,
                title,
                description,
                objectives_json,
                prerequisite_ids_json,
                difficulty,
                estimated_minutes,
                sort_order

            FROM knowledge_nodes

            WHERE project_id = ?
              AND id = ?
            """,
            (
                project_id,
                node_id,
            ),
        ).fetchone()

        if row is None:
            return None

        return {
            "project_id": row["project_id"],
            "id": row["id"],
            "title": row["title"],
            "description": row["description"],
            "objectives": load_json(
                row["objectives_json"]
            ),
            "prerequisite_ids": load_json(
                row["prerequisite_ids_json"]
            ),
            "difficulty": row["difficulty"],
            "estimated_minutes": (
                row["estimated_minutes"]
            ),
            "sort_order": row["sort_order"],
        }

    def list_recent_graded_assessments(
        self,
        *,
        project_id: str,
        node_id: str,
        limit: int = 3,
        exclude_assessment_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """返回最近的有效评分；逐条读取，跳过旧演示中的空卷或损坏记录。"""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 3:
            raise ValueError("limit 必须是 1 到 3 之间的整数")

        node = self.get_node(project_id=project_id, node_id=node_id)
        if node is None:
            return []
        skill_node = SkillNode.model_validate({
            key: value for key, value in node.items() if key not in {"project_id", "sort_order"}
        })
        sql = """
            SELECT * FROM assessments
            WHERE project_id = ? AND node_id = ?
              AND status = 'graded' AND evaluation_json IS NOT NULL
        """
        params: list[Any] = [project_id, node_id]
        if exclude_assessment_id is not None:
            sql += " AND id <> ?"
            params.append(exclude_assessment_id)
        sql += " ORDER BY created_at DESC, round_no DESC, id DESC"

        results = []
        cursor = self.conn.execute(sql, params)
        try:
            # 不 fetchall 全部历史；达到 limit 后立即停止。
            for row in cursor:
                try:
                    record = {
                        "id": row["id"], "project_id": row["project_id"],
                        "node_id": row["node_id"], "round_no": row["round_no"],
                        "quiz": load_json(row["quiz_json"]),
                        "answers": load_json(row["answers_json"]),
                        "evaluation": load_json(row["evaluation_json"]),
                        "diagnosis": load_json(row["diagnosis_json"]),
                        "status": row["status"], "created_at": row["created_at"],
                    }
                    quiz = AssessmentQuiz.model_validate(record["quiz"])
                    evaluation = AssessmentEvaluation.model_validate(record["evaluation"])
                    if quiz.assessment_id != record["id"]:
                        raise ValueError("存储的试卷 ID 与测验记录不一致")
                    validate_quiz_against_node(quiz, skill_node)
                    scores = validate_and_score_evaluation(quiz, evaluation)
                    if not all(math.isfinite(value) for value in scores.values()):
                        raise ValueError("评分必须是有限数值")
                    answers = record["answers"]
                    if not isinstance(answers, dict) or set(answers) != {q.id for q in quiz.questions}:
                        raise ValueError("历史答案未完整对应试卷")
                except (ValueError, TypeError):
                    # 无效旧记录不会冒充 0 分学习事实，也不占用有效历史限额。
                    continue
                results.append(record)
                if len(results) >= limit:
                    break
        finally:
            cursor.close()
        return results

    def list_previous_quizzes(
        self, *, project_id: str, node_id: str, exclude_assessment_id: str,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """查询同项目、同节点的旧卷，包括未评分与 abandoned 的已出试卷。"""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 3:
            raise ValueError("limit 必须是 1 到 3 之间的整数")
        cursor = self.conn.execute(
            """
            SELECT id, quiz_json, created_at FROM assessments
            WHERE project_id = ? AND node_id = ? AND id <> ?
              AND quiz_json IS NOT NULL
            ORDER BY created_at DESC, round_no DESC, id DESC
            """,
            (project_id, node_id, exclude_assessment_id),
        )
        results = []
        try:
            for row in cursor:
                try:
                    quiz = load_json(row["quiz_json"])
                except (ValueError, TypeError):
                    continue
                if not isinstance(quiz, dict) or not isinstance(quiz.get("questions"), list):
                    continue
                if not any(
                    isinstance(question, dict) and isinstance(question.get("prompt"), str)
                    and question["prompt"].strip()
                    for question in quiz["questions"]
                ):
                    continue
                results.append({
                    "assessment_id": row["id"], "quiz": quiz,
                    "created_at": row["created_at"],
                })
                if len(results) == limit:
                    break
        finally:
            cursor.close()
        return results
