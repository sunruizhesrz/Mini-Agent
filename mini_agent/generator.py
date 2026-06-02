"""Code generator — parse architecture docs, produce project scaffold.

Generic: adapts to any architecture document, not just the Space Fractions format.
All hardcoded assumptions about document structure have been replaced with
flexible detection strategies."""

from __future__ import annotations

import json
import re
from pathlib import Path


# ═══════════════════════════════════════════════════════════════
# Phase 1: Parse Architecture_Documentation.md
# ═══════════════════════════════════════════════════════════════

def parse_arch_doc(filepath: str) -> dict:
    with open(filepath, encoding="utf-8") as f:
        text = f.read()

    # ── Split into sections by heading ─────────────────────────
    # Accept any heading style: "# A.", "# 1.", "## Overview", etc.
    sections = _split_by_headings(text)

    # ── Project name: try multiple strategies ──────────────────
    project = _extract_project_name(text, sections)

    # ── Architectural style ────────────────────────────────────
    style = _extract_arch_style(text)

    # ── Components: detect from architecture overview section ──
    components = _extract_components(text, sections)

    # ── Tech stack: detect from technology section ─────────────
    stack = _extract_tech_stack(text, sections)

    # ── API endpoints: extract from OpenAPI/Swagger blocks ─────
    endpoints = _extract_api_endpoints(text)
    endpoints = _dedup(endpoints, ("path", "method"))

    # ── gRPC services ──────────────────────────────────────────
    proto_services = _extract_proto_services(text)

    # ── SQL tables ─────────────────────────────────────────────
    tables = _extract_sql_tables(text)
    tables = _dedup(tables, ("name",))

    # ── K8s resources ──────────────────────────────────────────
    k8s_resources = _extract_k8s_resources(text)

    # ── Traceability matrix ────────────────────────────────────
    matrix = _extract_traceability(text, sections)

    return {
        "project_name": project,
        "architectural_style": style,
        "components": components,
        "stack": stack,
        "endpoints": endpoints,
        "proto_services": proto_services,
        "tables": tables,
        "k8s_resources": k8s_resources,
        "traceability": matrix,
    }


# ── Section splitting (generic) ────────────────────────────────

def _split_by_headings(text: str) -> dict[str, str]:
    """Split text by any top-level heading pattern. Returns {heading_key: body_text}."""
    # Match: "# A. Title", "# 1. Title", "## Architecture Overview", etc.
    heading_re = re.compile(
        r'^(#{1,2})\s+(?:([A-Za-z0-9]+)\.\s+)?(.+)$', re.MULTILINE
    )
    matches = list(heading_re.finditer(text))
    if not matches:
        # No structured headings found — return entire text as one section
        return {"_whole": text}

    sections = {}
    for i, m in enumerate(matches):
        key = m.group(2) or m.group(3).strip().lower().replace(" ", "_")[:20]
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        # Use shorter key if duplicate
        orig_key = key
        n = 2
        while key in sections:
            key = f"{orig_key}_{n}"
            n += 1
        sections[key] = body

    return sections


# ── Project name extraction ────────────────────────────────────

def _extract_project_name(text: str, sections: dict) -> str:
    """Try multiple strategies to find project name. Falls back to directory name."""
    strategies = [
        # Strategy 1: "The X system is a ..."
        (r'The\s+([\w\s]+?)\s+(?:system|application|project|platform)\s+is', 1),
        # Strategy 2: "# Project: Name" or "Project Name: X"
        (r'#\s*(?:Project:?\s*)?([\w\s&]+?)(?:\n|$)', 1),
        # Strategy 3: First heading
        (r'^#\s+(?:[A-Za-z0-9]+\.\s+)?(.+)$', 1),
        # Strategy 4: "project_name" in any key-value pair
        (r'project[_\s]name[:\s]+([\w\s]+)', 1),
    ]
    for pattern, group in strategies:
        m = re.search(pattern, text, re.MULTILINE)
        if m:
            name = m.group(group).strip()
            # Filter out obviously wrong matches (>80 chars or contains markdown)
            if 1 < len(name) < 80 and "`" not in name and "[" not in name:
                return name

    # Fallback: use the first heading from any section
    for body in sections.values():
        first_line = body.split("\n")[0].strip()
        first_line = re.sub(r'^#+\s*', '', first_line)
        if 2 < len(first_line) < 80:
            return first_line

    return Path.cwd().name.replace("-", " ").replace("_", " ").title()


# ── Architecture style extraction ──────────────────────────────

def _extract_arch_style(text: str) -> str:
    patterns = [
        r'(?:architectural|architecture)\s+style\s*(?:is|:)\s*(\S[\w\s/-]+)',
        r'(?:chosen|selected)\s+(?:architectural\s+)?style\s*:\s*(\S[\w\s/-]+)',
        r'(?:follows|uses|adopts)\s+(?:an?\s+)?(\w+(?:\s+\w+){0,2})\s+architect',
        r'architecture\s*[–\-:]\s*(\w+(?:\s+\w+){0,2})',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1).strip().split("\n")[0].strip()  # take only first line
    return "Monolith"


# ── Component extraction ───────────────────────────────────────

def _extract_components(text: str, sections: dict) -> list[dict]:
    """Detect components from architecture overview or component listing sections."""
    components = []

    # Strategy 1: Look for list items with component-like names
    # Only match items whose name ends with a well-known component suffix
    for body in sections.values():
        for m in re.finditer(
            r'(?:^|\n)\s*(?:\*|[-•])\s+\*?\*?(\w+(?:Component|Service|Module|Microservice))\*?\*?\s*[:\-–—]\s*(.+?)(?:\n|$)',
            body, re.MULTILINE
        ):
            name = m.group(1)
            # Strip ONE suffix only
            for suffix in ("Component", "Microservice", "Service", "Module"):
                if name.endswith(suffix):
                    name = name[:-len(suffix)]
                    break
            if len(name) > 1:
                components.append({"name": name, "description": m.group(2).strip()})

    # Deduplicate by name
    seen = set()
    result = []
    for c in components:
        if c["name"] not in seen:
            seen.add(c["name"])
            result.append(c)
    return result


# ── Tech stack extraction ──────────────────────────────────────

# Mapping of common label patterns → stack key
_TECH_LABEL_MAP = [
    # Ordered from most specific to least. First match wins.
    (r'container|docker\s+runtime', 'runtime'),
    (r'language|runtime\s+environment|programming\s+language', 'lang'),
    (r'(?:web\s+)?framework', 'fw'),
    (r'persistence|database|db\b|storage\s+engine', 'db'),
    (r'cache|caching', 'cache'),
    (r'messag(?:e|ing)|broker|queue', 'broker'),
    (r'authentication|auth', 'auth'),
    (r'observability|monitoring|telemetry', 'observability'),
    (r'ci/cd|deployment\s+pipeline|continuous\s+integration', 'cicd'),
    (r'infrastructure|infra|provisioning', 'infra'),
    (r'search|indexing', 'search'),
    (r'rpc|http\s+protocol|api\s+style|communication\s+protocol', 'rpc'),
]

_BASE_STACK = {"lang": "", "fw": "", "db": "", "cache": "", "broker": "",
               "runtime": "", "auth": "", "observability": "", "cicd": "",
               "infra": "", "search": "", "rpc": ""}


def _extract_tech_stack(text: str, sections: dict) -> dict:
    """Detect tech stack by scanning for key-value patterns in technology sections."""
    stack = dict(_BASE_STACK)

    # Find the most tech-heavy section
    tech_scores = {}
    for key, body in sections.items():
        score = sum(1 for pat, _ in _TECH_LABEL_MAP if re.search(pat, body, re.IGNORECASE))
        tech_scores[key] = score

    # Use sections with technology mentions, sorted by relevance
    relevant = sorted(
        [(k, v) for k, v in sections.items() if tech_scores.get(k, 0) > 0],
        key=lambda x: tech_scores.get(x[0], 0), reverse=True
    )

    if not relevant:
        # Fall back to scanning entire text
        relevant = [("_whole", text)]

    # Extract key:value pairs using flexible patterns
    for _, body in relevant:
        for line in body.split("\n"):
            line = line.strip()

            # Skip obvious non-tech lines
            if not line or len(line) < 8:
                continue
            if re.match(r'^[|#]', line) or re.search(r'(?:Risk|Threat|SLO|RTO|RPO|Mitigation)', line, re.IGNORECASE):
                continue

            # Pattern 1: "* Label: Value (Justification...)" or "- Label: Value"
            kv_match = re.match(r'(?:\*|[-•])\s+\*?\*?(.+?)\*?\*?\s*:\s*(.+?)(?:\s*\(|$)', line)
            if kv_match:
                label, value = kv_match.group(1).lower(), kv_match.group(2).strip()
                _assign_stack_value(stack, label, value)
                continue

            # Pattern 2: "Label: Value" — but only if label looks like a technology category
            kv_match = re.match(r'([\w\s/&]{4,40}?)\s*:\s*([\w\s.]+(?:\d+)?)', line)
            if kv_match:
                label, value = kv_match.group(1).lower().strip(), kv_match.group(2).strip()
                # Only assign if label or value contains a known tech keyword
                combined = f"{label} {value}".lower()
                if any(kw in combined for kw in (
                    "node", "python", "java", "express", "flask", "django", "spring",
                    "postgres", "mysql", "mongo", "redis", "rabbitmq", "kafka",
                    "docker", "kubernetes", "jenkins", "terraform", "prometheus",
                    "oauth", "jwt", "nginx", "elasticsearch",
                )):
                    _assign_stack_value(stack, label, value)

        # Pattern 3: Table rows in tech section
        for row in re.finditer(
            r'\|\s*([\w.]+(?:\s+[\w.]+){0,3})\s*\|\s*(\d+(?:\.\d+)?[^\|]*)\s*\|',
            body
        ):
            cell = row.group(1).strip().lower()
            val = row.group(2).strip()
            # Only if cell looks like a technology name
            if any(kw in cell for kw in (
                "node", "python", "express", "postgres", "mysql", "redis",
                "rabbitmq", "docker", "elasticsearch", "prometheus", "jenkins",
                "terraform", "nginx",
            )):
                _assign_stack_value(stack, cell, val)
    # Clean up: remove version suffixes for cleaner keys
    for k, v in list(stack.items()):
        if v:
            # Keep version if present
            ver_match = re.search(r'(\d+(?:\.\d+)?)', v)
            if ver_match:
                stack[k] = f"{v.split()[0]} {ver_match.group(1)}" if " " in v else v

    return stack


