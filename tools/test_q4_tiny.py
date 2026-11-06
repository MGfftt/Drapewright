import os, sys, torch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # CG-WIN: run from anywhere
from transformers import LlamaConfig, LlamaForCausalLM
from peft import LoraConfig, get_peft_model
from llava import win_compat

cfg = LlamaConfig(vocab_size=128, hidden_size=128, intermediate_size=256,
                  num_hidden_layers=2, num_attention_heads=4, num_key_value_heads=4,
                  max_position_embeddings=64)
m = LlamaForCausalLM(cfg).to(torch.bfloat16)
m = get_peft_model(m, LoraConfig(r=8, lora_alpha=16, target_modules=['q_proj','v_proj'],
                                 lora_dropout=0.0, bias='none', task_type='CAUSAL_LM'))
core = m.base_model.model
q_proj = core.model.layers[0].self_attn.q_proj
print('wrapper', type(q_proj).__name__, 'base_layer', type(q_proj.base_layer).__name__)
x = torch.randint(0, 128, (1, 8))
with torch.no_grad():
    ref = core(input_ids=x).logits.float().clone()
win_compat.quantize_4bit(m)
print('after: base_layer', type(core.model.layers[0].self_attn.q_proj.base_layer).__name__)
print('after: k_proj  ', type(core.model.layers[0].self_attn.k_proj).__name__)
print('after: lm_head ', type(core.lm_head).__name__)
with torch.no_grad():
    out = core(input_ids=x.cuda()).logits.float().cpu()
print('logits maxdiff %.4f' % (out - ref).abs().max().item())
print('cuda alloc MB', round(torch.cuda.memory_allocated()/2**20, 1))
