import torch, time
def bench(M, K, N, dtype=torch.bfloat16):
    w = torch.randn(N, K, device='cuda', dtype=dtype)
    x = torch.randn(M, K, device='cuda', dtype=dtype)
    for _ in range(3): y = x @ w.T
    torch.cuda.synchronize(); t0=time.time()
    n=10
    for _ in range(n): y = x @ w.T
    torch.cuda.synchronize(); dt=(time.time()-t0)/n
    print(f'M{M} K{K} N{N} {str(dtype).split(".")[-1]}: {dt*1000:.2f} ms  {2*M*K*N/dt/1e9:.0f} GFLOP/s  {N*K*w.element_size()/dt/1e9:.0f} GB/s')
bench(1, 4096, 4096)
bench(16, 4096, 4096)
bench(512, 4096, 4096)
bench(1, 4096, 11008)
bench(2048, 4096, 4096)
bench(1, 4096, 11008, torch.float16)
print('name', torch.cuda.get_device_name(0))