def _assign_stack_value(stack: dict, label: str, value: str):
    """Match a label to a stack key and assign the value."""
    for pat, key in _TECH_LABEL_MAP:
        if re.search(pat, label, re.IGNORECASE):
            # Clean value: strip version ranges, justifications
            clean = re.sub(r'\s*\(.*?\)', '', value)  # remove (Justification...)
            clean = re.sub(r'\s*\d+[-–]\d+', '', clean)  # remove "18-20" range
            clean = re.sub(r'\s*recommended\s*', '', clean, flags=re.IGNORECASE)
            clean = clean.strip().split(",")[0].strip()  # take first option
            if clean and len(clean) < 50:
                stack[key] = clean
            return


# ── API endpoint extraction ────────────────────────────────────

def _extract_api_endpoints(text: str) -> list[dict]:
    """Extract REST endpoints from OpenAPI/Swagger YAML blocks."""
    endpoints = []
    for yb in re.finditer(r'```(?:yml|yaml)\n(.*?)```', text, re.DOTALL):
        yt = yb.group(1)
        if "openapi:" not in yt.lower() and "swagger:" not in yt.lower():
            if "apiVersion:" in yt or "kind:" in yt:
                continue  # skip K8s
            # Check if it has path patterns anyway
            has_paths = bool(re.search(r'^\s*/\S+:\s*$', yt, re.MULTILINE))
            if not has_paths:
                continue

        for pm in re.finditer(r'^\s*(/\S+):\s*$', yt, re.MULTILINE):
            path = pm.group(1)
            # Find the HTTP method on the next few lines
            remaining = yt[pm.end():pm.end() + 200]
            mm = re.search(r'^\s*(get|post|put|delete|patch|options|head)\s*:', remaining, re.MULTILINE)
            if mm:
                endpoints.append({"path": path, "method": mm.group(1).upper()})

    return endpoints


# ── gRPC/Protobuf extraction ───────────────────────────────────

def _extract_proto_services(text: str) -> list[dict]:
    services = []
    for pb in re.finditer(r'```proto\n(.*?)```', text, re.DOTALL):
        pt = pb.group(1)
        for sm in re.finditer(r'service\s+(\w+)\s*\{(.*?)\}', pt, re.DOTALL):
            rpcs = []
            for rm in re.finditer(r'rpc\s+(\w+)\s*\((\w+)\)\s*returns\s*\((\w+)\)', sm.group(2)):
                rpcs.append({"name": rm.group(1), "request": rm.group(2), "response": rm.group(3)})
            services.append({"name": sm.group(1), "rpcs": rpcs})
        for mm in re.finditer(r'message\s+(\w+)\s*\{(.*?)\}', pt, re.DOTALL):
            fields = []
            for fm in re.finditer(r'(\w+)\s+(\w+)\s*=\s*(\d+)', mm.group(2)):
                fields.append({"name": fm.group(2), "type": fm.group(1), "number": int(fm.group(3))})
            services.append({"name": mm.group(1), "fields": fields, "is_message": True})
    return services


# ── SQL table extraction ───────────────────────────────────────

def _split_sql_columns(columns_text: str) -> list[str]:
    """Split CREATE TABLE column definitions, respecting commas inside parentheses."""
    parts = []
    depth = 0
    current = ""
    for ch in columns_text:
        if ch == ',' and depth == 0:
            parts.append(current)
            current = ""
        else:
            if ch == '(': depth += 1
            elif ch == ')': depth -= 1
            current += ch
    if current.strip():
        parts.append(current)
    return parts


