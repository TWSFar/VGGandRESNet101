import torch
import torch.nn as nn
import torch.nn.init as init
import numpy as np


def resume_load_weights(model, optimizer, path):
    chkpt = torch.load(path)
    model.load_state_dict(chkpt['model'])
    best_loss = chkpt['best_loss']
    start_epoch = chkpt['epoch'] + 1
    if chkpt['optimizer'] is not None:
        try:
            optimizer.load_state_dict(chkpt['optimizer'])
        except:
            print('load optimizer failure...')
    del chkpt
    return model, best_loss, start_epoch, optimizer


def res_per_class(stats, total, num_class):
    p, r, f1 = np.zeros(num_class), np.zeros(num_class), np.zeros(num_class)
    for i in range(num_class):
        cur_class = (stats[:, 1] == i)
        num = cur_class.sum()
        TP = (stats[cur_class, 0] == i).sum()
        FN = (num - TP)
        FP = ((stats[:, 0] == i).sum() - TP)
        
        p[i] = 1.0 * TP / (TP + FP + 1e-16)
        r[i] = 1.0 * TP / (TP + FN + 1e-16)
        f1[i] = 2.0 * p[i] * r[i] / (p[i] + r[i] + 1e-16)

    return p, r, f1


# initialize model weights
def weights_init(m):
    if isinstance(m, nn.Conv2d):
        init.xavier_uniform_(m.weight.data)
        if m.bias:
            m.bias.data.zero_()


def compute_loss():
    pass


def create_vis_plot(vis, X_, Y_, title_, legend_):
    return vis.line(
        X=torch.zeros((1,)).cpu(),
        Y=torch.zeros((1, len(legend_))).cpu(),
        opts=dict(
            xlabel=X_,
            ylabel=Y_,
            title=title_,
            legend=legend_
        )
    )


def update_vis_plot(vis, item, loss, window, update_type):
 
    vis.line(
        X = torch.ones((1, len(loss))).cpu() * item,
        Y = torch.Tensor(loss).unsqueeze(0).cpu(),
        win = window,
        update = update_type
    )

def model_info(model, report='summary'):
    n_p = sum(x.numel() for x in model.parameters())
    n_g = sum(x.numel() for x in model.parameters() if x.requires_grad)
    if report is 'full':
        print("%5s %40s %9s %12s %20s %10s %10s" % ('layer', 'name', 'gradient', 'parameters', 'shape', 'mu', 'sigma'))
        for i, (name, p) in enumerate(model.named_parameters()):
            name = name.replace('module_list.', '')
            print('%5g %50g %9s %12g %20g %10.3g %10.3g' % 
                (i, name, p.requires_grad, p.numel(), list(p.shape), p.mean(), p.std()))
    print('Model Summary: %g layers, %g parameters, %g gradients\n' % (len(list(model.parameters())), n_p, n_g))
