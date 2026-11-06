import torch, bitsandbytes as bnb
lin = torch.nn.Linear(1024, 1024).to('cuda', torch.bfloat16)
ref = lin(torch.randn(4,1024, device='cuda', dtype=torch.bfloat16))
q = bnb.nn.Linear4bit(1024, 1024, bias=True, compute_dtype=torch.bfloat16, quant_type='nf4')
q.weight = bnb.nn.Params4bit(lin.weight.data.to('cpu'), requires_grad=False, quant_type='nf4', blocksize=64)
q.bias = torch.nn.Parameter(lin.bias.data.to('cpu').clone())
q = q.to('cuda')
x = torch.randn(4, 1024, device='cuda', dtype=torch.bfloat16)
y = q(x)
print('4bit ok', tuple(y.shape), y.dtype, 'maxdiff %.4f' % float((y.float()-lin(x).float()).abs().max()))
# speed test: 4096x4096x4096 matmul
import time
w = torch.randn(4096, 4096, device='cuda', dtype=torch.bfloat16)
xx = torch.randn(1, 4096, device='cuda', dtype=torch.bfloat16)
for _ in range(3):
    h = xx @ w.T
torch.cuda.synchronize()
t0=time.time()
for _ in range(20):
    h = xx @ w.T
torch.cuda.synchronize()
dt=(time.time()-t0)/20
print('bf16 1x4096x4096 GEMM ms %.2f -> %.0f GFLOP/s' % (dt*1000, 2*4096*4096/dt/1e9))
print('mem MB', round(torch.cuda.max_memory_allocated()/2**20, 1))
