"""Resolve the real Compose files to check rollout and rollback boundaries."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("docker"), "Docker Compose is required")
class ReadingConfigurationTests(unittest.TestCase):
    def config(self, production, mixed=None, home=None):
        root = Path(__file__).resolve().parents[2]
        env = {k: v for k, v in os.environ.items() if not k.startswith("R2_")}
        # These must never leak into the explicitly closed services.
        env.update(R2_MEMBER_PROCESSING_ENABLED="true", R2_SYNTHESIS_ENABLED="true",
                   R2_TOPIC_PUBLICATION_ENABLED="true", R2_TOPIC_PREFERENCES_ENABLED="true")
        for key, value in (("R2_HYBRID_ENABLED", mixed), ("R2_DISCOVER_HOME_ENABLED", home)):
            if value is not None:
                env[key] = value
        command = ["docker", "compose", "--env-file", "/dev/null", "-f", "deploy/compose.yml"]
        if production:
            command += ["-f", "deploy/compose.prod.yml"]
        result = subprocess.run(command + ["config", "--format", "json"], cwd=root,
                                env=env, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)["services"]

    def test_only_api_reading_is_enabled_and_each_switch_can_be_rolled_back(self):
        for production, mixed, home in ((False, None, None), (True, None, None),
                                       (True, "false", None), (True, None, "false"),
                                       (True, "false", "false")):
            with self.subTest(production=production, mixed=mixed, home=home):
                services = self.config(production, mixed, home)
                api = services["api"]["environment"]
                default = str(production).lower()
                self.assertEqual(api["UNSPUN_R2_HYBRID_ENABLED"], mixed or default)
                self.assertEqual(api["UNSPUN_R2_DISCOVER_HOME_ENABLED"], home or default)
                for service in ("api", "r1-worker"):
                    for suffix in ("MEMBER_PROCESSING", "SYNTHESIS", "TOPIC_PUBLICATION",
                                   "TOPIC_PREFERENCES"):
                        self.assertEqual(services[service]["environment"][
                            f"UNSPUN_R2_{suffix}_ENABLED"], "false")
                for suffix in ("HYBRID", "DISCOVER_HOME"):
                    self.assertEqual(services["r1-worker"]["environment"][
                        f"UNSPUN_R2_{suffix}_ENABLED"], "false")
                self.assertNotIn("worker", services)
                self.assertNotIn("UNSPUN_OPENROUTER_API_KEY", api)
                if production:
                    self.assertEqual(services["web"]["ports"][0]["host_ip"], "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
