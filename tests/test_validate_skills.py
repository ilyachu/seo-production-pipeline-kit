import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("validate_skills", ROOT / "scripts" / "validate_skills.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SkillPackValidationTest(unittest.TestCase):
    def test_pack_is_valid(self):
        self.assertEqual([], MODULE.validate())


if __name__ == "__main__":
    unittest.main()