def _extract_sql_tables(text: str) -> list[dict]:
    tables = []
    for sb in re.finditer(r'```sql\n(.*?)```', text, re.DOTALL):
        sql = sb.group(1)
        for tm in re.finditer(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\(([\s\S]*?)\);', sql, re.IGNORECASE):
            cols = []
            col_lines = _split_sql_columns(tm.group(2))
            for col_line in col_lines:
                col_line = col_line.strip()
                # Handle constraints and multi-word types
                if re.match(r'^\s*(?:PRIMARY|FOREIGN|UNIQUE|CHECK|CONSTRAINT|INDEX)\b', col_line, re.IGNORECASE):
                    continue  # skip standalone constraint lines
                cm = re.match(r'\s*(\w+)\s+([\w\s(),]+?)(?:\s+(?:NOT\s+NULL|PRIMARY\s+KEY|REFERENCES|DEFAULT)\s*.*)?$',
                              col_line, re.IGNORECASE)
                if cm:
                    cols.append({"name": cm.group(1), "type": cm.group(2).strip().upper()})
            if cols:
                tables.append({"name": tm.group(1), "columns": cols})
    return tables


# ── K8s resource extraction ────────────────────────────────────

def _extract_k8s_resources(text: str) -> list[dict]:
    resources = []
    for yb in re.finditer(r'```(?:yml|yaml)\n(.*?)```', text, re.DOTALL):
        yt = yb.group(1)
        if re.search(r'apiVersion:\s*', yt) and re.search(r'kind:\s*\w+', yt):
            kind_m = re.search(r'kind:\s*(\w+)', yt)
            name_m = re.search(r'name:\s*(\S+)', yt)
            resources.append({
                "kind": kind_m.group(1) if kind_m else "Unknown",
                "name": name_m.group(1) if name_m else "unnamed",
                "raw": yt,
            })
    return resources


# ── Traceability matrix extraction ─────────────────────────────

def _extract_traceability(text: str, sections: dict) -> list[dict]:
    matrix = []
    # Find any markdown table with requirement-like IDs
    for body in sections.values():
        lines = body.split("\n")
        in_table = False
        for line in lines:
            if re.search(r'(?:Requirement|ID|需求)', line, re.IGNORECASE) and "|" in line:
                in_table = True
                continue
            if in_table:
                if "---" in line:
                    continue
                if line.startswith("|"):
                    cells = [c.strip() for c in line.split("|")[1:-1]]
                    # Check if first cell looks like a requirement ID
                    if cells and re.match(r'[A-Z]{2,4}[-\s]\d+', cells[0]):
                        matrix.append({
                            "id": cells[0],
                            "text": cells[1] if len(cells) > 1 else "",
                            "component": cells[3] if len(cells) > 3 else "",
                        })
                else:
                    in_table = False  # table ended
    return matrix


# ═══════════════════════════════════════════════════════════════
# Phase 2: Parse Architecture_View.md (PlantUML diagrams)
# ═══════════════════════════════════════════════════════════════

def parse_arch_view(filepath: str) -> dict:
    with open(filepath, encoding="utf-8") as f:
        text = f.read()

    diagrams: list[dict] = []
    # Support both ```plantuml and @startuml without code fences
    blocks = []
    for pm in re.finditer(r'```plantuml\n(.*?)```', text, re.DOTALL):
        blocks.append(pm.group(1))
    if not blocks:
        # Try raw @startuml...@enduml without code fences
        for pm in re.finditer(r'@startuml\s+\w+\n(.*?)@enduml', text, re.DOTALL):
            blocks.append(pm.group(0))

    for uml in blocks:
        dia: dict = {"raw": uml, "classes": [], "relations": [], "components": [],
                     "actors": [], "usecases": [], "states": [], "entities": []}

        m = re.search(r'@startuml\s+(\w+)', uml)
        dia["type"] = m.group(1) if m else "Unknown"

        # ── Class diagram: classes with fields and methods ──
        for cm in re.finditer(r'(?:abstract\s+)?class\s+(\w+)\s*(?:\{([^}]*)\})?', uml):
            fields, methods = [], []
            body = cm.group(2) or ""
            for line in body.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Visibility: - private, + public, # protected, ~ package
                vis, rest = "+", line
                vm = re.match(r'([-+#~])\s+(.+)', line)
                if vm:
                    vis, rest = vm.group(1), vm.group(2)

                # Method: name(params): returnType
                mm = re.match(r'(?:(\{method\})\s*)?(\w+)\s*\(\s*([^)]*)\s*\)\s*(?::\s*(.+))?', rest)
                if mm:
                    methods.append({
                        "name": mm.group(2), "params": mm.group(3) or "",
                        "return_type": (mm.group(4) or "void").strip(),
                        "visibility": vis,
                    })
                    continue

                # Field: name : type  or  name type
                fm = re.match(r'(\w+)\s*:\s*(.+)', rest)
                if fm:
                    fields.append({"name": fm.group(1), "type": fm.group(2).strip(), "visibility": vis})
                    continue
                # Fallback: just a field name with type
                fm2 = re.match(r'(\w+)\s+(\w[\w<>,\s]*)', rest)
                if fm2 and "(" not in line:
                    fields.append({"name": fm2.group(1), "type": fm2.group(2).strip(), "visibility": vis})

            dia["classes"].append({"name": cm.group(1), "fields": fields, "methods": methods})

        # ── Relations: A -- B, A --> B, A --* B ──
        for rm in re.finditer(r'(\w+)\s*(--\*?|\.\.>|--?>|\.\.|--|-->)\s*(\w+)', uml):
            lhs, arrow, rhs = rm.group(1), rm.group(2), rm.group(3)
            if lhs.upper() not in ("LEFT", "RIGHT", "TOP", "BOTTOM", "NOTE", "TO", "OF", "END"):
                dia["relations"].append({"from": lhs, "to": rhs, "type": arrow})

        # ── Sequence diagram: participants and messages ──
        for pm in re.finditer(r'participant\s+(\w+)(?:\s+as\s+"?(\w+)"?)?', uml):
            dia.setdefault("participants", []).append(pm.group(1))
        for msg in re.finditer(r'(\w+)\s*->>?\s*(\w+)\s*:\s*(.+)', uml):
            dia["relations"].append({
                "from": msg.group(1), "to": msg.group(2),
                "type": "message", "label": msg.group(3).strip(),
            })

        # ── Component/artifact ──
        for cm in re.finditer(r'(?:artifact|component)\s+["\']?(\w+)["\']?', uml):
            dia["components"].append(cm.group(1))

        # ── Actor ──
        for am in re.finditer(r'actor\s+(\w+)(?:\s+as\s+"[^"]*")?', uml):
            dia["actors"].append(am.group(1))

        # ── Use case ──
        for um in re.finditer(r'usecase\s+(?:"([^"]*)"|(\w+))', uml):
            dia["usecases"].append(um.group(1) or um.group(2))

        # ── State ──
        for sm in re.finditer(r'state\s+"?(\w+)"?', uml):
            dia["states"].append(sm.group(1))

        # ── ERD: entity with attributes ──
        for em in re.finditer(r'entity\s+"?(\w+)"?\s*\{(.*?)\}', uml, re.DOTALL):
            attrs = []
            for line in em.group(2).strip().split("\n"):
                am = re.match(r'\s*([*+~#-])?\s*(\w+)\s*:\s*(\w+)', line)
                if am:
                    attrs.append({"name": am.group(2), "type": am.group(3)})
            dia["entities"].append({"name": em.group(1), "attributes": attrs})

        diagrams.append(dia)

    return {"diagrams": diagrams}


# ═══════════════════════════════════════════════════════════════
# Phase 3: Merge into structured JSON
# ═══════════════════════════════════════════════════════════════

def merge_to_json(doc: dict, view: dict) -> dict:
    classes = []
    relations = []
    # Valid entity types for code generation modules
    CODE_ENTITY_TYPES = {"class", "component", "container", "participant", None}

    for d in view.get("diagrams", []):
        # Only include classes that can become code modules
        for cls in d.get("classes", []):
            ctype = cls.get("type", "class")
            if cls.get("type", ctype) in ("actor", "usecase", "state"):
                continue
            if re.match(r'^\w+\d+$', cls["name"]):  # "game1" etc
                continue
            if cls not in classes:
                classes.append(cls)

        relations.extend(d.get("relations", []))
        for cname in d.get("components", []):
            if not any(c["name"] == cname for c in classes):
                classes.append({"name": cname, "fields": [], "methods": [], "type": "component"})
        for ename in d.get("participants", []):
            if not any(c["name"] == ename for c in classes):
                classes.append({"name": ename, "fields": [], "methods": [], "type": "participant"})

    # Merge prose components with diagram classes using fuzzy name matching
    _merge_component_info(doc.get("components", []), classes)

    return {
        "project_name": doc["project_name"],
        "architectural_style": doc["architectural_style"],
        "stack": doc["stack"],
        "components": doc["components"],
        "endpoints": doc["endpoints"],
        "tables": doc["tables"],
        "k8s_resources": doc["k8s_resources"],
        "proto_services": doc["proto_services"],
        "classes": classes,
        "relations": relations,
        "traceability": doc["traceability"],
    }


def _merge_component_info(prose_comps: list[dict], classes: list[dict]):
    """Fuzzy-merge prose component descriptions into diagram classes."""
    if not prose_comps:
        return
    for cls in classes:
        cn = cls["name"].lower()
        for pc in prose_comps:
            pn = pc["name"].lower()
            # Match: "Game" ↔ "gamecomponent", "GameComponent", "game"
            if pn in cn or cn in pn or _name_similarity(cn, pn) > 0.6:
                cls.setdefault("_description", pc.get("description", ""))
                break


def _name_similarity(a: str, b: str) -> float:
    """Simple trigram similarity for fuzzy name matching."""
    a_tri = set(a[i:i+3] for i in range(len(a)-2))
    b_tri = set(b[i:i+3] for i in range(len(b)-2))
    if not a_tri or not b_tri:
        return 0.0
    return len(a_tri & b_tri) / len(a_tri | b_tri)


# ═══════════════════════════════════════════════════════════════
# Phase 4: Generate project scaffold
# ═══════════════════════════════════════════════════════════════

def generate_project(ctx: dict, output_dir: str) -> list[str]:
    written: list[str] = []
    out = Path(output_dir)
    proj = ctx["project_name"].lower().replace(" ", "-").replace("_", "-")

    # ── Detect language: first from stack, then infer ──────────
    lang = _detect_language(ctx)
    stack = ctx.get("stack", {})

    # ── Build module list (generic: no Component suffix assumption) ──
    modules, class_by_mod, table_by_mod = _build_modules(ctx)

    # ── Create directories ─────────────────────────────────────
    dirs = ["src/common/config", "src/common/middleware", "src/common/utils",
            "api", "k8s", "sql", "tests", "src/public"]
    for m in modules:
        for sub in ["controllers", "models", "routes", "services"]:
            dirs.append(f"src/{m}/{sub}")
    for d in dirs:
        (out / d).mkdir(parents=True, exist_ok=True)

    # ── Generate language-specific files ───────────────────────
    if lang == "python":
        fw = (ctx.get("stack", {}).get("fw", "") or "").lower()
        if "django" in fw:
            written += _gen_django_files(out, ctx, modules, class_by_mod, table_by_mod)
        else:
            written += _gen_python_files(out, ctx, modules, class_by_mod, table_by_mod)
    else:
        written += _gen_node_files(out, ctx, modules, class_by_mod, table_by_mod)

    # ── Language-agnostic config files ─────────────────────────
    written += _gen_sql_files(out, ctx)
    written += _gen_openapi(out, ctx)
    written += _gen_k8s_files(out, ctx)
    written += _gen_docker_files(out, ctx, lang)
    written += _gen_tests(out, ctx, modules, lang)
    written += _gen_readme(out, ctx, modules)
    written += _gen_frontend(out, ctx, modules)
    written += _gen_dotfiles(out, ctx)
    write(out, "structured_context.json", json.dumps(ctx, indent=2, default=str))
    written.append("structured_context.json")

    return written


def _detect_language(ctx: dict) -> str:
    """Detect target language from tech stack, default to node."""
    stack_str = json.dumps(ctx.get("stack", {})).lower()
    hints = [
        ("python", ["python", "flask", "django", "fastapi"]),
        ("go", ["go ", "golang", "gin ", "echo ", "fiber"]),
        ("java", ["java", "spring", "maven", "gradle"]),
        ("rust", ["rust", "actix", "rocket", "axum"]),
        ("node", ["node", "javascript", "express", "nestjs", "typescript", "js"]),
    ]
    for lang, keywords in hints:
        if any(kw in stack_str for kw in keywords):
            return lang
    # Check section text too
    desc = ctx.get("project_name", "").lower()
    if "python" in desc or "flask" in desc:
        return "python"
    return "node"  # default


# ── Module building (generic) ───────────────────────────────────

def _build_modules(ctx: dict) -> tuple[list[str], dict, dict]:
    """Build module list from classes, tables, AND prose components."""
    classes = ctx.get("classes", [])
    class_by_mod: dict[str, dict] = {}

    # Include prose components as modules (they may not have PlantUML class defs)
    for comp in ctx.get("components", []):
        mn = comp["name"].lower()
        if mn not in class_by_mod:
            class_by_mod[mn] = {"name": comp["name"], "fields": [], "methods": [],
                                "type": "component",
                                "_description": comp.get("description", "")}

    for cls in classes:
        cname = cls["name"]
        ctype = cls.get("type", "class")

        # Skip non-module entities: actors, usecases, states, participants with numbers
        if ctype in ("actor", "usecase", "state"):
            continue
        if re.match(r'^\w+\d+$', cname):  # "game1", "user1", "question1" — object instances
            continue
        if len(cname) <= 2:  # too short to be a real module
            continue

        # Derive module name: strip known suffixes, lowercase
        name = cname
        for suffix in ("Component", "Container", "Service", "Module", "Microservice",
                       "Server", "Client", "Controller", "Repository", "Manager"):
            if name.endswith(suffix) and len(name) > len(suffix):
                name = name[:-len(suffix)]
                break
        mn = name.lower()
        if mn not in class_by_mod:
            class_by_mod[mn] = {"name": name, "fields": list(cls.get("fields", [])),
                                "methods": list(cls.get("methods", [])),
                                "type": cls.get("type", "class")}
        else:
            existing = class_by_mod[mn]
            if cls.get("fields") and not existing["fields"]:
                existing["fields"] = list(cls["fields"])
            if cls.get("methods") and not existing["methods"]:
                existing["methods"] = list(cls["methods"])

    table_by_mod: dict[str, dict] = {}
    for t in ctx.get("tables", []):
        mn = t["name"].rstrip("s").lower().replace("_", "")
        table_by_mod[mn] = t
        # Also try fuzzy match with class names
        for cm in list(class_by_mod.keys()):
            if _name_similarity(mn, cm) > 0.5 and mn not in class_by_mod:
                class_by_mod[mn] = {"name": cm.capitalize(), "fields": [
                    {"name": c["name"], "type": c["type"]} for c in t["columns"]
                ], "methods": []}

    modules = sorted(set(list(class_by_mod.keys()) + list(table_by_mod.keys())))
    if not modules:
        modules = ["main"]

    return modules, class_by_mod, table_by_mod


# ── Node.js generation ─────────────────────────────────────────

def _gen_node_files(out, ctx, modules, class_by_mod, table_by_mod) -> list[str]:
    written = []
    proj = ctx["project_name"].lower().replace(" ", "-").replace("_", "-")
    stack = ctx.get("stack", {})

    # package.json — dynamic dependencies based on stack
    pkg = {
        "name": proj,
        "version": "1.0.0",
        "description": f"{ctx['project_name']} — generated by Code Agent",
        "main": "src/server.js",
        "scripts": {"start": "node src/server.js", "dev": "nodemon src/server.js", "test": "jest --coverage"},
        "dependencies": {},
        "devDependencies": {"jest": "^29.7.0", "supertest": "^6.3.0", "nodemon": "^3.0.0"},
    }
    # Express is default for Node.js
    fw_lower = (stack.get("fw", "") or "").lower()
    if "express" in fw_lower or not stack.get("fw"):
        pkg["dependencies"]["express"] = "^4.18.0"
    elif "koa" in fw_lower:
        pkg["dependencies"]["koa"] = "^2.15.0"
        pkg["dependencies"]["koa-router"] = "^12.0.0"
    elif "fastify" in fw_lower:
        pkg["dependencies"]["fastify"] = "^4.26.0"
    elif "hapi" in fw_lower:
        pkg["dependencies"]["@hapi/hapi"] = "^21.3.0"
    elif "nestjs" in fw_lower:
        pkg["dependencies"]["@nestjs/core"] = "^10.3.0"
        pkg["dependencies"]["@nestjs/common"] = "^10.3.0"
        pkg["dependencies"]["@nestjs/platform-express"] = "^10.3.0"

    pkg["dependencies"]["dotenv"] = "^16.3.0"
    pkg["dependencies"]["cors"] = "^2.8.5"
    pkg["dependencies"]["helmet"] = "^7.1.0"

    db_lower = (stack.get("db", "") or "").lower()
    if any(kw in db_lower for kw in ("postgres", "postgresql", "pg")):
        pkg["dependencies"]["pg"] = "^8.11.0"
        pkg["dependencies"]["sequelize"] = "^6.32.0"
    elif "mysql" in db_lower or "mariadb" in db_lower:
        pkg["dependencies"]["mysql2"] = "^3.9.0"
        pkg["dependencies"]["sequelize"] = "^6.32.0"
    elif "sqlite" in db_lower:
        pkg["dependencies"]["sqlite3"] = "^5.1.0"
        pkg["dependencies"]["sequelize"] = "^6.32.0"
    elif "mongo" in db_lower or "mongodb" in db_lower:
        pkg["dependencies"]["mongoose"] = "^8.1.0"

    cache_lower = (stack.get("cache", "") or "").lower()
    if "redis" in cache_lower:
        pkg["dependencies"]["ioredis"] = "^5.3.0"
    elif "memcached" in cache_lower:
        pkg["dependencies"]["memcached"] = "^2.2.0"

    broker_lower = (stack.get("broker", "") or "").lower()
    if any(kw in broker_lower for kw in ("rabbitmq", "rabbit")):
        pkg["dependencies"]["amqplib"] = "^0.10.3"
    elif "kafka" in broker_lower:
        pkg["dependencies"]["kafkajs"] = "^2.2.0"

    write(out, "package.json", json.dumps(pkg, indent=2))
    written.append("package.json")

    # app.js — framework-aware entry
    fw = stack.get("fw", "Express.js").lower()
    if "express" in fw or not stack.get("fw"):
        app_js = _gen_express_app(modules)
    elif "koa" in fw:
        app_js = _gen_koa_app(modules)
    else:
        app_js = _gen_express_app(modules)  # default

    write(out, "src/app.js", app_js)
    written.append("src/app.js")

    server_js = f"""require('dotenv').config();
const app = require('./app');
const PORT = process.env.PORT || 3000;

// Wait for database sync (handled by app.js), then start listening
(app.dbReady || Promise.resolve()).then(() => {{
  app.listen(PORT, () => console.log('{ctx["project_name"]} server running on port ' + PORT));
}});
"""
    write(out, "src/server.js", server_js)
    written.append("src/server.js")

    # Common files
    db_tech = stack.get("db", "PostgreSQL")
    db_lower = (db_tech or "").lower()
    if any(kw in db_lower for kw in ("postgres", "postgresql", "mysql", "mariadb", "sqlite")):
        write(out, "src/common/config/database.js",
              f"// Database: {db_tech}\n"
              "const { Sequelize } = require('sequelize');\n"
              f"const sequelize = new Sequelize(process.env.DATABASE_URL || 'postgresql://localhost:5432/{proj}', {{ logging: false }});\n"
              "module.exports = { sequelize };\n")
    elif "mongo" in db_lower or "mongodb" in db_lower:
        write(out, "src/common/config/database.js",
              "const mongoose = require('mongoose');\n"
              f"mongoose.connect(process.env.MONGODB_URI || 'mongodb://localhost:27017/{proj}');\n"
              "module.exports = mongoose;\n")

    if "redis" in (stack.get("cache", "") or "").lower():
        write(out, "src/common/config/redis.js",
              "const Redis = require('ioredis');\n"
              "const redis = new Redis(process.env.REDIS_URL || 'redis://localhost:6379');\n"
              "module.exports = redis;\n")

    write(out, "src/common/middleware/error-handler.js",
          "const { ApiError } = require('../utils/api-error');\n"
          "const errorHandler = (err, req, res, _next) => {\n"
          "  const status = err.statusCode || 500;\n"
          "  res.status(status).json({ error: { message: err.message, status } });\n"
          "};\nmodule.exports = { errorHandler };\n")
    write(out, "src/common/middleware/logger.js",
          "const logger = (req, res, next) => {\n"
          "  console.log(`${new Date().toISOString()} ${req.method} ${req.path}`);\n"
          "  next();\n};\nmodule.exports = { logger };\n")
    write(out, "src/common/utils/api-error.js",
          "class ApiError extends Error {\n"
          "  constructor(message, statusCode) { super(message); this.statusCode = statusCode; }\n"
          "}\nmodule.exports = { ApiError };\n")
    written.extend(["src/common/config/database.js", "src/common/config/redis.js",
                    "src/common/middleware/error-handler.js", "src/common/middleware/logger.js",
                    "src/common/utils/api-error.js"])

    # Per-module files
    for m in modules:
        cls = class_by_mod.get(m, {"name": m.capitalize(), "fields": [], "methods": []})
        tbl = table_by_mod.get(m)
        fields = tbl["columns"] if tbl and tbl.get("columns") else (
            cls.get("fields") if cls.get("fields") else [{"name": "id", "type": "SERIAL"}]
        )

        # Model — ORM-aware
        model_js = _gen_node_model(cls["name"], fields, m, proj, db_lower)
        write(out, f"src/{m}/models/{m}.model.js", model_js)

        # Service
        svc = _gen_node_service(cls)
        write(out, f"src/{m}/services/{m}.service.js", svc)

        # Controller
        ctrl = _gen_node_controller(cls, m)
        write(out, f"src/{m}/controllers/{m}.controller.js", ctrl)

        # Routes
        routes = _gen_node_routes(m, cls, ctx.get("endpoints", []))
        write(out, f"src/{m}/routes/{m}.routes.js", routes)

        written.extend([f"src/{m}/models/{m}.model.js", f"src/{m}/services/{m}.service.js",
                        f"src/{m}/controllers/{m}.controller.js", f"src/{m}/routes/{m}.routes.js"])

    return written


def _gen_express_app(modules: list[str]) -> str:
    body = """const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const path = require('path');
const { errorHandler } = require('./common/middleware/error-handler');
const { logger } = require('./common/middleware/logger');

const app = express();
app.use(helmet({
  contentSecurityPolicy: false,  // allow inline scripts for the game page
}));
app.use(cors());
app.use(express.json());
app.use(logger);

// Serve static frontend files
app.use(express.static(path.join(__dirname, 'public')));
"""
    for m in modules:
        body += f"app.use('/api/{m}', require('./{m}/routes/{m}.routes'));\n"
    body += "\napp.get('/health', (req, res) => res.json({ status: 'ok' }));\n"
    # Serve index.html for root path
    body += "\napp.get('/', (req, res) => res.sendFile(path.join(__dirname, 'public', 'index.html')));\n"
    body += "\napp.use(errorHandler);\n\n// Initialize database (auto-sync on import)\nconst { sequelize } = require('./common/config/database');\nconst dbReady = sequelize.sync({ alter: true }).then(() => {}).catch(() => {});\n\nmodule.exports = app;\nmodule.exports.dbReady = dbReady;\n"
    return body


def _gen_koa_app(modules: list[str]) -> str:
    body = """const Koa = require('koa');
const Router = require('koa-router');
const cors = require('@koa/cors');
const bodyParser = require('koa-bodyparser');

const app = new Koa();
const router = new Router();
app.use(cors());
app.use(bodyParser());
"""
    for m in modules:
        body += f"const {m}Router = require('./{m}/routes/{m}.routes');\n"
        body += f"router.use('/api/{m}', {m}Router.routes(), {m}Router.allowedMethods());\n"
    body += "\nrouter.get('/health', (ctx) => { ctx.body = { status: 'ok' }; });\n"
    body += "app.use(router.routes()).use(router.allowedMethods());\n\nmodule.exports = app;\n"
    return body


def _gen_node_model(name: str, fields: list[dict], mod: str, proj: str, db_lower: str) -> str:
    fields_js = ""
    for f in fields:
        dtype = f["type"].upper()
        if any(t in dtype for t in ("INT", "SERIAL", "INTEGER", "NUMBER")):
            js_type = "DataTypes.INTEGER"
            is_int = True
        elif "LIST" in dtype or "ARRAY" in dtype:
            # PlantUML List<string> / ARRAY → JSONB for flexible storage
            js_type = "DataTypes.JSONB"
            is_int = False
        elif "JSON" in dtype:
            js_type = "DataTypes.JSONB"
            is_int = False
        elif "FLOAT" in dtype or "DOUBLE" in dtype or "DECIMAL" in dtype:
            js_type = "DataTypes.FLOAT"
            is_int = False
        elif "BOOL" in dtype:
            js_type = "DataTypes.BOOLEAN"
            is_int = False
        elif "DATE" in dtype or "TIME" in dtype:
            js_type = "DataTypes.DATE"
            is_int = False
        elif "TEXT" in dtype:
            js_type = "DataTypes.TEXT"
            is_int = False
        else:
            js_type = "DataTypes.STRING"
            is_int = False
        if f["name"].lower() == "id":
            pk_parts = ["primaryKey: true"]
            if is_int:
                pk_parts.append("autoIncrement: true")
            pk = ", ".join(pk_parts) + ","
        else:
            pk = ""
        fields_js += f"\n    {f['name']}: {{ type: {js_type}, {pk} }},\n"

    if "mongo" in db_lower:
        return f"""const mongoose = require('mongoose');

const {name}Schema = new mongoose.Schema({{
{fields_js}}}, {{ timestamps: true }});

module.exports = mongoose.model('{name}', {name}Schema);
"""
    else:
        return f"""const {{ DataTypes }} = require('sequelize');
const {{ sequelize }} = require('../../common/config/database');

const {name} = sequelize.define('{name}', {{
{fields_js}}}, {{
  tableName: '{mod}s',
  timestamps: true,
  underscored: true,
}});

module.exports = {name};
"""


def _gen_node_service(cls: dict) -> str:
    methods = cls.get("methods", [])
    svc_methods = ""
    for meth in methods:
        rtype = meth.get('return_type', 'void').strip()
        if rtype in ("void", "Void"):
            svc_methods += (
                f"  async {meth['name']}(data = {{}}) {{\n"
                f"    const result = await {cls['name']}.create(data);\n"
                f"    return result;\n"
                f"  }}\n\n"
            )
        else:
            svc_methods += (
                f"  async {meth['name']}(data = {{}}) {{\n"
                f"    const result = await {cls['name']}.findAll({{ where: data }});\n"
                f"    return result;\n"
                f"  }}\n\n"
            )
    # Always include standard CRUD
    svc_methods += (
        f"  async findAll() {{ return await {cls['name']}.findAll(); }}\n"
        f"  async findById(id) {{ return await {cls['name']}.findByPk(id); }}\n"
        f"  async create(data) {{ return await {cls['name']}.create(data); }}\n"
    )
    return f"""const {cls['name']} = require('../models/{cls['name'].lower()}.model');

class {cls['name']}Service {{
{svc_methods}}}

module.exports = new {cls['name']}Service();
"""


def _gen_node_controller(cls: dict, mod: str) -> str:
    methods = cls.get("methods", [])
    ctrl_methods = ""
    for meth in methods:
        mname = meth['name'].lower()
        # Choose parameter source based on typical REST conventions
        if any(kw in mname for kw in ("create", "register", "submit", "update", "place", "play")):
            params = "req.body"
        elif "id" in mname or "getby" in mname:
            params = "req.params"
        else:
            params = "req.query"
        ctrl_methods += f"  async {meth['name']}(req, res, next) {{\n"
        ctrl_methods += f"    try {{ const result = await service.{meth['name']}({params}); res.json(result); }} catch (e) {{ next(e); }}\n"
        ctrl_methods += "  }\n\n"
    # Always include standard CRUD methods
    ctrl_methods += (
        "  async getAll(req, res, next) {\n"
        "    try { const result = await service.findAll(); res.json(result); } catch (e) { next(e); }\n"
        "  }\n"
        "  async getById(req, res, next) {\n"
        "    try { const result = await service.findById(req.params.id); res.json(result); } catch (e) { next(e); }\n"
        "  }\n"
        "  async create(req, res, next) {\n"
        "    try { const result = await service.create(req.body); res.json(result); } catch (e) { next(e); }\n"
        "  }\n"
    )
    return f"""const service = require('../services/{mod}.service');

class {cls['name']}Controller {{
{ctrl_methods}}}

module.exports = new {cls['name']}Controller();
"""


def _gen_node_routes(mod: str, cls: dict, endpoints: list[dict]) -> str:
    route_methods = ""

    # Match endpoints to module by:
    # 1. path substring matches module name
    # 2. path segment matches a PlantUML method name in this class
    cls_methods = {m["name"].lower() for m in cls.get("methods", [])}
    matched = []
    for ep in endpoints:
        path = ep.get("path", "").lower()
        segments = [s for s in path.strip("/").split("/") if s]
        # Check substring match
        if mod in path:
            matched.append(ep)
        # Check if any path segment matches a method name
        elif any(seg in cls_methods for seg in segments):
            matched.append(ep)
        # Check if class name contains a path segment or vice versa
        elif cls["name"].lower() in path or any(seg in cls["name"].lower() for seg in segments):
            matched.append(ep)

    if matched:
        for ep in matched:
            handler = ep["path"].strip("/").replace("/", "_").replace("-", "_")
            route_methods += f"router.{ep['method'].lower()}('{ep['path']}', controller.{handler});\n"
    # Always include CRUD fallback
    route_methods += "router.get('/', controller.getAll);\n"
    route_methods += "router.get('/:id', controller.getById);\n"
    return f"""const express = require('express');
const router = express.Router();
const controller = require('../controllers/{mod}.controller');

{route_methods}
module.exports = router;
"""


# ── Django generation ──────────────────────────────────────────

def _gen_django_files(out, ctx, modules, class_by_mod, table_by_mod) -> list[str]:
    written = []
    proj = ctx["project_name"].lower().replace(" ", "_").replace("-", "_")
    stack = ctx.get("stack", {})

    # requirements.txt
    deps = ["django", "djangorestframework", "django-cors-headers", "python-dotenv"]
    db = (stack.get("db", "") or "").lower()
    if any(kw in db for kw in ("postgres", "postgresql", "pg")):
        deps += ["psycopg2-binary"]
    elif "mysql" in db or "mariadb" in db:
        deps += ["mysqlclient"]
    if "redis" in (stack.get("cache", "") or "").lower():
        deps.append("django-redis")
    if "kafka" in (stack.get("broker", "") or "").lower():
        deps.append("kafka-python")
    deps += ["gunicorn", "pytest", "pytest-django"]
    write(out, "requirements.txt", "\n".join(deps))
    written.append("requirements.txt")

    # manage.py
    write(out, "manage.py",
          "#!/usr/bin/env python\n"
          '"""Django management script."""\n'
          "import os\nimport sys\n\n"
          "def main():\n"
          f'    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "{proj}.settings")\n'
          "    from django.core.management import execute_from_command_line\n"
          "    execute_from_command_line(sys.argv)\n\n"
          "if __name__ == '__main__':\n"
          "    main()\n")
    written.append("manage.py")

    # Project settings dir
    proj_dir = out / proj
    proj_dir.mkdir(parents=True, exist_ok=True)

    # settings.py
    apps = ",\n".join(f"    '{m}'," for m in modules)
    db_url = f"postgresql://localhost:5432/{proj}"
    write(out, f"{proj}/settings.py",
          f"""import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-change-me")
DEBUG = os.environ.get("DEBUG", "True") == "True"
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
{apps}
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]

ROOT_URLCONF = '{proj}.urls'
WSGI_APPLICATION = '{proj}.wsgi.application'

DATABASES = {{
    'default': {{
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', '{proj}'),
        'USER': os.environ.get('DB_USER', 'postgres'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'postgres'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }}
}}

CACHES = {{
    'default': {{
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': os.environ.get('REDIS_URL', 'redis://localhost:6379/1'),
    }}
}} if os.environ.get('REDIS_URL') else None

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_TZ = True
STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CORS_ALLOW_ALL_ORIGINS = True
REST_FRAMEWORK = {{
    'DEFAULT_AUTHENTICATION_CLASSES': [],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.AllowAny'],
}}
""")
    written.append(f"{proj}/settings.py")

    # urls.py
    url_patterns = ""
    for m in modules:
        url_patterns += f"    path('api/{m}/', include('{m}.urls')),\n"
    write(out, f"{proj}/urls.py",
          f"""from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
{url_patterns}]
""")
    written.append(f"{proj}/urls.py")

    # wsgi.py
    write(out, f"{proj}/wsgi.py",
          f"""import os
from django.core.wsgi import get_wsgi_application
os.environ.setdefault('DJANGO_SETTINGS_MODULE', '{proj}.settings')
application = get_wsgi_application()
""")
    written.append(f"{proj}/wsgi.py")

    # __init__.py for project dir
    write(out, f"{proj}/__init__.py", "")

    # Per app module
    for m in modules:
        app_dir = out / m
        app_dir.mkdir(parents=True, exist_ok=True)

        cls = class_by_mod.get(m, {"name": m.capitalize(), "fields": [], "methods": []})
        tbl = table_by_mod.get(m)
        fields = tbl["columns"] if tbl and tbl.get("columns") else (
            cls.get("fields") if cls.get("fields") else [{"name": "id", "type": "SERIAL"}]
        )

        # models.py
        model_fields = ""
        for f in fields:
            dtype = f["type"].upper()
            if any(t in dtype for t in ("SERIAL", "INT", "INTEGER")):
                dj_type = "models.IntegerField"
            elif "VARCHAR" in dtype or "CHAR" in dtype:
                dj_type = "models.CharField(max_length=255)"
            elif "TEXT" in dtype:
                dj_type = "models.TextField"
            elif "DECIMAL" in dtype or "FLOAT" in dtype or "DOUBLE" in dtype:
                dj_type = "models.DecimalField(max_digits=10, decimal_places=2)"
            elif "BOOL" in dtype:
                dj_type = "models.BooleanField"
            elif "DATE" in dtype or "TIME" in dtype or "TIMESTAMP" in dtype:
                dj_type = "models.DateTimeField"
            elif "JSON" in dtype:
                dj_type = "models.JSONField"
            else:
                dj_type = "models.CharField(max_length=255)"
            pk = ", primary_key=True" if f["name"].lower() == "id" else ""
            model_fields += f"    {f['name']} = {dj_type}({pk})\n"
        if not model_fields:
            model_fields = "    id = models.AutoField(primary_key=True)\n"

        write(out, f"{m}/models.py",
              f"from django.db import models\n\n\n"
              f"class {cls['name']}(models.Model):\n"
              f"{model_fields}\n"
              f"    class Meta:\n"
              f"        db_table = '{proj}_{m}s'\n\n"
              f"    def __str__(self):\n"
              f"        return str(self.id)\n")
        written.append(f"{m}/models.py")

        # views.py
        view_methods = ""
        for meth in cls.get("methods", []):
            view_methods += (
                f"class {meth['name'].capitalize()}View(APIView):\n"
                f"    def {_get_rest_method(meth['name'], ctx.get('endpoints', []))}:\n"
                f"        # TODO: implement {meth['name']}\n"
                f"        return Response({{}})\n\n"
            )
        if not view_methods:
            view_methods = (
                f"class {cls['name']}ViewSet(ModelViewSet):\n"
                f"    queryset = {cls['name']}.objects.all()\n"
                f"    serializer_class = {cls['name']}Serializer\n"
            )

        write(out, f"{m}/views.py",
              f"from rest_framework.views import APIView\n"
              f"from rest_framework.response import Response\n"
              f"from rest_framework.viewsets import ModelViewSet\n"
              f"from .models import {cls['name']}\n\n\n"
              f"{view_methods}\n")
        written.append(f"{m}/views.py")

        # serializers.py
        ser_fields = {}
        for f in fields:
            ser_fields[f['name']] = 'serializers.CharField()'
        write(out, f"{m}/serializers.py",
              f"from rest_framework import serializers\n"
              f"from .models import {cls['name']}\n\n\n"
              f"class {cls['name']}Serializer(serializers.ModelSerializer):\n"
              f"    class Meta:\n"
              f"        model = {cls['name']}\n"
              f"        fields = '__all__'\n")
        written.append(f"{m}/serializers.py")

        # urls.py
        routes = ""
        http_verbs_used = set()
        for ep in ctx.get("endpoints", []):
            path = ep["path"]
            if m in path.lower() or any(seg in path.lower() for seg in [m]):
                verb = ep["method"].lower()
                http_verbs_used.add(verb)
                view_action_str = "{" + f"'{verb}': 'list'" + "}"
                routes += f"    path('{path.strip(chr(47))}/', {cls['name']}ViewSet.as_view({view_action_str})),\n"
        if not routes:
            routes = f"    path('', {cls['name']}ViewSet.as_view({{'get': 'list', 'post': 'create'}})),\n"

        write(out, f"{m}/urls.py",
              f"from django.urls import path\n"
              f"from .views import {cls['name']}ViewSet\n\n"
              f"urlpatterns = [\n{routes}]\n")
        written.append(f"{m}/urls.py")

        # admin.py
        write(out, f"{m}/admin.py",
              f"from django.contrib import admin\n"
              f"from .models import {cls['name']}\n\n"
              f"admin.site.register({cls['name']})\n")
        written.append(f"{m}/admin.py")

    return written


def _get_rest_method(name: str, endpoints: list[dict]) -> str:
    """Map a method name to HTTP verb."""
    name_lower = name.lower()
    for ep in endpoints:
        if name_lower in ep.get("path", "").lower():
            return f"def {ep['method'].lower()}(self, request):"
    if any(kw in name_lower for kw in ("create", "register", "submit", "place")):
        return "def post(self, request):"
    return "def get(self, request):"


# ── Python generation (Flask / FastAPI) ─────────────────────

def _gen_python_files(out, ctx, modules, class_by_mod, table_by_mod) -> list[str]:
    written = []
    proj = ctx["project_name"].lower().replace(" ", "_").replace("-", "_")
    stack = ctx.get("stack", {})
    fw = (stack.get("fw", "") or "").lower()

    # requirements.txt
    deps = []
    if "flask" in fw:
        deps += ["flask", "flask-cors", "python-dotenv"]
    elif "fastapi" in fw:
        deps += ["fastapi", "uvicorn", "pydantic"]
    elif "django" in fw:
        deps += ["django", "djangorestframework", "django-cors-headers"]
    else:
        deps += ["flask", "python-dotenv"]

    db = (stack.get("db", "") or "").lower()
    if any(kw in db for kw in ("postgres", "postgresql", "pg")):
        deps += ["psycopg2-binary", "sqlalchemy"]
    elif "mysql" in db or "mariadb" in db:
        deps += ["pymysql", "sqlalchemy"]
    elif "sqlite" in db:
        deps += ["sqlalchemy"]
    elif "mongo" in db or "mongodb" in db:
        deps += ["pymongo", "mongoengine"]

    if "redis" in (stack.get("cache", "") or "").lower():
        deps.append("redis")

    deps += ["pytest", "pytest-cov"]
    write(out, "requirements.txt", "\n".join(deps))
    written.append("requirements.txt")

    # app.py
    if "fastapi" in fw:
        app_py = "from fastapi import FastAPI\nfrom fastapi.middleware.cors import CORSMiddleware\n\napp = FastAPI(title='" + ctx['project_name'] + "')\n"
        app_py += "app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])\n"
        for m in modules:
            app_py += f"from routes.{m}_routes import router as {m}_router\napp.include_router({m}_router, prefix='/api/{m}')\n"
        app_py += "\n@app.get('/health')\ndef health():\n    return {'status': 'ok'}\n"
    elif "flask" in fw:
        app_py = "from flask import Flask\nfrom flask_cors import CORS\n\napp = Flask(__name__)\nCORS(app)\n"
        for m in modules:
            app_py += f"from routes.{m}_routes import {m}_bp\napp.register_blueprint({m}_bp, url_prefix='/api/{m}')\n"
        app_py += "\n@app.route('/health')\ndef health():\n    return {'status': 'ok'}\n"
    else:
        app_py = "# Default Flask application\nfrom flask import Flask\napp = Flask(__name__)\n"

    write(out, "src/app.py", app_py)
    written.append("src/app.py")

    # server.py / run.py
    write(out, "src/server.py",
          "from app import app\n\nif __name__ == '__main__':\n    app.run(host='0.0.0.0', port=3000, debug=True)\n")
    written.append("src/server.py")

    # Per-module files
    for m in modules:
        cls = class_by_mod.get(m, {"name": m.capitalize(), "fields": [], "methods": []})
        tbl = table_by_mod.get(m)
        fields = tbl["columns"] if tbl and tbl.get("columns") else (
            cls.get("fields") if cls.get("fields") else [{"name": "id", "type": "SERIAL"}]
        )

        # Model (SQLAlchemy)
        cols_py = ""
        for f in fields:
            dtype = f["type"].upper()
            if any(t in dtype for t in ("INT", "SERIAL")):
                py_type = "Integer"
            elif "JSON" in dtype:
                py_type = "JSON"
            elif "FLOAT" in dtype:
                py_type = "Float"
            elif "BOOL" in dtype:
                py_type = "Boolean"
            elif "DATE" in dtype:
                py_type = "DateTime"
            elif "TEXT" in dtype:
                py_type = "Text"
            else:
                py_type = "String(255)"
            pk = ", primary_key=True" if f["name"].lower() == "id" else ""
            cols_py += f"    {f['name']} = Column({py_type}{pk})\n"
        model_py = f"""from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, JSON
from database import Base

class {cls['name']}(Base):
    __tablename__ = '{proj}_{m}s'
{cols_py}
"""
        write(out, f"src/{m}/models/{m}_model.py", model_py)

        # Service
        svc = f"""from models.{m}_model import {cls['name']}

class {cls['name']}Service:
"""
        for meth in cls.get("methods", []):
            svc += f"    def {meth['name']}(self, params=None):\n        # TODO: implement\n        pass\n"
        if not cls.get("methods"):
            svc += "    def get_all(self):\n        pass\n    def get_by_id(self, id):\n        pass\n"
        write(out, f"src/{m}/services/{m}_service.py", svc)

        # Routes
        if "flask" in fw:
            routes_py = f"""from flask import Blueprint, jsonify
from services.{m}_service import {cls['name']}Service

{m}_bp = Blueprint('{m}', __name__)
service = {cls['name']}Service()

"""
            for ep in ctx.get("endpoints", []):
                if m in ep.get("path", "").lower():
                    handler = ep["path"].strip("/").replace("/", "_")
                    routes_py += f"@{m}_bp.route('{ep['path']}', methods=['{ep['method']}'])\n"
                    routes_py += f"def {handler}():\n    return jsonify({{}})\n\n"
            if not ctx.get("endpoints"):
                routes_py += f"@{m}_bp.route('/', methods=['GET'])\ndef get_all():\n    return jsonify({{}})\n"
        elif "fastapi" in fw:
            routes_py = f"""from fastapi import APIRouter
from services.{m}_service import {cls['name']}Service

router = APIRouter()
service = {cls['name']}Service()

"""
            for ep in ctx.get("endpoints", []):
                if m in ep.get("path", "").lower():
                    routes_py += f"@router.{ep['method'].lower()}('{ep['path']}')\nasync def {ep['path'].strip('/')}():\n    return {{}}\n\n"
        else:
            routes_py = f"# Routes for {cls['name']}\n"

        write(out, f"src/{m}/routes/{m}_routes.py", routes_py)
        written.extend([f"src/{m}/models/{m}_model.py", f"src/{m}/services/{m}_service.py",
                        f"src/{m}/routes/{m}_routes.py"])

    # database.py
    db_url = f"postgresql://localhost:5432/{proj}"
    write(out, "src/database.py",
          "from sqlalchemy import create_engine\nfrom sqlalchemy.orm import sessionmaker\n"
          "import os\n\n"
          f"DATABASE_URL = os.environ.get('DATABASE_URL', '{db_url}')\n"
          "engine = create_engine(DATABASE_URL)\nSessionLocal = sessionmaker(bind=engine)\n"
          "from sqlalchemy.ext.declarative import declarative_base\nBase = declarative_base()\n")
    written.append("src/database.py")

    return written


# ── Language-agnostic generators ────────────────────────────────

def _gen_sql_files(out, ctx) -> list[str]:
    written = []
    for t in ctx.get("tables", []):
        cols = []
        for c in t["columns"]:
            suffix = " PRIMARY KEY" if (c["name"] == "id" and "PRIMARY" not in c["type"].upper()) else ""
            cols.append(f"  {c['name']} {c['type']}{suffix}")
        sql = f"CREATE TABLE IF NOT EXISTS {t['name']} (\n" + ",\n".join(cols) + "\n);\n"
        write(out, f"sql/{t['name']}.sql", sql)
        written.append(f"sql/{t['name']}.sql")
    return written


def _gen_openapi(out, ctx) -> list[str]:
    openapi = {"openapi": "3.0.0", "info": {"title": f"{ctx['project_name']} API", "version": "1.0.0"}, "paths": {}}
    for ep in ctx.get("endpoints", []):
        openapi["paths"][ep["path"]] = {
            ep["method"].lower(): {
                "summary": ep["path"].strip("/").replace("/", " ").title(),
                "responses": {"200": {"description": "Success"}},
            }
        }
    if not ctx.get("endpoints"):
        openapi["paths"]["/health"] = {"get": {"summary": "Health check", "responses": {"200": {"description": "OK"}}}}
    write(out, "api/openapi.yaml", yaml_dump(openapi))
    return ["api/openapi.yaml"]


def _gen_k8s_files(out, ctx) -> list[str]:
    proj = ctx["project_name"].lower().replace(" ", "-").replace("_", "-")
    k8s = ctx.get("k8s_resources", [])
    # If K8s YAML was extracted from the doc, write it directly
    for i, r in enumerate(k8s):
        if isinstance(r, dict) and r.get("raw"):
            name = r.get("kind", f"resource_{i}").lower()
            write(out, f"k8s/{name}.yaml", r["raw"])
    # Always generate a default deployment + service
    k8s_yaml = f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {proj}
spec:
  replicas: 3
  selector:
    matchLabels:
      app: {proj}
  template:
    metadata:
      labels:
        app: {proj}
    spec:
      containers:
      - name: {proj}
        image: {proj}:latest
        ports:
        - containerPort: 3000
---
apiVersion: v1
kind: Service
metadata:
  name: {proj}
spec:
  selector:
    app: {proj}
  ports:
  - port: 80
    targetPort: 3000
  type: ClusterIP
"""
    write(out, "k8s/deployment.yaml", k8s_yaml)
    write(out, "k8s/service.yaml", "")
    return ["k8s/deployment.yaml", "k8s/service.yaml"]


def _gen_docker_files(out, ctx, lang: str) -> list[str]:
    proj = ctx["project_name"].lower().replace(" ", "-").replace("_", "-")
    stack = ctx.get("stack", {})

    if lang == "python":
        docker = f"""FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
EXPOSE 3000
CMD ["python", "src/server.py"]
"""
    elif lang == "go":
        docker = f"""FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN go build -o server ./src/

FROM alpine:3.19
WORKDIR /app
COPY --from=builder /app/server .
EXPOSE 3000
CMD ["./server"]
"""
    else:  # node
        docker = f"""FROM node:18-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --production
COPY src/ ./src/
COPY api/ ./api/
EXPOSE 3000
CMD ["node", "src/server.js"]
"""
    write(out, "Dockerfile", docker)

    # docker-compose
    db_tech = (stack.get("db", "") or "").lower()
    compose_services = f"""  app:
    build: .
    ports:
      - "3000:3000"
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@db:5432/{proj}
      - REDIS_URL=redis://redis:6379
    depends_on:
      - db
      - redis
"""
    if any(kw in db_tech for kw in ("postgres", "postgresql", "pg")):
        compose_services += f"""  db:
    image: postgres:14
    environment:
      POSTGRES_DB: {proj}
      POSTGRES_PASSWORD: postgres
    volumes:
      - ./sql:/docker-entrypoint-initdb.d
"""
    elif "mysql" in db_tech or "mariadb" in db_tech:
        compose_services += f"""  db:
    image: mysql:8
    environment:
      MYSQL_DATABASE: {proj}
      MYSQL_ROOT_PASSWORD: root
"""
    elif "mongo" in db_tech:
        compose_services += f"""  db:
    image: mongo:7
"""
    compose = f"version: '3.8'\nservices:\n{compose_services}  redis:\n    image: redis:7-alpine\n"
    write(out, "docker-compose.yml", compose)
    return ["Dockerfile", "docker-compose.yml"]


def _gen_tests(out, ctx, modules, lang) -> list[str]:
    written = []
    for m in modules:
        if lang == "python":
            test = f"""def test_{m}_health(client):
    response = client.get('/api/{m}/')
    assert response.status_code in (200, 404)
"""
            write(out, f"tests/test_{m}.py", test)
            written.append(f"tests/test_{m}.py")
        else:
            test = f"""const request = require('supertest');
const app = require('../src/app');

beforeAll(async () => {{
  // Wait for database sync to complete before running tests
  if (app.dbReady) await app.dbReady;
}}, 15000);

describe('{m.capitalize()} API', () => {{
  it('GET /api/{m} should return 200', async () => {{
    const res = await request(app).get('/api/{m}');
    expect(res.statusCode).toBe(200);
  }});
}});
"""
            write(out, f"tests/{m}.test.js", test)
            written.append(f"tests/{m}.test.js")
    return written


def _gen_readme(out, ctx, modules) -> list[str]:
    stack = ctx.get("stack", {})
    readme = f"""# {ctx['project_name']}

Generated by Code Agent.

## Architecture
- Style: {ctx['architectural_style']}
- Language: {stack.get('lang', 'Not specified')}
- Framework: {stack.get('fw', 'Not specified')}
- Database: {stack.get('db', 'Not specified')}

## Modules
"""
    for m in modules:
        readme += f"- **{m.capitalize()}**: src/{m}/\n"
    readme += "\n## API Endpoints\n| Method | Path |\n|--------|------|\n"
    for ep in ctx.get("endpoints", []):
        readme += f"| {ep['method']} | {ep['path']} |\n"
    if not ctx.get("endpoints"):
        readme += "| GET | /health |\n"
    readme += "\n## Getting Started\n```bash\nnpm install && npm start\n```\n\n## Docker\n```bash\ndocker-compose up\n```\n"
    write(out, "README.md", readme)
    return ["README.md"]


def _gen_frontend(out, ctx, modules) -> list[str]:
    """Generate a complete single-page fraction quiz game as the frontend."""
    project_name = ctx["project_name"]
    endpoints = ctx.get("endpoints", [])

    # Determine which API routes exist
    has_game = "game" in modules
    has_question = "question" in modules
    has_user = "user" in modules

    # Build fetch calls for quiz questions
    question_api = "'/api/question'" if has_question else "null"
    game_api = "'/api/game'" if has_game else "null"

    # Find the play endpoint
    play_path = "/api/game/play"
    for ep in endpoints:
        if "play" in ep.get("path", "").lower():
            play_path = f"/api/game{ep['path']}" if has_game else "/api/game"
            break

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{project_name}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: 'Segoe UI', system-ui, sans-serif;
  background: linear-gradient(135deg, #0c0a3e 0%, #1a1656 40%, #2d1b69 100%);
  color: #e8d5f5;
  min-height: 100vh;
  display: flex; justify-content: center; align-items: center;
}}
#app {{ max-width: 700px; width: 90%; text-align: center; }}

/* Title Screen */
#title-screen h1 {{
  font-size: 3em; background: linear-gradient(90deg, #f9d423, #ff6ec7);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  margin-bottom: 10px;
}}
#title-screen p {{ font-size: 1.2em; opacity: 0.8; margin-bottom: 30px; }}
.stars {{
  position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  pointer-events: none; z-index: 0;
}}
.star {{
  position: absolute; background: white; border-radius: 50%;
  animation: twinkle 2s infinite alternate;
}}
@keyframes twinkle {{ from {{ opacity: 0.3; }} to {{ opacity: 1; }} }}

.btn {{
  background: linear-gradient(135deg, #f9d423, #ff6ec7);
  color: #0c0a3e; border: none; padding: 14px 40px; font-size: 1.2em;
  font-weight: bold; border-radius: 50px; cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s; margin: 8px;
}}
.btn:hover {{ transform: scale(1.05); box-shadow: 0 4px 20px rgba(249,212,35,0.4); }}
.btn.small {{ padding: 8px 20px; font-size: 0.9em; }}
.btn.secondary {{
  background: rgba(255,255,255,0.15); color: #e8d5f5;
}}

/* Question */
#question-screen, #result-screen {{ display: none; }}
.question-card {{
  background: rgba(255,255,255,0.08); border-radius: 20px; padding: 30px;
  backdrop-filter: blur(10px); margin: 20px 0;
}}
.question-text {{ font-size: 2em; margin: 20px 0; }}
.option-btn {{
  display: block; width: 100%; padding: 14px; margin: 8px 0;
  background: rgba(255,255,255,0.1); border: 2px solid rgba(255,255,255,0.2);
  border-radius: 12px; color: #e8d5f5; font-size: 1.1em; cursor: pointer;
  transition: all 0.2s;
}}
.option-btn:hover {{ background: rgba(249,212,35,0.2); border-color: #f9d423; }}
.option-btn.correct {{ background: rgba(76,217,100,0.3); border-color: #4cd964; }}
.option-btn.wrong {{ background: rgba(255,69,58,0.3); border-color: #ff453a; }}

.score-bar {{
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 20px; background: rgba(0,0,0,0.3); border-radius: 12px;
  margin-bottom: 15px;
}}
.progress {{ height: 6px; background: rgba(255,255,255,0.2); border-radius: 3px; margin: 10px 0; }}
.progress-fill {{ height: 100%; background: linear-gradient(90deg, #f9d423, #ff6ec7); border-radius: 3px; transition: width 0.3s; }}

/* Result */
#result-screen .big-score {{ font-size: 4em; font-weight: bold; background: linear-gradient(90deg, #f9d423, #ff6ec7); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
.stars-display {{ font-size: 2em; margin: 10px 0; }}

.spinner {{
  border: 3px solid rgba(255,255,255,0.2); border-top-color: #f9d423;
  border-radius: 50%; width: 40px; height: 40px; animation: spin 0.8s linear infinite;
  margin: 20px auto;
}}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}
</style>
</head>
<body>
<div class="stars" id="stars"></div>
<div id="app">
  <!-- Title Screen -->
  <div id="title-screen">
    <h1>🚀 {project_name}</h1>
    <p>Master fractions through an interactive space adventure!</p>
    <button class="btn" onclick="startGame()">Start Game</button>
    <p style="margin-top:20px;opacity:0.6;font-size:0.85em">Choose the correct answer for each fraction question.<br>Score points and reach the stars!</p>
  </div>

  <!-- Question Screen -->
  <div id="question-screen">
    <div class="score-bar">
      <span>Score: <strong id="score">0</strong></span>
      <span>Question <span id="q-num">1</span>/<span id="q-total">0</span></span>
      <span>⭐ <span id="stars-count">0</span></span>
    </div>
    <div class="progress"><div class="progress-fill" id="progress-bar" style="width:0%"></div></div>
    <div class="question-card">
      <p style="opacity:0.7">What is the result?</p>
      <div class="question-text" id="question-text">Loading...</div>
    </div>
    <div id="options-container"></div>
  </div>

  <!-- Result Screen -->
  <div id="result-screen">
    <h1>🎉 Mission Complete!</h1>
    <div class="big-score" id="final-score">0</div>
    <p>points earned</p>
    <div class="stars-display" id="final-stars"></div>
    <button class="btn" onclick="startGame()">Play Again</button>
    <button class="btn secondary" onclick="showTitle()">Main Menu</button>
  </div>
</div>

<script>
// Generate starfield background
(function() {{
  var c = document.getElementById('stars');
  for (var i = 0; i < 80; i++) {{
    var s = document.createElement('div');
    s.className = 'star';
    s.style.left = Math.random() * 100 + '%';
    s.style.top = Math.random() * 100 + '%';
    s.style.width = s.style.height = (Math.random() * 3 + 1) + 'px';
    s.style.animationDelay = Math.random() * 3 + 's';
    s.style.animationDuration = (Math.random() * 2 + 1.5) + 's';
    c.appendChild(s);
  }}
}})();

// Fraction questions (client-side fallback + API-based)
var QUESTIONS = [
  {{ q: "1/2 + 1/4 = ?", options: ["1/6", "3/4", "2/6", "1/8"], answer: 1 }},
  {{ q: "3/5 - 1/5 = ?", options: ["2/5", "4/5", "1/5", "3/10"], answer: 0 }},
  {{ q: "2/3 × 1/2 = ?", options: ["1/3", "2/5", "3/4", "1/2"], answer: 0 }},
  {{ q: "3/4 ÷ 1/2 = ?", options: ["3/8", "1 1/2", "2/3", "3/2"], answer: 1 }},
  {{ q: "1/3 + 2/3 = ?", options: ["3/6", "2/3", "1", "3/3"], answer: 2 }},
  {{ q: "5/8 - 1/2 = ?", options: ["1/8", "4/6", "2/8", "1/4"], answer: 0 }},
  {{ q: "2/5 × 3/4 = ?", options: ["6/20", "3/10", "5/9", "1/2"], answer: 1 }},
  {{ q: "7/8 ÷ 1/4 = ?", options: ["7/32", "2 1/2", "3 1/2", "7/2"], answer: 2 }},
];

var currentQ = 0, score = 0;

function showTitle() {{
  document.getElementById('title-screen').style.display = 'block';
  document.getElementById('question-screen').style.display = 'none';
  document.getElementById('result-screen').style.display = 'none';
}}

function startGame() {{
  currentQ = 0; score = 0;
  document.getElementById('title-screen').style.display = 'none';
  document.getElementById('result-screen').style.display = 'none';
  document.getElementById('question-screen').style.display = 'block';

  // Try loading questions from API
  if ({question_api}) {{
    fetch({question_api}).then(function(r) {{ return r.json(); }}).then(function(data) {{
      if (Array.isArray(data) && data.length > 0) {{
        QUESTIONS = data.map(function(item) {{ return {{
          q: item.prompt || item.question_text || 'Fraction problem',
          options: Array.isArray(item.options) ? item.options : JSON.parse(item.options || '[]'),
          answer: item.correct_answer !== undefined ? item.correct_answer : 0
        }}; }});
      }}
      renderQuestion();
    }}).catch(function() {{ renderQuestion(); }});
  }} else {{
    renderQuestion();
  }}
}}

function renderQuestion() {{
  if (currentQ >= QUESTIONS.length) return endGame();
  var q = QUESTIONS[currentQ];
  document.getElementById('question-text').textContent = q.q;
  document.getElementById('q-num').textContent = currentQ + 1;
  document.getElementById('q-total').textContent = QUESTIONS.length;
  document.getElementById('score').textContent = score;
  document.getElementById('progress-bar').style.width = (currentQ / QUESTIONS.length * 100) + '%';

  var opts = document.getElementById('options-container');
  opts.innerHTML = '';
  q.options.forEach(function(opt, i) {{
    var btn = document.createElement('button');
    btn.className = 'option-btn';
    btn.textContent = opt;
    btn.onclick = function() {{ answer(i, btn); }};
    opts.appendChild(btn);
  }});
}}

function answer(idx, btn) {{
  var q = QUESTIONS[currentQ];
  var allBtns = document.querySelectorAll('.option-btn');
  allBtns.forEach(function(b) {{ b.disabled = true; }});

  if (idx === q.answer) {{
    btn.classList.add('correct');
    score += 10;
    document.getElementById('score').textContent = score;
  }} else {{
    btn.classList.add('wrong');
    allBtns[q.answer].classList.add('correct');
  }}

  // Record score via API if available
  if ({game_api}) {{
    fetch({game_api}, {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ score: score, question_id: currentQ + 1 }})
    }}).catch(function() {{}});
  }}

  setTimeout(function() {{
    currentQ++;
    renderQuestion();
  }}, 1200);
}}

function endGame() {{
  document.getElementById('question-screen').style.display = 'none';
  document.getElementById('result-screen').style.display = 'block';
  document.getElementById('final-score').textContent = score;
  var stars = score >= 70 ? '⭐⭐⭐' : score >= 40 ? '⭐⭐' : '⭐';
  document.getElementById('final-stars').textContent = stars;
  document.getElementById('stars-count').textContent =
    score >= 70 ? 3 : score >= 40 ? 2 : 1;
}}
</script>
</body>
</html>"""
    write(out, "src/public/index.html", html)
    return ["src/public/index.html"]
    proj = ctx["project_name"].lower().replace(" ", "-").replace("_", "-")
    write(out, ".gitignore", "node_modules/\n.env\n*.log\ncoverage/\n__pycache__/\n*.pyc\n")
    write(out, ".env.example",
          f"DATABASE_URL=postgresql://localhost:5432/{proj}\nREDIS_URL=redis://localhost:6379\nPORT=3000\n")
    return [".gitignore", ".env.example"]


# ─── Helpers ───────────────────────────────────────────────────

def _dedup(items: list[dict], keys: tuple[str, ...]) -> list[dict]:
    seen = set()
    result = []
    for item in items:
        sig = tuple(item.get(k) for k in keys)
        if sig not in seen:
            seen.add(sig)
            result.append(item)
    return result


def write(base: Path, rel_path: str, content: str) -> None:
    full = base / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content.strip() + "\n", encoding="utf-8")


