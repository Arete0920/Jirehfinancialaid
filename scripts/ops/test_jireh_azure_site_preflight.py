import unittest
import subprocess
import sys
import tempfile
from pathlib import Path
from jireh_azure_site_preflight import collect


class JirehAzurePreflightTests(unittest.TestCase):
    def test_free_tier_does_not_imply_cost_or_launch_approval(self):
        calls = []
        def run(args):
            calls.append(args)
            if args[1:3] == ['account', 'show']:
                return {'id': 'fake', 'state': 'Enabled'}
            if args[1:3] == ['staticwebapp', 'list']:
                return [{'name': 'crown-dash', 'sku': {'name': 'Free'}},
                        {'name': 'jireh-site', 'sku': {'name': 'Free'}}]
            if args[1:3] == ['consumption', 'budget']:
                return [{'name': 'budget'}]
        data = collect('jireh-staging', run=run)
        self.assertEqual(data['static_sites']['sku_counts'], {'Free': 2})
        self.assertTrue(data['static_sites']['existing_jireh_site'])
        self.assertEqual(data['budget_count'], 1)
        self.assertFalse(data['launch_authorized'])
        self.assertEqual(data['actual_cost_status'], 'NOT_COLLECTED')
        self.assertEqual(data['resource_isolation_status'], 'NOT_VERIFIED')
        self.assertEqual(len(calls), 3)
        self.assertTrue(all('create' not in arg and 'update' not in arg and 'delete' not in arg
                            for args in calls for arg in args))
    def test_no_cli_access_fails_closed_without_implicit_zero(self):
        data = collect('jireh-staging', run=lambda _: None)
        self.assertEqual(data['checks']['static_web_apps'], 'UNAVAILABLE')
        self.assertEqual(data['checks']['resource_group_budgets'], 'UNAVAILABLE')
        self.assertIsNone(data['budget_count'])
        self.assertFalse(data['launch_authorized'])
    def test_rejects_bad_resource_groups(self):
        for group in ('', '../bad', 'x; rm -rf /', 'invalid group'):
            with self.assertRaises(ValueError):
                collect(group, run=lambda _: None)

    def test_crown_group_is_rejected_before_queries(self):
        calls = []
        with self.assertRaises(ValueError):
            collect('CROWN-RG', run=lambda args: calls.append(args))
        self.assertEqual(calls, [])


from jireh_azure_site_preflight import AdmissionDenied, plan, verify

def site(name="jireh-site", group="jireh-staging", sku="Free"):
    return {"name": name, "sku": {"name": sku},
            "id": f"/subscriptions/mock/resourceGroups/{group}/providers/Microsoft.Web/staticSites/{name}"}

class JirehAdmissionTests(unittest.TestCase):
    def test_reuse_existing_free_only(self):
        self.assertEqual(plan([site(), site(name="other-site")], group="jireh-staging"), "REUSE_VERIFIED_FREE")
        self.assertTrue(verify(site(), group="jireh-staging"))
    def test_create_with_available_quota(self):
        self.assertEqual(plan([site("other-site")], group="jireh-staging"), "CREATE_FREE")
    def test_fail_at_quota(self):
        with self.assertRaises(AdmissionDenied):
            plan([site(name=f"free-{x}") for x in range(10)], group="jireh-staging")
    def test_never_replace_paid(self):
        with self.assertRaises(AdmissionDenied):
            plan([site(sku="Standard")], group="jireh-staging")
        with self.assertRaises(AdmissionDenied):
            verify(site(sku="Standard"), group="jireh-staging")
    def test_other_resource_group_fails(self):
        with self.assertRaises(AdmissionDenied):
            plan([site(group="other-rg")], group="jireh-staging")
        with self.assertRaises(AdmissionDenied):
            verify(site(group="other-rg"), group="jireh-staging")
    def test_unavailable_inventory_fails(self):
        for bad in (None, {}, [dict(name="jireh-site")], [site(sku="Unknown")]):
            with self.subTest(value=bad), self.assertRaises(AdmissionDenied):
                plan(bad, group="jireh-staging")
    def test_duplicate_name_fails(self):
        with self.assertRaises(AdmissionDenied):
            plan([site(), site()], group="jireh-staging")
    def test_rejects_command_injection_names(self):
        for value in ("", "../bad", "a b", "x;curl"):
            with self.subTest(value=value), self.assertRaises(AdmissionDenied):
                plan([], name=value, group="jireh-staging")

    def test_crown_group_rejected_in_offline_modes(self):
        with self.assertRaises(ValueError):
            plan([], group="CROWN-RG")
        with self.assertRaises(ValueError):
            verify(site(group="crown-rg"), group="crown-rg")

    def test_group_must_be_explicit(self):
        with self.assertRaises(TypeError):
            plan([])
        with self.assertRaises(TypeError):
            verify(site())

    def test_cli_fails_closed_without_a_group(self):
        script = str(Path(__file__).with_name("jireh_azure_site_preflight.py"))
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory) / "inventory.json"
            inventory.write_text("[]", encoding="utf-8")
            for args in ([], ["--inventory", str(inventory)]):
                result = subprocess.run(
                    [sys.executable, script, *args], capture_output=True, text=True, check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("required", result.stderr)

    def test_cli_inventory_is_not_deployment_authorization(self):
        script = str(Path(__file__).with_name("jireh_azure_site_preflight.py"))
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory) / "inventory.json"
            inventory.write_text("[]", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, script, "--inventory", str(inventory), "--group", "jireh-staging"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("provisioning and deployment NOT AUTHORIZED", result.stdout)


class JirehDeferredHostingContractTests(unittest.TestCase):
    def test_legacy_crown_deployment_workflow_is_not_present(self):
        workflow = Path(__file__).resolve().parents[2] / ".github/workflows/azure-classroom-preflight.yml"
        self.assertFalse(workflow.exists())

if __name__ == "__main__":
    unittest.main()
