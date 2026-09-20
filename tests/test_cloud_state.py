import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from research_radar.cloud_state import (CloudStateError, GitHubState,
                                        decrypt_state, encrypt_state)
from research_radar.state import save_json_atomic


class CloudStateTests(unittest.TestCase):
    def test_encrypted_checkpoint_roundtrip_includes_unsent_mail(self):
        key = Fernet.generate_key().decode("ascii")
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as restored:
            root = Path(source)
            save_json_atomic(root / "state.json", {"schema_version": 1, "monitor_id": "私密研究", "works": {}, "source_scans": {}})
            eml = root / "emails" / "weekly.eml"
            eml.parent.mkdir(parents=True)
            eml.write_text("Subject: 测试\n\n私密内容", encoding="utf-8")
            save_json_atomic(root / "delivery.json", {"schema_version": 1, "periods": {
                "2026-09-21": {"status": "transmitting", "message_file": "emails/weekly.eml"}
            }})
            ciphertext = encrypt_state(root, key)
            self.assertNotIn("私密研究".encode("utf-8"), ciphertext)
            self.assertNotIn("私密内容".encode("utf-8"), ciphertext)
            decrypt_state(ciphertext, Path(restored), key)
            self.assertEqual(json.loads((Path(restored) / "state.json").read_text(encoding="utf-8"))["monitor_id"], "私密研究")
            self.assertIn("私密内容", (Path(restored) / "emails" / "weekly.eml").read_text(encoding="utf-8"))

    def test_wrong_key_and_malicious_path_fail_before_writing(self):
        key = Fernet.generate_key()
        payload = {"schema_version": 1, "files": {"state.json": "{}", "../escape.json": "bad"}}
        ciphertext = Fernet(key).encrypt(gzip.compress(json.dumps(payload).encode("utf-8")))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(CloudStateError):
                decrypt_state(ciphertext, root, key.decode("ascii"))
            self.assertFalse((root / "state.json").exists())
            with self.assertRaisesRegex(CloudStateError, "authenticated/decrypted"):
                decrypt_state(ciphertext, root, Fernet.generate_key().decode("ascii"))

    def test_optimistic_concurrency_refuses_overwrite(self):
        env = {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_TOKEN": "token",
               "RADAR_STATE_KEY": Fernet.generate_key().decode("ascii")}
        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", env, clear=True):
            storage = GitHubState(Path(temp))
            storage.head = "old-head"
            with patch.object(storage, "_request", return_value={"object": {"sha": "new-head"}}), \
                    patch("research_radar.cloud_state.encrypt_state") as encrypt:
                with self.assertRaisesRegex(CloudStateError, "another run"):
                    storage.checkpoint()
                encrypt.assert_not_called()

    def test_missing_remote_state_requires_explicit_initialization(self):
        env = {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_TOKEN": "token",
               "RADAR_STATE_KEY": Fernet.generate_key().decode("ascii")}
        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", env, clear=True):
            storage = GitHubState(Path(temp))
            with patch.object(storage, "_request", return_value=None):
                with self.assertRaisesRegex(CloudStateError, "initialize explicitly"):
                    storage.restore()
                self.assertFalse(storage.restore(initialize=True))


if __name__ == "__main__":
    unittest.main()
