"""Stage 7: render an AWS architecture diagram from the assembled template.

Produces a grouped, labeled diagram with semantic flows (not a linear icon
chain). Resources are bucketed into logical tiers — Edge, Compute, Data,
Identity, Observability — and edges are drawn based on the workload type
so the picture matches how the services actually talk to each other.

Falls back to a Mermaid string if Graphviz or the `diagrams` lib is missing.
"""
from __future__ import annotations

import importlib
import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple


def _ensure_graphviz_on_path() -> None:
    if shutil.which("dot"):
        return
    for c in (r"C:\Program Files\Graphviz\bin", r"C:\Program Files (x86)\Graphviz\bin"):
        if os.path.isdir(c) and os.path.exists(os.path.join(c, "dot.exe")):
            os.environ["PATH"] = c + os.pathsep + os.environ.get("PATH", "")
            return


_ensure_graphviz_on_path()


def _writable_tempdir() -> str:
    """Prefer a project-local tmp dir if C:\\ (default %TEMP%) is full."""
    project_tmp = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".cache",
        "diagrams",
    )
    try:
        os.makedirs(project_tmp, exist_ok=True)
        probe = os.path.join(project_tmp, ".probe")
        with open(probe, "wb") as f:
            f.write(b"0")
        os.remove(probe)
        return tempfile.mkdtemp(prefix="arch_", dir=project_tmp)
    except OSError:
        return tempfile.mkdtemp(prefix="arch_")


# tf resource type -> (diagrams submodule, class, tier)
_NODE_MAP: Dict[str, Tuple[str, str, str]] = {
    # Edge / network
    "aws_apigatewayv2_api": ("network", "APIGateway", "edge"),
    "aws_api_gateway_rest_api": ("network", "APIGateway", "edge"),
    "aws_cloudfront_distribution": ("network", "CloudFront", "edge"),
    "aws_route53_health_check": ("network", "Route53", "edge"),
    "aws_route53_zone": ("network", "Route53", "edge"),
    "aws_elb": ("network", "ELB", "edge"),
    "aws_lb": ("network", "ELB", "edge"),
    # Compute
    "aws_lambda_function": ("compute", "Lambda", "compute"),
    "aws_ecs_service": ("compute", "ECS", "compute"),
    "aws_ecs_cluster": ("compute", "ECS", "compute"),
    "aws_ecr_repository": ("compute", "EC2ContainerRegistry", "compute"),
    "aws_sagemaker_model": ("ml", "Sagemaker", "compute"),
    "aws_sagemaker_training_job": ("ml", "SagemakerTrainingJob", "compute"),
    "aws_glue_job": ("analytics", "Glue", "compute"),
    "aws_sfn_state_machine": ("integration", "StepFunctions", "compute"),
    # Data
    "aws_dynamodb_table": ("database", "Dynamodb", "data"),
    "aws_db_instance": ("database", "RDS", "data"),
    "aws_elasticache_replication_group": ("database", "ElastiCache", "data"),
    "aws_s3_bucket": ("storage", "S3", "data"),
    "aws_s3_bucket_versioning": ("storage", "S3", "data"),
    "aws_glue_catalog_database": ("analytics", "GlueDataCatalog", "data"),
    "aws_athena_workgroup": ("analytics", "Athena", "data"),
    # Identity / security
    "aws_cognito_user_pool": ("security", "Cognito", "identity"),
    "aws_iam_role": ("security", "IAM", "identity"),
    "aws_iam_account_password_policy": ("security", "IAM", "identity"),
    "aws_kms_key": ("security", "KMS", "identity"),
    "aws_guardduty_detector": ("security", "Guardduty", "identity"),
    "aws_wafv2_web_acl": ("security", "WAF", "identity"),
    # Observability
    "aws_cloudwatch_log_group": ("management", "Cloudwatch", "obs"),
    "aws_cloudtrail": ("management", "Cloudtrail", "obs"),
}


_TIER_ORDER = ["edge", "compute", "data", "identity", "obs"]
_TIER_LABELS = {
    "edge": "Edge / API",
    "compute": "Compute",
    "data": "Data",
    "identity": "Identity & Security",
    "obs": "Observability",
}
_TIER_BG = {
    "edge": "#E8F1FB",
    "compute": "#FFF3E6",
    "data": "#EAF7EE",
    "identity": "#FDEBEA",
    "obs": "#F3EEFB",
}


