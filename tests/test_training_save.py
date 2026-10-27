import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from router_train_local import EarlyStop
from training_power_guard import low_battery


class TrainingSaveTests(unittest.TestCase):
    def test_power_guard_allows_charging_and_stops_low_battery(self):
        self.assertFalse(low_battery("Now drawing from 'AC Power'\n14%; charging;"))
        self.assertFalse(low_battery("Now drawing from 'Battery Power'\n40%; discharging;"))
        self.assertTrue(low_battery("Now drawing from 'Battery Power'\n25%; discharging;"))
        self.assertTrue(low_battery("Now drawing from 'Battery Power'\n14%; discharging;"))
        with self.assertRaises(ValueError):
            low_battery('unavailable')
    def test_interrupted_adapter_is_saved_atomically_without_loading_a_model(self):
        with tempfile.TemporaryDirectory() as folder:
            state = EarlyStop(folder)
            parameters = [('model.layers.1.lora_a','weight')]
            state.model = Mock(trainable_parameters=Mock(return_value=parameters))
            def save(path, values):
                self.assertEqual(values,dict(parameters))
                Path(path).write_bytes(b'saved-adapter')
            core = SimpleNamespace(save_safetensors=save)
            modules = {'mlx.core':core,
                       'mlx.utils':SimpleNamespace(tree_flatten=lambda x:x),'mlx':SimpleNamespace(core=core)}
            with patch.dict(sys.modules,modules):
                self.assertTrue(state.save_latest())
            self.assertEqual((Path(folder)/'adapters.safetensors').read_bytes(),b'saved-adapter')
            self.assertFalse((Path(folder)/'latest.tmp.safetensors').exists())

    def test_base_weights_are_never_saved_as_an_adapter(self):
        state = EarlyStop('/tmp/not-used')
        self.assertFalse(state.save_latest())
        state.model = Mock(trainable_parameters=Mock(return_value=[('model.weight','base')]))
        save = Mock()
        core = SimpleNamespace(save_safetensors=save)
        with patch.dict(sys.modules,{'mlx.core':core,
                                   'mlx.utils':SimpleNamespace(tree_flatten=lambda x:x),'mlx':SimpleNamespace(core=core)}):
            self.assertFalse(state.save_latest())
        save.assert_not_called()

    def test_progress_records_the_last_reported_iteration(self):
        with tempfile.TemporaryDirectory() as folder:
            state = EarlyStop(folder)
            state.on_train_loss_report({'iteration':40,'train_loss':.1})
            self.assertEqual(json.loads((Path(folder)/'progress.json').read_text())['last_reported_iteration'],40)
