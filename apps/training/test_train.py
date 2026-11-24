import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from sklearn.datasets import load_iris
from skops.io import dump, load

import train


class TrainingTests(unittest.TestCase):
    def test_deterministic_training_and_model_round_trip(self):
        first, first_report = train.train()
        second, second_report = train.train()
        self.assertEqual(first_report, second_report)
        self.assertEqual((first_report["train_rows"], first_report["test_rows"]), (120, 30))
        sample = load_iris().data
        np.testing.assert_array_equal(first.predict(sample), second.predict(sample))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.skops"
            dump(first, path)
            np.testing.assert_array_equal(first.predict(sample), load(path).predict(sample))

    def test_metrics(self):
        scores = train.quality([0, 0, 1, 1], [0, 1, 1, 1])
        self.assertEqual(scores["accuracy"], 0.75)
        self.assertAlmostEqual(scores["macro_f1"], 11 / 15)

    def test_artifact_error_marks_failed_and_returns_nonzero(self):
        client = Mock()
        client.get_experiment_by_name.return_value = SimpleNamespace(experiment_id="1")
        client.create_run.return_value = SimpleNamespace(
            info=SimpleNamespace(run_id="run", artifact_uri="mlflow-artifacts:/1/run/artifacts")
        )
        client.log_artifacts.side_effect = RuntimeError("upload failed")
        with patch.dict("os.environ", {"MLFLOW_TRACKING_URI": "http://127.0.0.1:5000"}):
            with patch.object(train, "MlflowClient", return_value=client):
                self.assertEqual(train.main(), 1)
        client.set_terminated.assert_called_once_with("run", status="FAILED")

    def test_requires_finished_readback(self):
        client = Mock()
        client.get_experiment_by_name.return_value = SimpleNamespace(experiment_id="1")
        client.create_run.return_value = SimpleNamespace(
            info=SimpleNamespace(run_id="run", artifact_uri="mlflow-artifacts:/1/run/artifacts")
        )
        client.get_run.return_value = SimpleNamespace(info=SimpleNamespace(status="RUNNING"))
        with self.assertRaisesRegex(RuntimeError, "FINISHED"):
            train.run_training(client)
        self.assertEqual(client.set_terminated.call_count, 2)
        client.set_terminated.assert_called_with("run", status="FAILED")


if __name__ == "__main__":
    unittest.main()
