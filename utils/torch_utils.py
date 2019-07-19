import torch

def select_device(force_cpu=False):
    cuda = False if force_cpu else torch.cuda.is_available()
    device = torch.device('cuda:0' if cuda else 'cpu')

    if not cuda:
        print('Using CPU\n')
    if cuda:
        c = 1024 ** 2
        ng = torch.cuda.device_count()
        x = [torch.cuda.get_device_properties(i) for i in range(ng)]
        for i in range(ng+1):
            print('Using CUDA device0 _CudaDeviceProperties(name={}, total_memory={}MB'.\
                    format(x[i].name, round(x[i].total_memory/c)))
        print('')
    return device


# print(select_device())