def _safe_label(s: str, max_len: int = 22) -> str:
    s = str(s).replace('"', "'")
    # stay ASCII-only; Graphviz cairo writer can fail on some unicode
    s = s.encode("ascii", "ignore").decode("ascii")
    return s if len(s) <= max_len else s[: max_len - 3] + "..."


def _mermaid(template: dict) -> str:
    """Grouped Mermaid fallback — used when Graphviz / diagrams unavailable."""
    resources = template.get("resources", [])
    tiers: Dict[str, List[dict]] = {t: [] for t in _TIER_ORDER}
    for r in resources:
        mapped = _NODE_MAP.get(r["type"])
        if not mapped:
            continue
        tiers[mapped[2]].append(r)

    def nid(r: dict) -> str:
        return f"{r['type']}_{r['name']}".replace("-", "_").replace(".", "_")

    lines = ["flowchart LR", "    user((User / Client))"]
    for tier in _TIER_ORDER:
        if not tiers[tier]:
            continue
        lines.append(f'    subgraph {tier}["{_TIER_LABELS[tier]}"]')
        for r in tiers[tier]:
            label = f"{r['type'].replace('aws_', '')}<br/>{r['name']}"
            lines.append(f'        {nid(r)}["{label}"]')
        lines.append("    end")

    # basic spine: user -> edge -> compute -> data
    spine = [tiers.get(t, []) for t in ("edge", "compute", "data")]
    prev_nodes = [("user", "user")]
    for group in spine:
        if not group:
            continue
        for r in group:
            for pn, _ in prev_nodes:
                lines.append(f"    {pn} --> {nid(r)}")
        prev_nodes = [(nid(r), r["name"]) for r in group]

    # identity -> compute (dashed)
    for r in tiers.get("identity", []):
        for c in tiers.get("compute", []) or tiers.get("edge", []):
            lines.append(f"    {nid(r)} -.-> {nid(c)}")
    # compute -> obs (dashed)
    for c in tiers.get("compute", []):
        for o in tiers.get("obs", []):
            lines.append(f"    {nid(c)} -.-> {nid(o)}")

    return "\n".join(lines)


def _match_iam_target(role_name: str, compute_nodes: Dict[str, Any]) -> Optional[str]:
    """Pick the compute node a given IAM role most likely serves, by name hint."""
    rn = role_name.lower()
    # hints: "lambda_exec" -> lambda, "glue" -> glue job, "sfn" -> step functions
    hints = {
        "lambda": ["handler", "lambda"],
        "glue": ["etl", "glue"],
        "sfn": ["orchestr", "sfn", "state"],
        "sagemaker": ["model", "train", "sagemaker"],
        "sm": ["model", "train", "sagemaker"],
        "ecs": ["ecs", "service"],
    }
    for key, targets in hints.items():
        if key in rn:
            for nn in compute_nodes:
                if any(t in nn.lower() for t in targets):
                    return nn
    # fallback: first compute node
    return next(iter(compute_nodes), None)


def _wire_web_api(nodes, edge_cls):
    """User -> (CF ->) APIGW -> Lambda -> Data;  Cognito authn APIGW."""
    user = nodes["_user"]
    e = nodes["edge"]
    c = nodes["compute"]
    d = nodes["data"]
    i = nodes["identity"]
    o = nodes["obs"]

    cf = next((n for t, n in e.items() if "cloudfront" in t), None)
    apigw = next((n for t, n in e.items() if "apigateway" in t), None)
    lambdas = [n for t, n in c.items() if "lambda_function" in t]
    cognito = next((n for t, n in i.items() if "cognito" in t), None)

    if cf and apigw:
        user >> edge_cls(label="HTTPS", color="#1A73E8") >> cf >> edge_cls(label="origin") >> apigw
    elif cf:
        user >> edge_cls(label="HTTPS", color="#1A73E8") >> cf
    if apigw and not cf:
        user >> edge_cls(label="HTTPS", color="#1A73E8") >> apigw
    if cognito and apigw:
        cognito >> edge_cls(label="authN", style="dashed", color="#B00020") >> apigw

    for fn in lambdas:
        if apigw:
            apigw >> edge_cls(label="invoke") >> fn
        for data_node in d.values():
            fn >> edge_cls(label="read/write", color="#0F8A3F") >> data_node
        for log in o.values():
            fn >> edge_cls(label="logs", style="dashed", color="#6B3FA0") >> log

    # IAM roles -> their compute target (dashed)
    iam_roles = {t: n for t, n in i.items() if "iam_role" in t}
    compute_by_name = {t.split("__")[-1]: n for t, n in c.items()}
    for role_key, role_node in iam_roles.items():
        role_name = role_key.split("__")[-1]
        tgt = _match_iam_target(role_name, compute_by_name)
        if tgt:
            role_node >> edge_cls(label="assumes", style="dotted", color="#6B3FA0") >> compute_by_name[tgt]


