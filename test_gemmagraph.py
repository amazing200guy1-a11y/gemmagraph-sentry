"""
Unit Test Suite for GemmaGraph-Sentry
Verifying AST Code Graph Extraction, Context Compression, and Deterministic Sandbox.
"""

import unittest
from gemmagraph_sentry import DirectedCodeGraph, DeterministicSandboxVerifier, GemmaGraphAgent

class TestGemmaGraphSentry(unittest.TestCase):

    def setUp(self):
        self.sample_code = """
def calculate_tax(amount, rate):
    return amount * rate

def process_transaction(user_id, amount):
    if amount <= 0:
        raise ValueError("Invalid amount")
    tax = calculate_tax(amount, 0.05)
    return amount + tax

def format_receipt(user_id, amount):
    total = process_transaction(user_id, amount)
    return f"Receipt for {user_id}: Total ${total:.2f}"

def audit_log(event):
    print(f"Log: {event}")
"""

    def test_code_graph_ast_extraction(self):
        graph = DirectedCodeGraph()
        graph.extract_from_source(self.sample_code)

        # Verify extracted nodes
        self.assertIn("calculate_tax", graph.nodes)
        self.assertIn("process_transaction", graph.nodes)
        self.assertIn("format_receipt", graph.nodes)
        self.assertIn("audit_log", graph.nodes)

        # Verify graph edges
        self.assertIn("calculate_tax", graph.adjacency["process_transaction"])
        self.assertIn("process_transaction", graph.adjacency["format_receipt"])
        print("[PASS] AST Code Graph extracted 4 symbols and topological dependencies.")

    def test_k_hop_context_compression(self):
        graph = DirectedCodeGraph()
        graph.extract_from_source(self.sample_code)

        # Target: calculate_tax with 1-hop neighborhood
        subgraph = graph.get_k_hop_subgraph("calculate_tax", k=1)
        
        # calculate_tax is called by process_transaction.
        # It should contain calculate_tax and process_transaction, but NOT format_receipt or audit_log.
        self.assertIn("calculate_tax", subgraph)
        self.assertIn("process_transaction", subgraph)
        self.assertNotIn("audit_log", subgraph)

        compression_ratio = 1.0 - (len(subgraph) / len(graph.nodes))
        print(f"[PASS] Context pruned from {len(graph.nodes)} to {len(subgraph)} nodes ({compression_ratio:.1%} reduction).")
        self.assertGreaterEqual(compression_ratio, 0.5)

    def test_deterministic_sandbox_verification(self):
        test_suite = """
assert process_transaction(101, 100) == 105.0
try:
    process_transaction(101, -5)
    assert False, "Should have raised ValueError"
except ValueError:
    pass
print("ALL TESTS PASSED")
"""
        # Candidate 1: Broken patch (syntax error or logic bug)
        broken_patch = """
def calculate_tax(amount, rate):
    return 0  # Buggy zero tax

def process_transaction(user_id, amount):
    return amount + calculate_tax(amount, 0.05)
"""
        success, logs, duration = DeterministicSandboxVerifier.verify_patch(self.sample_code, broken_patch, test_suite)
        self.assertFalse(success)
        print(f"[PASS] Deterministic Sandbox rejected buggy patch in {duration:.4f}s.")

        # Candidate 2: Correct patch
        valid_patch = """
def calculate_tax(amount, rate):
    return amount * rate

def process_transaction(user_id, amount):
    if amount <= 0:
        raise ValueError("Invalid amount")
    return amount + calculate_tax(amount, 0.05)
"""
        success, logs, duration = DeterministicSandboxVerifier.verify_patch(self.sample_code, valid_patch, test_suite)
        self.assertTrue(success)
        self.assertIn("ALL TESTS PASSED", logs)
        print(f"[PASS] Deterministic Sandbox verified correct patch in {duration:.4f}s.")

if __name__ == "__main__":
    unittest.main()
