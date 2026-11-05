"""
GemmaGraph-Sentry: Directed Code Knowledge Graphs (DCKG) & Deterministic Verification
for Autonomous Agentic Software Engineering with Google Gemma 4.

Author: Usman Bamidele (Department of Mathematics, FUNAAB)
License: Apache-2.0 / MIT
"""

import ast
import json
import os
import sys
import tempfile
import subprocess
import time
from typing import Dict, List, Set, Tuple, Optional

class CodeNode:
    def __init__(self, name: str, node_type: str, lineno: int, end_lineno: int, source_code: str):
        self.name = name
        self.node_type = node_type  # 'function', 'class', 'module'
        self.lineno = lineno
        self.end_lineno = end_lineno
        self.source_code = source_code
        self.dependencies: Set[str] = set()  # Names of symbols this node calls/uses

    def to_dict(self):
        return {
            "name": self.name,
            "type": self.node_type,
            "lines": f"{self.lineno}-{self.end_lineno}",
            "dependencies": list(self.dependencies)
        }

class DirectedCodeGraph:
    """
    Formulates a software repository as an Attributed Directed Code Knowledge Graph G = (V, E).
    V = Set of functional code symbols (functions, classes, methods).
    E = Directed edges representing invocation, inheritance, or dependency.
    """
    def __init__(self):
        self.nodes: Dict[str, CodeNode] = {}
        self.adjacency: Dict[str, Set[str]] = {}       # caller -> {callees}
        self.reverse_adj: Dict[str, Set[str]] = {}    # callee -> {callers}

    def add_node(self, node: CodeNode):
        self.nodes[node.name] = node
        if node.name not in self.adjacency:
            self.adjacency[node.name] = set()
        if node.name not in self.reverse_adj:
            self.reverse_adj[node.name] = set()

    def add_edge(self, source: str, target: str):
        if source not in self.adjacency:
            self.adjacency[source] = set()
        if target not in self.reverse_adj:
            self.reverse_adj[target] = set()
        self.adjacency[source].add(target)
        self.reverse_adj[target].add(source)

    def extract_from_source(self, source_code: str, module_name: str = "main"):
        tree = ast.parse(source_code)
        lines = source_code.splitlines()

        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                snippet = "\n".join(lines[stmt.lineno - 1:stmt.end_lineno])
                node = CodeNode(stmt.name, "function", stmt.lineno, stmt.end_lineno, snippet)
                
                # Extract calls inside function
                for child in ast.walk(stmt):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name):
                            node.dependencies.add(child.func.id)
                        elif isinstance(child.func, ast.Attribute):
                            node.dependencies.add(child.func.attr)
                            
                self.add_node(node)
                for dep in node.dependencies:
                    self.add_edge(stmt.name, dep)

            elif isinstance(stmt, ast.ClassDef):
                snippet = "\n".join(lines[stmt.lineno - 1:stmt.end_lineno])
                node = CodeNode(stmt.name, "class", stmt.lineno, stmt.end_lineno, snippet)
                self.add_node(node)

    def get_k_hop_subgraph(self, target_symbol: str, k: int = 1) -> Dict[str, CodeNode]:
        """
        Extracts the k-hop topological neighborhood around target_symbol.
        Collapses context from large repositories into minimal reasoning subgraphs.
        """
        visited: Set[str] = {target_symbol}
        queue: List[Tuple[str, int]] = [(target_symbol, 0)]

        while queue:
            curr, depth = queue.pop(0)
            if depth >= k:
                continue

            # Check outbound (callees) and inbound (callers)
            neighbors = self.adjacency.get(curr, set()) | self.reverse_adj.get(curr, set())
            for nbr in neighbors:
                if nbr in self.nodes and nbr not in visited:
                    visited.add(nbr)
                    queue.append((nbr, depth + 1))

        return {name: self.nodes[name] for name in visited if name in self.nodes}


class DeterministicSandboxVerifier:
    """
    Subprocess-isolated verification engine.
    Applies candidate patches produced by Gemma 4, executes regression test suites,
    and returns deterministic binary pass/fail proofs with stderr traces.
    """
    @staticmethod
    def verify_patch(original_code: str, patch_code: str, test_code: str) -> Tuple[bool, str, float]:
        start_time = time.perf_counter()
        with tempfile.TemporaryDirectory() as tmpdir:
            solution_file = os.path.join(tmpdir, "solution.py")
            test_file = os.path.join(tmpdir, "test_solution.py")

            with open(solution_file, "w", encoding="utf-8") as f:
                f.write(patch_code)

            full_test_code = f"import sys\nsys.path.insert(0, r'{tmpdir}')\nfrom solution import *\n" + test_code
            with open(test_file, "w", encoding="utf-8") as f:
                f.write(full_test_code)

            try:
                proc = subprocess.run(
                    [sys.executable, test_file],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                duration = time.perf_counter() - start_time
                success = (proc.returncode == 0)
                output = proc.stdout if success else proc.stderr
                return success, output.strip(), duration
            except subprocess.TimeoutExpired:
                duration = time.perf_counter() - start_time
                return False, "Sandbox execution timed out (Infinite loop detected)", duration
            except Exception as e:
                duration = time.perf_counter() - start_time
                return False, f"Sandbox error: {str(e)}", duration


class GemmaGraphAgent:
    """
    Autonomous Developer Agent pipeline combining DCKG Graph Pruning
    with Test-Time Verification for Gemma 4.
    """
    def __init__(self, graph: DirectedCodeGraph):
        self.graph = graph
        self.verifier = DeterministicSandboxVerifier()

    def generate_prompt_from_error(self, failing_symbol: str, error_trace: str) -> str:
        """
        Extracts 1-hop minimal context subgraph to keep prompt within Gemma 4 compute limits.
        """
        subgraph = self.graph.get_k_hop_subgraph(failing_symbol, k=1)
        code_context = "\n\n".join([f"# Symbol: {n.name} (Lines {n.lineno}-{n.end_lineno})\n{n.source_code}" for n in subgraph.values()])

        prompt = f"""[GEMMA-4-DEVELOPER-AGENT TASK]
Target Symbol: {failing_symbol}
Error Traceback:
{error_trace}

Topological Code Subgraph Context:
{code_context}

Instruction:
Formulate an invariant-preserving bug fix for {failing_symbol}. Output only the corrected function.
"""
        return prompt

    def solve_and_verify(self, original_code: str, candidate_patches: List[str], test_suite: str) -> Dict:
        """
        Best-of-N Search with Test-Time Verification:
        Iterates over candidate patches, executes them in the deterministic sandbox,
        and selects the verified solution.
        """
        evaluations = []
        best_patch = None

        for idx, patch in enumerate(candidate_patches):
            passed, logs, duration = self.verifier.verify_patch(original_code, patch, test_suite)
            evaluations.append({
                "candidate_id": idx + 1,
                "passed": passed,
                "latency_sec": round(duration, 4),
                "logs": logs[:200]
            })
            if passed and best_patch is None:
                best_patch = patch

        return {
            "verified": best_patch is not None,
            "selected_patch": best_patch,
            "evaluations": evaluations
        }