def _wire_data_pipeline(nodes, edge_cls):
    """S3 raw -> Glue -> S3 curated; Athena queries curated; SFN orchestrates Glue."""
    c = nodes["compute"]
    d = nodes["data"]
    i = nodes["identity"]
    o = nodes["obs"]

    raw = next((n for k, n in d.items() if "s3_bucket__raw" in k or ("s3_bucket" in k and "raw" in k)), None)
    curated = next((n for k, n in d.items() if "curated" in k), None)
    glue_job = next((n for k, n in c.items() if "glue_job" in k), None)
    sfn = next((n for k, n in c.items() if "sfn" in k), None)
    catalog = next((n for k, n in d.items() if "glue_catalog" in k), None)
    athena = next((n for k, n in d.items() if "athena" in k), None)

    if sfn and glue_job:
        sfn >> edge_cls(label="orchestrate") >> glue_job
    if raw and glue_job:
        raw >> edge_cls(label="read raw", color="#0F8A3F") >> glue_job
    if glue_job and curated:
        glue_job >> edge_cls(label="write curated", color="#0F8A3F") >> curated
    if catalog and glue_job:
        glue_job >> edge_cls(label="register", style="dashed") >> catalog
    if athena and curated:
        athena >> edge_cls(label="query", color="#1A73E8") >> curated
    if athena and catalog:
        catalog >> edge_cls(label="schema", style="dashed") >> athena

    for log in o.values():
        if glue_job:
            glue_job >> edge_cls(label="logs", style="dashed", color="#6B3FA0") >> log

    compute_by_name = {t.split("__")[-1]: n for t, n in c.items()}
    for role_key, role_node in {k: v for k, v in i.items() if "iam_role" in k}.items():
        role_name = role_key.split("__")[-1]
        tgt = _match_iam_target(role_name, compute_by_name)
        if tgt:
            role_node >> edge_cls(label="assumes", style="dotted", color="#6B3FA0") >> compute_by_name[tgt]


def _wire_ml_training(nodes, edge_cls):
    c = nodes["compute"]
    d = nodes["data"]
    i = nodes["identity"]
    o = nodes["obs"]

    datasets = next((n for k, n in d.items() if "dataset" in k), None)
    artifacts = next((n for k, n in d.items() if "artifact" in k), None)
    ecr = next((n for k, n in c.items() if "ecr" in k), None)
    sagemaker = next((n for k, n in c.items() if "sagemaker" in k), None)

    if datasets and sagemaker:
        datasets >> edge_cls(label="training data", color="#0F8A3F") >> sagemaker
    if ecr and sagemaker:
        ecr >> edge_cls(label="image", style="dashed") >> sagemaker
    if sagemaker and artifacts:
        sagemaker >> edge_cls(label="model artifacts", color="#0F8A3F") >> artifacts
    for log in o.values():
        if sagemaker:
            sagemaker >> edge_cls(label="logs", style="dashed", color="#6B3FA0") >> log

    compute_by_name = {t.split("__")[-1]: n for t, n in c.items()}
    for role_key, role_node in {k: v for k, v in i.items() if "iam_role" in k}.items():
        role_name = role_key.split("__")[-1]
        tgt = _match_iam_target(role_name, compute_by_name)
        if tgt:
            role_node >> edge_cls(label="assumes", style="dotted", color="#6B3FA0") >> compute_by_name[tgt]


def _wire_static_site(nodes, edge_cls):
    user = nodes["_user"]
    e = nodes["edge"]
    d = nodes["data"]
    cf = next((n for k, n in e.items() if "cloudfront" in k), None)
    bucket = next(iter(d.values()), None)
    if cf and bucket:
        user >> edge_cls(label="HTTPS", color="#1A73E8") >> cf >> edge_cls(label="origin") >> bucket
    elif bucket:
        user >> edge_cls(label="HTTPS", color="#1A73E8") >> bucket


