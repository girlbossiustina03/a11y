"""ChatML rendering for the non-thinking Qwen3 Instruct router.

Use the same assistant prefix for masked training and MLX inference. No template-
inserted think blocks; EOS is the trained <|im_end|>, not an unfinished JSON turn.
"""
import json

TEMPLATE = """{% for message in messages %}{{ '<|im_start|>' + message['role'] + '\\n' + message['content'] + '<|im_end|>\\n' }}{% endfor %}{% if add_generation_prompt %}{{ '<|im_start|>assistant\\n' }}{% endif %}"""


def install(tokenizer):
    # MLX TokenizerWrapper delegates reads, so mutate its underlying HF tokenizer.
    target = getattr(tokenizer, '_tokenizer', None)
    if target is None or not hasattr(target, 'apply_chat_template'):
        target = tokenizer
    target.chat_template = TEMPLATE
    return tokenizer


def check_training_rows(rows, tokenizer, max_length):
    for i, row in enumerate(rows):
        msgs = row['messages']
        json.loads(msgs[-1]['content'])
        rendered = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
        prefix = tokenizer.apply_chat_template(msgs[:-1], tokenize=False, add_generation_prompt=True)
        expected = msgs[-1]['content'] + '<|im_end|>\n'
        if not rendered.startswith(prefix) or rendered[len(prefix):] != expected:
            raise ValueError(f'Row {i}: assistant template mismatch')
        tokens = tokenizer.apply_chat_template(msgs, add_generation_prompt=False, return_dict=False)
        prefix_tokens = tokenizer.apply_chat_template(msgs[:-1], add_generation_prompt=True, return_dict=False)
        if tokens[:len(prefix_tokens)] != prefix_tokens:
            raise ValueError(f'Row {i}: token mask boundary mismatch')
        if len(tokens) > max_length:
            raise ValueError(f'Row {i}: {len(tokens)} tokens exceeds {max_length}; would truncate JSON/EOS')
