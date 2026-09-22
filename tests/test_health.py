import asyncio
import unittest

from routes.verify import health


class HealthTest(unittest.TestCase):
    def test_health_contract(self):
        response = asyncio.run(health())
        self.assertEqual(response["status"], "ok")
        self.assertIn("version", response)


if __name__ == "__main__":
    unittest.main()