def _wire_generic(nodes, edge_cls):
    """Fallback: user -> edge -> compute -> data; compute -> obs."""
    user = nodes["_user"]
    for tier in ("edge", "compute", "data"):
        if nodes[tier]:
            first = next(iter(nodes[tier].values()))
            user >> edge_cls(label="request", color="#1A73E8") >> first
            break
    prev_tier_nodes = []
    for tier in ("edge", "compute", "data"):
        tier_nodes = list(nodes[tier].values())
        if not tier_nodes:
            continue
        for pn in prev_tier_nodes:
            for tn in tier_nodes:
                pn >> edge_cls() >> tn
        prev_tier_nodes = tier_nodes
    for comp in nodes["compute"].values():
        for log in nodes["obs"].values():
            comp >> edge_cls(label="logs", style="dashed", color="#6B3FA0") >> log


_WIRING = {
    "web_api": _wire_web_api,
    "data_pipeline": _wire_data_pipeline,
    "ml_training": _wire_ml_training,
    "static_site": _wire_static_site,
}


_LAST_ERROR: Dict[str, str] = {"msg": ""}


def last_error() -> str:
    return _LAST_ERROR.get("msg", "")


def render(template: dict, out_dir: Optional[str] = None) -> Tuple[Optional[str], str]:
    mermaid = _mermaid(template)
    _LAST_ERROR["msg"] = ""
    try:
        from diagrams import Cluster, Diagram, Edge  # type: ignore
        from diagrams.onprem.client import Users  # type: ignore
    except Exception as e:
        _LAST_ERROR["msg"] = f"import failed: {type(e).__name__}: {e}"
        return None, mermaid

    if not shutil.which("dot"):
        _LAST_ERROR["msg"] = "Graphviz `dot` not on PATH"
        return None, mermaid

    try:
        out_dir = out_dir or _writable_tempdir()
        out_name = os.path.join(out_dir, "architecture")
        workload = template.get("name", "architecture")
        title = f"{workload.replace('_', ' ').title()} — AWS Architecture"

        graph_attr = {
            "splines": "ortho",
            "bgcolor": "white",
            "pad": "0.5",
            "nodesep": "0.7",
            "ranksep": "1.0",
            "fontname": "Helvetica",
            "fontsize": "16",
            "labelloc": "t",
        }
        node_attr = {"fontname": "Helvetica", "fontsize": "12"}
        edge_attr = {"fontname": "Helvetica", "fontsize": "11", "color": "#555555"}

        with Diagram(
            title,
            show=False,
            filename=out_name,
            outformat="png",
            direction="LR",
            graph_attr=graph_attr,
            node_attr=node_attr,
            edge_attr=edge_attr,
        ):
            tier_nodes: Dict[str, Dict[str, Any]] = {t: {} for t in _TIER_ORDER}
            # bucket resources by tier
            resources_by_tier: Dict[str, List[dict]] = {t: [] for t in _TIER_ORDER}
            for r in template.get("resources", []):
                mapped = _NODE_MAP.get(r["type"])
                if not mapped:
                    continue
                resources_by_tier[mapped[2]].append(r)

            # user / client node outside clusters
            user_node = Users("Client")
            tier_nodes["_user"] = user_node  # type: ignore

            # build clusters in tier order
            for tier in _TIER_ORDER:
                if not resources_by_tier[tier]:
                    continue
                cluster_attr = {
                    "bgcolor": _TIER_BG[tier],
                    "style": "rounded",
                    "pencolor": "#888888",
                    "fontname": "Helvetica-Bold",
                    "fontsize": "13",
                }
                with Cluster(_TIER_LABELS[tier], graph_attr=cluster_attr):
                    for r in resources_by_tier[tier]:
                        module, cls_name, _ = _NODE_MAP[r["type"]]
                        try:
                            mod = importlib.import_module(f"diagrams.aws.{module}")
                            cls = getattr(mod, cls_name)
                            label = _safe_label(r["name"])
                            key = f"{r['type']}__{r['name']}"
                            tier_nodes[tier][key] = cls(label)
                        except Exception:
                            continue

            # Wire it up based on workload
            wiring = _WIRING.get(workload, _wire_generic)
            wiring(tier_nodes, Edge)  # type: ignore[arg-type]

        png_path = f"{out_name}.png"
        if os.path.exists(png_path):
            return png_path, mermaid
        _LAST_ERROR["msg"] = f"rendered but PNG missing at {png_path}"
    except Exception as e:
        _LAST_ERROR["msg"] = f"{type(e).__name__}: {e}"
    return None, mermaid
