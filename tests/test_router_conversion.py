"""Conversion metadata compatibility without model loads or inference."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from router_gguf_input import compatible_config,prepare


class RouterConversionTests(unittest.TestCase):
    def test_new_list_metadata_maps_to_existing_special_ids_only(self):
        config=dict(eos_token='end',extra_special_tokens=['start','end'])
        tokenizer=dict(added_tokens=[dict(content='start',id=10,special=True),dict(content='end',id=11,special=True)])
        converted=compatible_config(config,tokenizer)
        self.assertEqual(converted,dict(eos_token='end',additional_special_tokens=['start','end']))
        self.assertIn('extra_special_tokens',config)
        self.assertEqual(tokenizer['added_tokens'][1]['id'],11)
        with self.assertRaises(ValueError): compatible_config(dict(extra_special_tokens=['unknown']),tokenizer)

    def test_old_dictionary_metadata_is_unchanged(self):
        config=dict(extra_special_tokens={'image_token':'image'})
        self.assertEqual(compatible_config(config,{}),config)

    def test_separate_view_preserves_originals_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'fused';source.mkdir()
            config=dict(extra_special_tokens=['end'])
            (source/'tokenizer_config.json').write_text(json.dumps(config))
            (source/'tokenizer.json').write_text(json.dumps(dict(added_tokens=[dict(content='end',id=7,special=True)])))
            (source/'weights.safetensors').write_bytes(b'owned fixture')
            for _ in range(2): prepare(source,root/'conversion')
            self.assertEqual(json.loads((source/'tokenizer_config.json').read_text()),config)
            self.assertTrue((root/'conversion/weights.safetensors').is_symlink())
            self.assertEqual((root/'conversion/weights.safetensors').read_bytes(),b'owned fixture')
            with self.assertRaises(ValueError): prepare(source,source)
            with self.assertRaises(ValueError): prepare(source,source/'conversion')


if __name__=='__main__': unittest.main()
