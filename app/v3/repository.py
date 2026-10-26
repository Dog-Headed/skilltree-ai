"""V3 foundation persistence. Query methods never start a Graph or model."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from .storage import V3Paths, validate_existing, GRAPH_VERSION, CONTRACT_VERSION


class ConflictError(ValueError):
    pass


class BudgetExhaustedError(RuntimeError):
    pass


def encode(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def now():
    return datetime.now(timezone.utc).isoformat()


def request_key(value):
    return UUID(str(value)).hex


class V3Repository:
    def __init__(self, paths: V3Paths = V3Paths()):
        from .config import SERVER_LIMITS
        paths.validate()
        if not validate_existing(paths.learning, "business"):
            raise ValueError("Initialize V3 storage explicitly first")
        self.paths, self.limits = paths, SERVER_LIMITS
        self.conn = sqlite3.connect(paths.learning, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.conn.close()

    @contextmanager
    def transaction(self):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def get_project(self, project_id):
        row = self.conn.execute("SELECT * FROM learning_projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        for name in ("profile", "candidate_plan", "policy", "frozen_snapshot", "limits"):
            raw = result.pop(name + "_json")
            result[name] = json.loads(raw) if raw else None
        result["requires_replan"] = bool(result["candidate_plan"] and result["candidate_revision"] != result["draft_revision"])
        return result

    def list_projects(self):
        return [self.get_project(row[0]) for row in self.conn.execute("SELECT id FROM learning_projects ORDER BY created_at,id")]

    def create_project(self, request_id, profile, *, derived_from_project_id=None, guided_intent=None):
        from .contracts import LearningProfile
        profile = LearningProfile.model_validate(profile)
        if profile.profile_version != 1:
            raise ValueError("Initial profile_version is server-owned and must be 1")
        if profile.prior_knowledge.assessed_evidence:
            raise ValueError("Day 9 does not import verified prior assessments; use self_reported")
        key = request_key(request_id)
        profile_json = encode(profile)
        creation={"profile": json.loads(profile_json), "parent": derived_from_project_id}
        if guided_intent is not None:creation['guided_intent']=guided_intent
        fingerprint = hashlib.sha256(encode(creation).encode()).hexdigest()
        project_id = "v3_" + key
        with self.transaction():
            row = self.conn.execute("SELECT id,create_fingerprint FROM learning_projects WHERE create_request_id=?", (key,)).fetchone()
            if row:
                if row["create_fingerprint"] != fingerprint:
                    raise ConflictError("Creation request reused with different input")
                return self.get_project(row["id"])
            self.conn.execute("""INSERT INTO learning_projects
                (id,thread_id,create_request_id,create_fingerprint,goal,profile_json,draft_revision,lifecycle,
                 pending_input_id,derived_from_project_id,limits_json,created_at,graph_version,contract_version)
                VALUES (?,?,?,?,?,?,1,'profile_review',?,?,?,?,?,?)""",
                (project_id, project_id, key, fingerprint, profile.goal, profile_json, "profile_"+uuid4().hex,
                 derived_from_project_id, encode(self.limits), now(), GRAPH_VERSION, CONTRACT_VERSION))
            if guided_intent is not None:
                from .onboarding import register
                register(self,project_id,guided_intent)
        return self.get_project(project_id)

    def _draft(self, project_id, expected_revision=None):
        project = self.get_project(project_id)
        if not project:
            raise KeyError(project_id)
        if project["frozen_snapshot"]:
            raise ConflictError("Frozen project content cannot be replaced; derive a new project")
        if expected_revision is not None and project["draft_revision"] != expected_revision:
            raise ConflictError("Stale draft_revision; requires_replan")
        return project

    def update_profile(self, project_id, profile, *, expected_revision, pending_input_id):
        from .contracts import LearningProfile
        profile = LearningProfile.model_validate(profile)
        with self.transaction():
            project = self._draft(project_id, expected_revision)
            if profile.profile_version != project["profile"]["profile_version"] or profile.prior_knowledge.assessed_evidence:
                raise ValueError("Draft input cannot mint a profile version or assessed evidence")
            if pending_input_id != project["pending_input_id"]:
                raise ConflictError("Stale pending_input_id")
            if encode(project["profile"]) != encode(profile):
                self.conn.execute("UPDATE learning_projects SET profile_json=?,goal=?,draft_revision=draft_revision+1,pending_input_id=?,profile_confirmation_hash=NULL,lifecycle='profile_review' WHERE id=?",
                                  (encode(profile), profile.goal, "profile_"+uuid4().hex, project_id))
        return self.get_project(project_id)

    def save_candidate_plan(self, project_id, plan, *, expected_revision, policy=None):
        from .contracts import LearningPlan
        plan = LearningPlan.model_validate(plan)
        with self.transaction():
            project = self._draft(project_id, expected_revision)
            if plan.project_id != project_id or plan.draft_revision != expected_revision:
                raise ConflictError("Plan project/revision does not match draft")
            input_id="plan_"+uuid4().hex
            self.conn.execute("UPDATE learning_projects SET candidate_plan_json=?,candidate_revision=?,candidate_policy_json=?,lifecycle='plan_review',pending_input_id=?,candidate_input_id=?,error_type=NULL WHERE id=?",
                              (encode(plan), expected_revision, encode(policy) if policy is not None else None, input_id,input_id,project_id))
        return self.get_project(project_id)

    def put_source(self, document, chunks, *, request_id):
        from .contracts import SourceDocument, SourceChunk
        document = SourceDocument.model_validate(document)
        chunks = [SourceChunk.model_validate(c) for c in chunks]
        key = request_key(request_id)
        raw_bytes = len(document.content.encode("utf-8"))
        if raw_bytes > self.limits.max_file_bytes:
            raise ValueError("Source exceeds server file limit")
        if len({c.chunk_id for c in chunks}) != len(chunks):
            raise ValueError("Duplicate chunk identity")
        for c in chunks:
            if (c.project_id, c.source_id, c.source_version) != (document.project_id, document.source_id, document.source_version):
                raise ValueError("Cross-project or source-version chunk")
            lines = document.content.splitlines()
            if c.line_end > len(lines) or c.content != "\n".join(lines[c.line_start-1:c.line_end]):
                raise ValueError("Chunk must exactly locate its source lines")
        ordered = sorted(chunks, key=lambda c:c.line_start)
        if any(left.line_end >= right.line_start for left,right in zip(ordered,ordered[1:])):
            raise ValueError("Foundation chunks must have non-overlapping source ranges")
        with self.transaction():
            self._draft(document.project_id)
            existing = self.conn.execute("SELECT document_json FROM source_documents WHERE project_id=? AND import_request_id=?",
                                         (document.project_id, key)).fetchone()
            if existing:
                saved_chunks = [json.loads(r[0]) for r in self.conn.execute("SELECT chunk_json FROM source_chunks WHERE project_id=? AND source_id=? AND source_version=? ORDER BY chunk_id",
                                                                          (document.project_id, document.source_id, document.source_version))]
                if existing[0] != encode(document) or encode(saved_chunks) != encode(sorted([c.model_dump(mode="json") for c in chunks], key=lambda c:c["chunk_id"])):
                    raise ConflictError("Source import identity reused with changed content")
                return
            if self.conn.execute("SELECT 1 FROM source_documents WHERE project_id=? AND source_id=? AND source_version=?", (document.project_id, document.source_id, document.source_version)).fetchone():
                raise ConflictError("Source version is immutable")
            used = self.conn.execute("SELECT COALESCE(SUM(content_bytes),0) FROM source_documents WHERE project_id=?", (document.project_id,)).fetchone()[0]
            if used + raw_bytes > self.limits.max_project_material_bytes:
                raise ValueError("Project material limit exceeded")
            self.conn.execute("INSERT INTO source_documents VALUES (?,?,?,?,?,?,?)", (document.project_id, document.source_id, document.source_version, key, encode(document), raw_bytes, document.visibility))
            self.conn.executemany("INSERT INTO source_chunks VALUES (?,?,?,?,?)", ((c.project_id,c.chunk_id,c.source_id,c.source_version,encode(c)) for c in chunks))
            self.conn.execute("UPDATE learning_projects SET draft_revision=draft_revision+1 WHERE id=?", (document.project_id,))

    def list_sources(self, project_id, *, include_private=False):
        return [json.loads(r[0]) for r in self.conn.execute("SELECT document_json FROM source_documents WHERE project_id=? AND (? OR visibility='teaching') ORDER BY source_id,source_version", (project_id, int(include_private)))]

    def list_source_chunks(self, project_id, source_id, source_version, *, include_private=False):
        chunks=[json.loads(r[0]) for r in self.conn.execute("""SELECT c.chunk_json FROM source_chunks c JOIN source_documents d
            USING(project_id,source_id,source_version) WHERE c.project_id=? AND c.source_id=? AND c.source_version=?
            AND (? OR d.visibility='teaching') ORDER BY c.chunk_id""",(project_id,source_id,source_version,int(include_private)))]
        return sorted(chunks,key=lambda c:(c['line_start'],c['line_end'],c['chunk_id']))

    def import_source_version(self, document_kwargs, chunks_factory, *, request_id):
        from .contracts import SourceDocument, SourceChunk
        key=request_key(request_id)
        proposed=SourceDocument.model_validate({**document_kwargs,"source_version":1})
        fingerprint=hashlib.sha256(encode(proposed.model_dump(exclude={"source_version"})).encode()).hexdigest()
        project_id=proposed.project_id
        with self.transaction():
            replay=self.conn.execute("SELECT * FROM source_import_requests WHERE project_id=? AND request_id=?",(project_id,key)).fetchone()
            if replay:
                if replay["fingerprint"] != fingerprint:raise ConflictError("Import request reused with changed content")
                version=replay["source_version"]
                row=self.conn.execute("SELECT document_json FROM source_documents WHERE project_id=? AND source_id=? AND source_version=?",(project_id,replay["source_id"],version)).fetchone()
                return {"document":json.loads(row[0]),"chunks":self.list_source_chunks(project_id,replay["source_id"],version,include_private=True),"reused":True,"draft_revision":self.get_project(project_id)["draft_revision"]}
            self._draft(project_id)
            latest=self.conn.execute("SELECT document_json FROM source_documents WHERE project_id=? AND source_id=? ORDER BY source_version DESC LIMIT 1",(project_id,proposed.source_id)).fetchone()
            current=SourceDocument.model_validate(json.loads(latest[0])) if latest else None
            reused=bool(current and encode(current.model_dump(exclude={"source_version"}))==encode(proposed.model_dump(exclude={"source_version"})))
            version=current.source_version if reused else (current.source_version+1 if current else 1)
            document=SourceDocument.model_validate({**document_kwargs,"source_version":version})
            chunks=sorted([SourceChunk.model_validate(c) for c in chunks_factory(document)],key=lambda c:(c.line_start,c.line_end,c.chunk_id))
            if not chunks or len({c.chunk_id for c in chunks}) != len(chunks):raise ValueError("Source requires unique actual chunks")
            from .materials import validate_chunk_origin
            for chunk in chunks:validate_chunk_origin(chunk,document)
            ordered=sorted(chunks,key=lambda c:c.line_start)
            if any(a.line_end>=b.line_start for a,b in zip(ordered,ordered[1:])):raise ValueError("Overlapping source chunks")
            legacy=self.conn.execute("SELECT document_json FROM source_documents WHERE project_id=? AND import_request_id=?",(project_id,key)).fetchone()
            if legacy and encode(json.loads(legacy[0])) != encode(document):raise ConflictError("Import request identity already used")
            if reused:
                actual=self.list_source_chunks(project_id,document.source_id,version,include_private=True)
                if encode(sorted(actual,key=lambda c:c['chunk_id'])) != encode(sorted([c.model_dump() for c in chunks],key=lambda c:c['chunk_id'])):
                    raise ConflictError("Deterministic chunking changed; use a new source version")
            else:
                used=self.conn.execute("SELECT COALESCE(SUM(content_bytes),0) FROM source_documents WHERE project_id=?",(project_id,)).fetchone()[0]
                count=len(document.content.encode('utf-8'))
                if count>self.limits.max_file_bytes or used+count>self.limits.max_project_material_bytes:raise ValueError("Material size exceeds server limit")
                self.conn.execute("INSERT INTO source_documents VALUES (?,?,?,?,?,?,?)",(project_id,document.source_id,version,key,encode(document),count,document.visibility))
                self.conn.executemany("INSERT INTO source_chunks VALUES (?,?,?,?,?)",((c.project_id,c.chunk_id,c.source_id,c.source_version,encode(c)) for c in chunks))
                self.conn.execute("UPDATE learning_projects SET draft_revision=draft_revision+1 WHERE id=?",(project_id,))
            self.conn.execute("INSERT INTO source_import_requests VALUES (?,?,?,?,?)",(project_id,key,fingerprint,document.source_id,version))
            return {"document":document.model_dump(),"chunks":[c.model_dump() for c in chunks],"reused":reused,"draft_revision":self.get_project(project_id)["draft_revision"]}

    def get_bound_chunks(self, project_id, node_id, objective_id, purpose):
        if purpose not in ('teaching','assessment','grading'):raise ValueError("Unknown material purpose")
        project=self.get_project(project_id)
        if not project or not project['candidate_plan']:return []
        node=next((n for n in project['candidate_plan']['nodes'] if n['node_id']==node_id),None)
        objective=next((o for o in node['objectives'] if o['objective_id']==objective_id),None) if node else None
        if objective is None:raise ValueError("Unknown node/objective")
        if project['frozen_snapshot']:
            identities=[(r['chunk_id'],r['purpose']) for r in self.conn.execute("SELECT chunk_id,purpose FROM node_material_links WHERE project_id=? AND node_id=? AND objective_id=? AND purpose IN ('teaching',?)",(project_id,node_id,objective_id,purpose))]
            manifest={(r['source_id'],r['source_version']) for r in project['frozen_snapshot']['source_manifest']}
        else:
            if project['requires_replan']:raise ConflictError("Source revision changed; requires_replan")
            identities=[(chunk_id,'teaching') for chunk_id in objective['source_chunk_ids']]
            manifest=None
        result=[]
        for chunk_id,binding_purpose in identities:
            chunk=self.get_chunk(project_id,chunk_id,include_private=purpose!='teaching')
            if not chunk:continue
            row=self.conn.execute("SELECT document_json FROM source_documents WHERE project_id=? AND source_id=? AND source_version=?",(project_id,chunk['source_id'],chunk['source_version'])).fetchone()
            if manifest is not None and (chunk['source_id'],chunk['source_version']) not in manifest:raise ValueError("Binding differs from frozen source manifest")
            result.append({'chunk':chunk,'source':json.loads(row[0]),'purpose':binding_purpose})
        return result

    def get_chunk(self, project_id, chunk_id, *, include_private=False):
        row = self.conn.execute("""SELECT c.chunk_json FROM source_chunks c JOIN source_documents d
            USING(project_id,source_id,source_version) WHERE c.project_id=? AND c.chunk_id=? AND (? OR d.visibility='teaching')""",
            (project_id, chunk_id, int(include_private))).fetchone()
        return json.loads(row[0]) if row else None

    def freeze_plan(self, project_id, policy, *, expected_revision, pending_input_id, material_links=()):
        """Persist one confirmed snapshot. Day 9 exposes no teaching/completion runner."""
        from .contracts import LearningProfile, LearningPlan, FrozenSnapshot, SourceDocument, SourceChunk, NodeMaterialLink, validate_material_link
        from .capabilities import check_capabilities, validate_policy, get_capability
        policy = validate_policy(policy)
        links = [NodeMaterialLink.model_validate(link) for link in material_links]
        with self.transaction():
            project = self._draft(project_id, expected_revision)
            if pending_input_id != project["pending_input_id"] or project["requires_replan"] or not project["candidate_plan"]:
                raise ConflictError("Stale plan confirmation; requires_replan")
            profile = LearningProfile.model_validate(project["profile"])
            plan = LearningPlan.model_validate(project["candidate_plan"])
            sources = self.list_sources(project_id, include_private=True)
            if profile.learning_mode == "exploration":
                raise ValueError("Exploration cannot freeze a formal learning plan")
            if not profile.bounded_goal:
                raise ValueError("Formal profile needs a bounded goal")
            # Recheck executable capabilities; caller assertions cannot grant permission.
            result = check_capabilities(profile, has_material=any(d["visibility"] == "teaching" for d in sources))
            if result.status != "supported":
                raise ValueError("Formal plan requires supported capabilities and material")
            objective_ids = {obj.objective_id for node in plan.nodes for obj in node.objectives}
            rules = {rule.objective_id:rule for rule in policy.objective_rules}
            if rules.keys() != objective_ids:
                raise ValueError("Policy must cover exactly the confirmed plan objectives")
            if sum(node.estimated_minutes for node in plan.nodes) > profile.time_budget_minutes:
                raise ValueError("Plan exceeds confirmed time budget")
            evaluator_ids = {ref.evaluator_id for ref in policy.evaluators}
            # Freeze only explicitly referenced source versions, including private
            # sources only through validated assessment/grading bindings.
            selected = {}
            chunks = {}
            for node in plan.nodes:
                if sum(rules[o.objective_id].min_items for o in node.objectives if o.required) > self.limits.max_questions_per_assessment:
                    raise ValueError("Objective coverage cannot fit the server question limit")
                for objective in node.objectives:
                    check = check_capabilities(objective.required_capability_ids, has_material=True)
                    if check.status != "supported":
                        raise ValueError("Objective uses unavailable evaluation capabilities")
                    needed = {get_capability(c).evaluator_id for c in objective.required_capability_ids if get_capability(c).kind == "evaluation"}
                    rule = rules[objective.objective_id]
                    if not needed <= evaluator_ids or rule.required != objective.required or not set(objective.evidence_requirement) <= set(rule.evidence_kinds):
                        raise ValueError("Objective capability, evidence or required rule conflicts with policy")
                    if not objective.source_chunk_ids:
                        raise ValueError("Formal objective needs source coverage")
                    for chunk_id in objective.source_chunk_ids:
                        raw = self.get_chunk(project_id, chunk_id)
                        if not raw:
                            raise ValueError("Objective requires a project teaching chunk")
                        chunks[chunk_id] = SourceChunk.model_validate(raw)
                        links.append(NodeMaterialLink(project_id=project_id,node_id=node.node_id,objective_id=objective.objective_id,chunk_id=chunk_id,purpose="teaching"))
            for link in links:
                raw = self.get_chunk(project_id,link.chunk_id,include_private=True)
                if not raw:
                    raise ValueError("Material binding uses an unknown project chunk")
                chunk = SourceChunk.model_validate(raw)
                source = next(d for d in sources if (d["source_id"],d["source_version"]) == (chunk.source_id,chunk.source_version))
                document = SourceDocument.model_validate(source)
                validate_material_link(link,project_id=project_id,plan=plan,chunks={chunk.chunk_id:chunk},sources={document.source_id:document})
                if document.source_id in selected and selected[document.source_id]["source_version"] != document.source_version:
                    raise ValueError("One frozen plan cannot mix versions of the same source")
                selected[document.source_id] = source
            from .context import ContextBuilder
            ContextBuilder(self).validate_candidate_bindings(project_id, links, policy=policy)
            snapshot = FrozenSnapshot(profile_version=profile.profile_version, plan_version=plan.plan_version,
                                      policy_id=policy.policy_id, policy_version=policy.policy_version,
                                      source_manifest=[{k:d[k] for k in ("source_id","source_version","content_hash")} for d in selected.values()],
                                      evaluator_manifest=policy.evaluators)
            for node in plan.nodes:
                self.conn.execute("INSERT INTO knowledge_nodes VALUES (?,?,?,?)", (project_id,node.node_id,plan.plan_version,encode(node)))
                self.conn.execute("INSERT INTO learning_progress(project_id,node_id) VALUES (?,?)", (project_id,node.node_id))
            self.conn.executemany("INSERT OR IGNORE INTO node_material_links VALUES (?,?,?,?,?)",((link.project_id,link.node_id,link.objective_id,link.chunk_id,link.purpose) for link in links))
            self.conn.execute("UPDATE learning_projects SET policy_json=?,frozen_snapshot_json=?,frozen_at=?,lifecycle='learning',pending_input_id=NULL,last_confirmation_id=? WHERE id=?",
                              (encode(policy),encode(snapshot),now(),pending_input_id,project_id))
        return self.get_project(project_id)

    def prepare_assessment(self, project_id, node_id, *, request_id, previous_assessment_id=None):
        key = request_key(request_id)
        with self.transaction():
            project = self.get_project(project_id)
            if not project or not project["frozen_snapshot"]:
                raise ValueError("Assessment requires a frozen project")
            row = self.conn.execute("SELECT * FROM assessments WHERE project_id=? AND node_id=? AND prepare_request_id=?", (project_id,node_id,key)).fetchone()
            if row:
                if row["snapshot_json"] != encode(project["frozen_snapshot"]) or row["previous_assessment_id"] != previous_assessment_id:
                    raise ConflictError("Assessment identity/snapshot mismatch")
                return dict(row)
            assessment_id = "assessment_"+uuid5(NAMESPACE_URL,project_id+":"+node_id+":"+key).hex
            self.conn.execute("INSERT INTO assessments(id,project_id,node_id,prepare_request_id,snapshot_json,status,previous_assessment_id,created_at) VALUES (?,?,?,?,?,'prepared',?,?)",
                              (assessment_id,project_id,node_id,key,encode(project["frozen_snapshot"]),previous_assessment_id,now()))
        return self.get_assessment(project_id, assessment_id)

    def get_assessment(self, project_id, assessment_id):
        row = self.conn.execute("SELECT * FROM assessments WHERE project_id=? AND id=?", (project_id,assessment_id)).fetchone()
        return dict(row) if row else None

    def mark_node_started(self, project_id, node_id):
        with self.transaction():
            cursor = self.conn.execute("UPDATE learning_progress SET started_at=COALESCE(started_at,?) WHERE project_id=? AND node_id=?", (now(),project_id,node_id))
            if cursor.rowcount != 1:
                raise KeyError(node_id)

    def get_progress(self, project_id):
        return [dict(r) for r in self.conn.execute("SELECT * FROM learning_progress WHERE project_id=? ORDER BY node_id", (project_id,))]

    def create_operation(self, project_id, request_id, *, kind, parent_operation_id=None, retry_token=None):
        key = request_key(request_id)
        with self.transaction():
            existing = self.conn.execute("SELECT * FROM model_operations WHERE project_id=? AND request_id=?", (project_id,key)).fetchone()
            if existing:
                if existing["kind"] != kind or existing["parent_operation_id"] != parent_operation_id:
                    raise ConflictError("Operation request reused with different intent")
                if parent_operation_id:
                    parent = self.get_operation(project_id,parent_operation_id)
                    if not parent or parent["retry_token"] != retry_token:
                        raise ConflictError("Stale continuation token")
                return dict(existing)
            operation_id = "operation_"+uuid5(NAMESPACE_URL,project_id+":"+key).hex
            root_id = operation_id
            if parent_operation_id:
                parent = self.get_operation(project_id,parent_operation_id)
                if not parent or parent["retry_token"] != retry_token:
                    raise ConflictError("Stale continuation token")
                if parent["status"] != "budget_exhausted" or parent["parent_operation_id"]:
                    raise ConflictError("Only one explicit continuation of an exhausted root is allowed")
                if self.conn.execute("SELECT 1 FROM model_operations WHERE parent_operation_id=?", (parent_operation_id,)).fetchone():
                    raise ConflictError("Budget already extended")
                root_id = parent["root_operation_id"]
            self.conn.execute("INSERT INTO model_operations(operation_id,project_id,request_id,kind,root_operation_id,parent_operation_id,retry_token,request_limit,status,created_at) VALUES (?,?,?,?,?,?,?,?,'pending',?)",
                              (operation_id,project_id,key,kind,root_id,parent_operation_id,"retry_"+uuid4().hex,self.limits.max_operation_requests,now()))
        return self.get_operation(project_id,operation_id)

    def get_operation(self, project_id, operation_id):
        row = self.conn.execute("SELECT * FROM model_operations WHERE project_id=? AND operation_id=?", (project_id,operation_id)).fetchone()
        return dict(row) if row else None

    def reserve_model_request(self, project_id, operation_id):
        """Commit BEFORE HTTP; an interrupted request remains charged after restart."""
        exhausted = False
        with self.transaction():
            op = self.get_operation(project_id,operation_id)
            if not op:
                raise KeyError(operation_id)
            if op["status"] == "completed":
                raise ConflictError("Completed operation cannot make another request")
            if op["reserved_requests"] >= op["request_limit"]:
                self.conn.execute("UPDATE model_operations SET status='budget_exhausted' WHERE operation_id=?",(operation_id,))
                exhausted = True
            else:
                reserved_number = op["reserved_requests"] + 1
                self.conn.execute("UPDATE model_operations SET reserved_requests=reserved_requests+1,status='running' WHERE operation_id=?",(operation_id,))
        if exhausted:
            raise BudgetExhaustedError("Operation budget exhausted; explicit continuation or save required")
        return reserved_number
