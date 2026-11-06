import torch, bitsandbytes as bnb
lin = torch.nn.Linear(64, 32).to(torch.bfloat16)
q = bnb.nn.Linear4bit(64, 32, bias=True, compute_dtype=torch.bfloat16, quant_type='nf4')
print('fresh weight', q.weight.dtype, q.weight.shape, type(q.weight).__name__)
print('nb quantized flag', getattr(q.weight, 'bnb_quantized', None))
p = bnb.nn.Params4bit(lin.weight.data.clone(), requires_grad=False, quant_type='nf4', blocksize=64)
print('p', p.dtype, p.shape, p.bnb_quantized, p.quant_storage)
q.weight = p
print('after assign', q.weight.dtype, q.weight.bnb_quantized)
try:
    q = q.to('cuda')
    print('ok', q.weight.dtype, q.weight.shape, q.weight.quant_state is not None)
except Exception as e:
    print('FAIL', type(e).__name__, e)
    import traceback; traceback.print_exc()