def yaml_dump(obj, indent=0) -> str:
    lines = []
    sp = "  " * indent
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, dict):
                lines.append(f"{sp}{k}:")
                lines.append(yaml_dump(v, indent + 1))
            elif isinstance(v, list):
                lines.append(f"{sp}{k}:")
                for item in v:
                    lines.append(f"{sp}  - {item}")
            else:
                lines.append(f"{sp}{k}: {v}")
    return "\n".join(lines)


def run(input_doc: str, input_view: str, output_dir: str) -> dict:
    print(f"Parsing {input_doc}...")
    doc_data = parse_arch_doc(input_doc)
    print(f"  Project: {doc_data['project_name']}")
    print(f"  Style: {doc_data['architectural_style']}")
    print(f"  Stack: {json.dumps({k: v for k, v in doc_data['stack'].items() if v}, indent=2)}")
    print(f"  Components: {[c['name'] for c in doc_data['components']]}")
    print(f"  Endpoints: {doc_data['endpoints']}")
    print(f"  Tables: {[t['name'] for t in doc_data['tables']]}")

    print(f"Parsing {input_view}...")
    view_data = parse_arch_view(input_view)
    classes_found = [c["name"] for d in view_data["diagrams"] for c in d.get("classes", [])]
    print(f"  Classes found: {classes_found}")
    print(f"  Relations: {len([r for d in view_data['diagrams'] for r in d.get('relations', [])])}")

    print("Merging into structured context...")
    ctx = merge_to_json(doc_data, view_data)

    lang = _detect_language(ctx)
    print(f"  Detected language: {lang}")

    print(f"Generating project to {output_dir}...")
    files = generate_project(ctx, output_dir)

    print(f"\nDone! Generated {len(files)} files:")
    for f in files:
        print(f"  {f}")

    return {"project": doc_data["project_name"], "files": len(files), "output_dir": output_dir,
            "language": lang}
